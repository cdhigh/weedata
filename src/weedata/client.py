#!/usr/bin/env python3
# -*- coding:utf-8 -*-
#an ORM/ODM for Google Cloud Datastore/MongoDB, featuring a compatible interface with Peewee.
#Author: cdhigh <http://github.com/cdhigh>
#Repository: <https://github.com/cdhigh/weedata>
import os
from itertools import chain

try:
    from google.cloud import datastore
    from google.cloud.datastore import Key
    from google.cloud.datastore import query as qr
except ImportError:
    datastore = None

try:
    import pymongo
    from bson.objectid import ObjectId
except ImportError:
    pymongo = None

from .model import BaseModel

#if os.environ.get('WEEDATA_TEST_BACKEND') == 'datastore':
#    from fake_datastore import *
#    print('Alert: using fake datastore stub!!!')

class NosqlClient(object):
    def bind(self, models):
        for model in models:
            model.bind(self)
    def drop_tables(self, models, **kwargs):
        for model in models:
            self.drop_table(model)
    def create_tables(self, models, **kwargs):
        for model in models:
            model.create_table(**kwargs)
    def create_index(self, model, keys, **kwargs):
        pass
    def is_closed(self):
        return False
    def connect(self, **kwargs):
        return True
    @classmethod
    def op_map(cls, op):
        return op
    
