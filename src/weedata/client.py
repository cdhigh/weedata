#!/usr/bin/env python3
# -*- coding:utf-8 -*-
#an ORM/ODM for Google Cloud Datastore/MongoDB, featuring a compatible interface with Peewee.
#Author: cdhigh <http://github.com/cdhigh>
#Repository: <https://github.com/cdhigh/weedata>
import os, uuid
from itertools import chain
from operator import attrgetter

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

try:
    import redis
except ImportError:
    redis = None

from .model import Model, BaseModel
from .fields import Filter

#if os.environ.get('WEEDATA_TEST_BACKEND') == 'datastore':
#    from fake_datastore import *
#    print('Alert: using fake datastore stub!!!')

class NosqlClient(object):
    stringifyStore = False #For redis, it's True

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
    def close(self):
        return False
    def connect(self, **kwargs):
        return True
    def atomic(self, **kwargs):
        return fakeTransation()
    def transaction(self, **kwargs):
        return fakeTransation()
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
        return {Filter.EQ: '=', Filter.NE: '!=', Filter.LT: '<', Filter.GT: '>', Filter.LE: '<=',
            Filter.GE: '>=', Filter.IN: 'IN', Filter.NIN: 'NOT_IN'}.get(op, op)

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
            return 1
        else:
            return 0

    def delete_many(self, models):
        keys = [e._key for e in models if e._key]
        if keys:
            self.client.delete_multi(keys)
            return len(keys)
        else:
            return 0

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
        return len(list(self.execute(queryObj, parent_key=parent_key)))
        #count_query = self.get_aggregation_query(queryObj, parent_key).count()
        #with count_query.fetch() as query_result:
        #    return next(query_result).value if query_result else 0

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
                setattr(inst, field_name, fields[field_name]._python_value(value))
            else:
                setattr(inst, field_name, value)
        inst.clear_dirty(list(fields.keys()))
        return inst.set_id(key.to_legacy_urlsafe().decode())

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
                if operator == Filter.OR:
                    subqueries = query_dict[operator]
                    ds_filters = list(chain.from_iterable([to_ds_query(subquery) for subquery in subqueries]))
                    converted.append(qr.Or(ds_filters))
                elif operator == Filter.AND:
                    subqueries = query_dict[operator]
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
        if isinstance(key, Model):
            key = key.get_id()
        if isinstance(key, Key):
            return key
        elif kind and (isinstance(key, int) or key.isdigit()):
            return self.generate_key(kind, int(key))
        else:
            return Key.from_legacy_urlsafe(key)

    def drop_table(self, model):
        kind = model._meta.name if issubclass(model, Model) else model
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
    def __init__(self, project, host='127.0.0.1', port=27017, username=None, password=None):
        self.project = project
        self.host = host
        self.port = port
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
        id_ = model.get_id()
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
            return self._db[model._meta.name].delete_one({'_id': model._id}).deleted_count
        else:
            return 0

    def delete_many(self, models):
        return sum([self.delete_one(model) for model in models])
        
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
                setattr(inst, field_name, fields[field_name]._python_value(value))
            else:
                setattr(inst, field_name, value)
        inst.clear_dirty(list(fields.keys()))
        return inst.set_id(str(inst._id))

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
        if isinstance(key, Model):
            key = key.get_id()
        if isinstance(key, ObjectId):
            return key
        else:
            return ObjectId(key)

    def create_index(self, model, keys, **kwargs):
        self._db[model._meta.name].create_index(keys, **kwargs)

    def drop_table(self, model):
        model = model._meta.name if issubclass(model, Model) else model
        self._db.drop_collection(model)

    def close(self):
        self.client.close()