class DatastoreClient(NosqlClient):
    def __init__(self, project=None, namespace=None, credentials=None, _http=None):
        self.project = project or os.getenv("GOOGLE_CLOUD_PROJECT", None)
        self.credentials = credentials
        self.namespace = namespace
        self._http = _http
        self.client = datastore.Client(project=self.project, namespace=self.namespace, credentials=self.credentials, _http=self._http)
    
    @classmethod
    def db_id_name(cls):
        return "__key__"

    @classmethod
    def op_map(cls, op):
        return {'$eq': '=', '$ne': '!=', '$lt': '<', '$gt': '>', '$lte': '<=',
            '$gte': '>=', '$in': 'IN', '$nin': 'NOT_IN'}.get(op, op)

    def insert_one(self, model_class, data: dict):
        entity = self.create_entity(data, kind=model_class._meta.name)
        self.client.put(entity)
        return entity.key.to_legacy_urlsafe().decode()

    def insert_many(self, model_class, datas: list):
        ids = []
        kind = model_class._meta.name
        for batch in self.split_batches(datas, 500):
            entities = [self.create_entity(data, kind=kind) for data in batch]
            self.client.put_multi(entities)
            ids.extend([e.key.to_legacy_urlsafe().decode() for e in entities])
        return ids

    def update_one(self, model):
        only_dirty = bool(model._key)
        data = model.dicts(remove_id=True, db_value=True, only_dirty=only_dirty)
        entity = self.create_entity(data, kind=model._meta.name, key=model._key)
        if data:
            self.client.put(entity)
            model.clear_dirty(list(data.keys()))
        return entity.key.to_legacy_urlsafe().decode()
        
    def delete_one(self, model):
        if model._key:
            self.client.delete(model._key)

    def delete_many(self, models):
        keys = [e._key for e in models if e._key]
        if keys:
            self.client.delete_multi(keys)

    def execute(self, queryObj, page_size=500, parent_key=None):
        model_class = queryObj.model_class
        kind = model_class._meta.name
        query = self.get_query(kind, parent_key)
        self.apply_query_condition(queryObj, query)

        limit = queryObj._limit
        batch_size = min(page_size, limit) if limit else page_size
        yield from self.query_fetch(query, batch_size, limit, model_class)

    #count aggregation query
    def count(self, queryObj, parent_key=None):
        count_query = self.get_aggregation_query(queryObj, parent_key).count()
        with count_query.fetch() as query_result:
            return next(query_result).value if query_result else 0

    #sum aggregation query
    def sum(self, queryObj, field, parent_key=None):
        field = field.name if isinstance(field, Field) else field
        sum_query = self.get_aggregation_query(queryObj, parent_key).sum(field)
        with sum_query.fetch() as query_result:
            return next(query_result).value if query_result else 0

    #avg aggregation query
    def avg(self, queryObj, field, parent_key=None):
        field = field.name if isinstance(field, Field) else field
        sum_query = self.get_aggregation_query(queryObj, parent_key).avg(field)
        with sum_query.fetch() as query_result:
            return next(query_result).value if query_result else 0

    #generate model instance(model_class!=None) or entity(model_class=None)
    def query_fetch(self, query, batch_size=500, limit=0, model_class=None):
        cursor = None
        count = 0
        while True:
            last_entity = None
            result = query.fetch(start_cursor=cursor, limit=batch_size)

            for entity in result:
                last_entity = self.make_instance(model_class, entity) if model_class else entity
                yield last_entity
                count += 1
            cursor = result.next_page_token
            if not cursor or (last_entity is None) or (limit and (count >= limit)):
                break

    #make Model instance from database data
    def make_instance(self, model_class, raw):
        key = raw.key
        inst = model_class(_key=key)
        fields = inst._meta.fields
        for field_name, value in raw.items():
            if field_name in fields:
                setattr(inst, field_name, fields[field_name].python_value(value))
            else:
                setattr(inst, field_name, value)
        inst.clear_dirty(list(fields.keys()))
        setattr(inst, inst._meta.primary_key, key.to_legacy_urlsafe().decode())
        return inst

    def get_query(self, kind, parent_key=None):
        return self.client.query(kind=kind, ancestor=parent_key)

    def get_aggregation_query(self, queryObj, parent_key=None):
        kind = queryObj.model_class._meta.name
        query = self.get_query(kind, parent_key)
        self.apply_query_condition(queryObj, query)
        return self.client.aggregation_query(query=query)

    def apply_query_condition(self, queryObj, query):
        flt = self.build_ds_filter(queryObj.filters())
        if flt:
            query.add_filter(filter=flt)

        if queryObj._projection:
            query.projection = queryObj._projection
        if queryObj._order:
            query.order = queryObj._order
        if queryObj._distinct:
            query.distinct_on = queryObj._distinct
        return query

    #convert mongo filters dict to datastore Query PropertyFilter
    def build_ds_filter(self, mongo_filters):
        def to_ds_query(query_dict):
            if not query_dict:
                return []

            converted = []
            for operator in query_dict.keys():
                if operator == '$or':
                    subqueries = query_dict['$or']
                    ds_filters = list(chain.from_iterable([to_ds_query(subquery) for subquery in subqueries]))
                    converted.append(qr.Or(ds_filters))
                elif operator == '$and':
                    subqueries = query_dict['$and']
                    ds_filters = list(chain.from_iterable([to_ds_query(subquery) for subquery in subqueries]))
                    converted.append(qr.And(ds_filters))
                else:
                    prop_flts = []
                    for field, condition in query_dict.items():
                        if isinstance(condition, dict):
                            for op, value in condition.items():
                                prop_flts.append(qr.PropertyFilter(field, op, value))
                        else:
                            prop_flts.append(qr.PropertyFilter(field, '=', condition))
                    converted.extend(prop_flts)
            return converted

        result = to_ds_query(mongo_filters)
        if len(result) > 1:
            return qr.And(result)
        elif len(result) == 1:
            return result[0]
        else:
            return None

    #split a large list into some small list
    def split_batches(self, entities, batch_size):
        return [entities[i:i + batch_size] for i in range(0, len(entities), batch_size)]

    #create datastore entity instance
    def create_entity(self, data: dict, kind=None, key=None, parent_key=None):
        if not key:
            key = self.generate_key(kind, parent_key=parent_key)
        entity = datastore.Entity(key=key)
        entity.update(data)
        return entity

    def atomic(self, **kwargs):
        return self.client.transaction(**kwargs)

    def transaction(self, **kwargs):
        return self.client.transaction(**kwargs)

    def generate_key(self, kind, identifier=None, parent_key=None):
        if identifier:
            return self.client.key(kind, identifier, parent=parent_key)
        else:
            return self.client.key(kind, parent=parent_key)

    def ensure_key(self, key, kind=None):
        if isinstance(key, Key):
            return key
        elif kind and (isinstance(key, int) or key.isdigit()):
            return self.generate_key(kind, int(key))
        else:
            return Key.from_legacy_urlsafe(key)

    def drop_table(self, model):
        kind = model._meta.name if isinstance(model, BaseModel) else model
        query = self.get_query(kind)
        query.projection = ['__key__']
        keys = []
        cursor = None
        while True:
            result = query.fetch(start_cursor=cursor, limit=500)
            keys.extend([entity.key for entity in result])
            cursor = result.next_page_token
            if not cursor:
                break
        if keys:
            self.client.delete_multi(keys)

    def close(self):
        self.client.close()