class RedisDbClient(NosqlClient):
    stringifyStore = True
    urlsafe_alphabet = '0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz'

    def __init__(self, project, host='127.0.0.1', port=6379, db=0, password=None, key_sep=':'):
        if '://' in host:
            self.redis = redis.from_url(host)
        else:
            self.redis = redis.Redis(host=host, port=port, db=db, password=password)
        self.prefix = project
        self.key_sep = key_sep

    @classmethod
    def op_map(cls, op):
        return {Filter.EQ: '==', Filter.NE: '!=', Filter.LT: '<', Filter.GT: '>', Filter.LE: '<=',
            Filter.GE: '>=', Filter.IN: 'in', Filter.NIN: 'not in'}.get(op, op)

    #generate id of a 22 characters string instead of 36 characters UUID
    @classmethod
    def generate_id(cls):
        id_ = uuid.uuid4().int
        if id_ == 0:
            return '0'
        digits = []
        while id_: #len(urlsafe_alphabet)==62
            digits.append(cls.urlsafe_alphabet[int(id_ % 62)])
            id_ //= 62
        return ''.join(digits[::-1])

    def build_key(self, model, id_):
        #compatible for class and instance
        model = model._meta.name if isinstance(model, (BaseModel, Model)) else model
        return f'{self.prefix}{self.key_sep}{model}{self.key_sep}{id_}'

    @classmethod
    def db_id_name(cls):
        return "id"

    #InsertOneResult has inserted_id property
    def insert_one(self, model_class, data: dict):
        id_ = self.generate_id()
        self.redis.hmset(self.build_key(model_class, id_), data)
        return id_

    #InsertManyResult has inserted_ids property
    def insert_many(self, model_class, datas: list):
        return [self.insert_one(model_class, data) for data in datas]
        
    def update_one(self, model):
        id_ = model.get_id()
        if id_: #update
            data = model.dicts(remove_id=True, db_value=True, only_dirty=True)
            if data:
                key = self.build_key(model, id_)
                self.redis.hmset(key, data)
                model.clear_dirty(list(data.keys()))
            return id_
        else: #insert
            data = model.dicts(remove_id=True, db_value=True)
            model.clear_dirty(list(data.keys()))
            return self.insert_one(model.__class__, data)
     
    def delete_one(self, model):
        id_ = model.get_id()
        if id_:
            return self.redis.delete(self.build_key(model, id_))
        else:
            return 0

    def delete_many(self, models):
        return sum([self.delete_one(model) for model in models])
        
    def execute(self, queryObj, page_size=500, parent_key=None):
        model_class = queryObj.model_class
        filters = [flt.clone('utf-8') for flt in queryObj._filters]
        fields = {name.encode('utf-8'): inst for name, inst in model_class._meta.fields.items()}
        results = []
        key_sep = self.key_sep.encode('utf-8')
        id_name = self.db_id_name().encode('utf-8')
        for key in self.redis.keys(self.build_key(model_class, '*')):
            data = self.redis.hgetall(key)
            data[id_name] = key.rsplit(key_sep, 1)[-1] #set primary key
            for flt in filters:
                if not self._matches_query(data, flt, fields):
                    break
            else:
                #if queryObj._projection:
                #    for k in data:
                #        if k not in self._projection:
                #            data[k] = None
                results.append(data)

        if queryObj._order:
            order = queryObj._order[0].encode('utf-8')
            reverse = False
            if order.startswith(b'-'):
                order = order[1:]
                reverse = True
            results.sort(key=lambda x: x.get(order), reverse=reverse)

        for ret in (results[:queryObj._limit] if queryObj._limit else results):
            yield self.make_instance(model_class, ret)

    def _matches_query(self, data: dict, flt: Filter, fields: dict):
        if not flt.bit_op:
            item = flt.item
            op = flt.op
            dbValue = data.get(item, None)
            if dbValue is None or item not in fields:
                return False

            value = fields[item]._db_value(flt.value)
            return (((op == Filter.EQ) and (value == dbValue)) or
                ((op == Filter.NE) and (value != dbValue)) or
                ((op == Filter.LT) and (value < dbValue)) or
                ((op == Filter.GT) and (value > dbValue)) or
                ((op == Filter.LE) and (value <= dbValue)) or
                ((op == Filter.GE) and (value >= dbValue)) or
                ((op == Filter.IN) and (value in dbValue)) or
                ((op == Filter.NIN) and (value not in dbValue)))
        elif flt.bit_op == Filter.AND:
            for c in flt.children:
                if not self._matches_query(data, c, fields):
                    return False
            return True
        elif flt.bit_op == Filter.OR:
            for c in flt.children:
                if self._matches_query(data, c, fields):
                    return True
            return False
        else:
            raise ValueError(f"Unsupported bit operator: {flt.bit_op}")
        
    def count(self, queryObj, parent_key=None):
        return len(list(self.execute(queryObj)))

    #make Model instance from database data
    def make_instance(self, model_class, raw):
        inst = model_class()
        fields = model_class._meta.fields
        for name, value in raw.items():
            name = name.decode('utf-8') if isinstance(name, bytes) else name
            setattr(inst, name, fields[name]._python_value(value) if name in fields else value)
            
        inst.clear_dirty(list(fields.keys()))
        return inst.set_id(str(getattr(inst, self.db_id_name())))

    def ensure_key(self, key, kind=None):
        return key.get_id() if isinstance(key, Model) else str(key)
        
    def drop_table(self, model):
        for key in self.redis.keys(self.build_key(model, '*')):
            self.redis.delete(key)


class fakeTransation:
    def __enter__(self, *args, **kwargs):
        return self
    def __exit__(self, *args, **kwargs):
        pass