class MongoDbClient(NosqlClient):
    def __init__(self, project, host=None, port=None, username=None, password=None):
        self.project = project
        self.host = host or 'localhost'
        self.port = port or 27017
        if self.host.startswith('mongodb://'):
            self.client = pymongo.MongoClient(self.host)
        else:
            self.client = pymongo.MongoClient(host=self.host, port=self.port, username=username, password=password)
        self._db = self.client[project]
    
    @classmethod
    def db_id_name(cls):
        return "_id"

    #InsertOneResult has inserted_id property
    def insert_one(self, model_class, data: dict):
        id_ = self._db[model_class._meta.name].insert_one(data).inserted_id
        return str(id_)

    #InsertManyResult has inserted_ids property
    def insert_many(self, model_class, datas: list):
        ids = self._db[model_class._meta.name].insert_many(datas).inserted_ids
        return [str(id_) for id_ in ids]
        
    def update_one(self, model):
        id_ = getattr(model, model._meta.primary_key, None)
        if id_: #update
            data = model.dicts(remove_id=True, db_value=True, only_dirty=True)
            if data:
                self._db[model._meta.name].update({'_id': ObjectId(id_)}, {'$set': data})
                model.clear_dirty(list(data.keys()))
            return id_
        else: #insert
            data = model.dicts(remove_id=True, db_value=True)
            model.clear_dirty(list(data.keys()))
            return self.insert_one(model.__class__, data)
     
    def delete_one(self, model):
        if model._id:
            self._db[model._meta.name].delete_one({'_id': model._id})

    def delete_many(self, models):
        for model in models:
            self.delete_one(model)
        
    def execute(self, queryObj, page_size=500, parent_key=None):
        model_class = queryObj.model_class
        collection = self._db[model_class._meta.name]
        sort = [(item[1:], pymongo.DESCENDING) if item.startswith('-') else (item, pymongo.ASCENDING) for item in queryObj._order]
        projection = self.build_projection(queryObj)

        with collection.find(queryObj.filters(), projection=projection) as cursor:
            if sort:
                cursor = cursor.sort(sort)
            if queryObj._limit:
                cursor = cursor.limit(queryObj._limit)
            for item in cursor:
                yield self.make_instance(model_class, item)

    def count(self, queryObj, parent_key=None):
        return self._db[queryObj.model_class._meta.name].count_documents(queryObj.filters())

    #make Model instance from database data
    def make_instance(self, model_class, raw):
        inst = model_class()
        fields = inst._meta.fields
        for field_name, value in raw.items():
            if field_name in fields:
                setattr(inst, field_name, fields[field_name].python_value(value))
            else:
                setattr(inst, field_name, value)
        inst.clear_dirty(list(fields.keys()))
        setattr(inst, inst._meta.primary_key, str(inst._id)) #set primary_key
        return inst

    #make projection dict to fetch some field only
    def build_projection(self, queryObj):
        proj = queryObj._projection
        result = {}
        if proj:
            _meta = queryObj.model_class._meta
            for field_name in _meta.fields.keys():
                if (field_name != _meta.primary_key) and (field_name not in proj):
                    result[field_name] = 0
            return result
        else:
            return None

    def ensure_key(self, key, kind=None):
        if isinstance(key, ObjectId):
            return key
        else:
            return ObjectId(key)

    def atomic(self, **kwargs):
        #return self.client.start_session(**kwargs)
        return fakeTransation()

    def transaction(self, **kwargs):
        #return self.client.start_session(**kwargs)
        return fakeTransation()

    def create_index(self, model, keys, **kwargs):
        self._db[model._meta.name].create_index(keys, **kwargs)

    def drop_table(self, model):
        model = model._meta.name if isinstance(model, BaseModel) else model
        self._db.drop_collection(model)

    def close(self):
        self.client.close()


class fakeTransation:
    def __enter__(self, *args, **kwargs):
        return self
    def __exit__(self, *args, **kwargs):
        pass
