#!/usr/bin/env python3
# -*- coding:utf-8 -*-
#An ORM/ODM for Google Cloud Datastore/MongoDB/redis, featuring a compatible interface with Peewee.
#Author: cdhigh <http://github.com/cdhigh>
#Repository: <https://github.com/cdhigh/weedata>
#Pypi package: <https://pypi.org/project/weedata>
import os, re, sys, uuid, pickle, shutil, logging
from itertools import chain
from operator import attrgetter
from collections import defaultdict
from urllib.parse import urlparse, parse_qs

try:
    from google.cloud import datastore
    from google.cloud.datastore import Key
    from google.cloud.datastore import query as qr
except Exception:  # pragma: no cover
    datastore = None
    Key = None
    qr = None

try:
    import pymongo
    from bson.objectid import ObjectId
except Exception:  # pragma: no cover
    pymongo = None

try:
    import redis
except Exception:  # pragma: no cover
    redis = None

from .model import Model, BaseModel
from .fields import Field, Filter

if os.environ.get('WEEDATA_TEST_BACKEND') == 'datastore': # pragma: no cover
    from fake_datastore import *
    print('Alert: using fake datastore stub!!!')

class FakeTransaction:
    def __enter__(self):
        return self
    def __exit__(self, exc_type, exc_val, exc_tb):
        pass

class NosqlClient(object):
    bytes_store = False #For redis, it's True
    def __init__(self, *args, **kwargs):
        self.log = logging.getLogger('weedata')

    def bind(self, models):
        for model in models:
            model.bind(self)
    def drop_tables(self, models, **kwargs):
        for model in models:
            self.drop_table(model)
    def create_tables(self, models, **kwargs):
        for model in models:
            model.create_table(**kwargs)
    def create_index(self, model, keys, unique=False, **kwargs):
        pass
    def rebuild_index(self, klass):
        pass # pragma: no cover
    def is_closed(self):
        return False
    def close(self):
        return False
    def connect(self, **kwargs):
        return True
    def atomic(self, **kwargs):
        return FakeTransaction()
    def transaction(self, **kwargs):
        return FakeTransaction()
    def key_to_id(self, key):
        #convert a native key object into the string form stored in id/foreign key fields
        return str(key)
    @classmethod
    def op_map(cls, op):
        return op

class DatastoreClient(NosqlClient):
    def __init__(self, project=None, namespace=None, credentials=None, _http=None):
        super().__init__()
        if datastore is None: # pragma: no cover
            raise ImportError('google-cloud-datastore is required for DatastoreClient')
        self.project = project or os.getenv("GOOGLE_CLOUD_PROJECT", None)
        self.credentials = credentials
        self.namespace = namespace
        self._http = _http
        self.client = datastore.Client(project=self.project, namespace=self.namespace,
            credentials=self.credentials, _http=self._http)

    @classmethod
    def db_id_name(cls):
        return "__key__"

    @classmethod
    def op_map(cls, op):
        return {Filter.EQ: '=', Filter.NE: '!=', Filter.LT: '<', Filter.GT: '>', Filter.LE: '<=',
            Filter.GE: '>=', Filter.IN: 'IN', Filter.NIN: 'NOT_IN'}.get(op, op)

    def insert_one(self, klass, data: dict):
        model = klass(**data)
        data = model.dicts(remove_id=True, db_value=True)
        entity = self.create_entity(data, model)
        self.client.put(entity)
        return entity.key.to_legacy_urlsafe().decode()

    def insert_many(self, klass, datas: list):
        ids = []
        kind = klass._meta.name
        for batch in self.split_batches(datas, 500):
            entities = []
            for data in batch:
                model = klass(**data)
                data = model.dicts(remove_id=True, db_value=True)
                entities.append(self.create_entity(data, model))
            self.client.put_multi(entities)
            ids.extend([e.key.to_legacy_urlsafe().decode() for e in entities])
        return ids

    def update_one(self, model):
        data = model.dicts(remove_id=True, db_value=True, only_dirty=False) #datastore update all fields always
        entity = self.create_entity(data, model, key=self.model_key(model))
        if data:
            self.client.put(entity)
            model.clear_dirty(list(data.keys()))
        #keep the real key, so later saves update the same entity instead of duplicating it
        model._key = entity.key
        return model.set_id(entity.key.to_legacy_urlsafe().decode())

    def delete_one(self, model):
        key = self.model_key(model)
        if key:
            self.client.delete(key)
            return 1
        else:
            return 0

    def delete_many(self, models):
        keys = [k for k in (self.model_key(e) for e in models) if k]
        if keys:
            self.client.delete_multi(keys)
            return len(keys)
        else:
            return 0

    def execute(self, queryObj, page_size=500, parent_key=None, limit=None, as_dict=False):
        if self.has_impossible_filter(queryObj._filters):
            return #a condition that can never match, e.g. in_([])
        klass = queryObj.model_class
        kind = klass._meta.name
        query = self.client.query(kind=kind, ancestor=parent_key)
        self.apply_query_condition(queryObj, query)

        limit = limit if (limit and limit > 0) else queryObj._limit
        batch_size = min(page_size, limit) if limit else page_size
        yield from self.query_fetch(query, batch_size, limit, klass, as_dict)

    #count aggregation query
    def count(self, queryObj, parent_key=None):
        return self.aggre_execute(queryObj, parent_key, 'count')

    #sum aggregation query
    def sum(self, queryObj, field, parent_key=None):  # pragma: no cover
        field = field.name if isinstance(field, Field) else field
        return self.aggre_execute(queryObj, parent_key, 'sum', field)

    #avg aggregation query
    def avg(self, queryObj, field, parent_key=None):  # pragma: no cover
        field = field.name if isinstance(field, Field) else field
        return self.aggre_execute(queryObj, parent_key, 'avg', field)

    #aggregation query
    #func: 'count', 'sum', 'avg'
    #arg: field name if func is 'sum' or 'avg'
    def aggre_execute(self, queryObj, parent_key, func, arg=None):
        if self.has_impossible_filter(queryObj._filters):
            return 0
        kind = queryObj.model_class._meta.name
        query = self.client.query(kind=kind, ancestor=parent_key)
        self.apply_query_condition(queryObj, query)
        query_func = getattr(self.client.aggregation_query(query=query), func)
        query = query_func(arg) if arg else query_func()
        with query.fetch() as result:
            try:
                return next(result).value
            except StopIteration:
                return 0

    #True when the filter tree can never match any row (an empty in_() list for example)
    def has_impossible_filter(self, filters):
        for f in filters or []:
            if f.bit_op == Filter.AND:
                if any(self.has_impossible_filter([c]) for c in f.children):
                    return True
            elif f.bit_op == Filter.OR:
                if f.children and all(self.has_impossible_filter([c]) for c in f.children):
                    return True
            elif not f.bit_op:
                if f.op == Filter.IN and isinstance(f.value, (list, tuple, set)) and not f.value:
                    return True
            #NOR never forces an empty result by itself
        return False

    #make Model instance(klass!=None) or entity(klass=None)
    def query_fetch(self, query, batch_size=500, limit=0, klass=None, as_dict=False):
        cursor = None
        count = 0
        while True:
            if limit and (count >= limit):
                break
            last_entity = None
            fetch_limit = batch_size
            if limit and (limit - count) < batch_size:
                fetch_limit = limit - count
            result = query.fetch(start_cursor=cursor, limit=fetch_limit)

            for entity in result:
                last_entity = self.make_instance(klass, entity) if klass else entity
                yield last_entity.dicts() if (last_entity and as_dict) else last_entity
                count += 1
            cursor = result.next_page_token
            if not cursor or (last_entity is None):
                break

    #make Model instance from database data
    def make_instance(self, klass, raw):
        key = raw.key
        inst = klass(_key=key)
        fields = inst._meta.fields
        for field_name, value in raw.items():
            if field_name in fields:
                setattr(inst, field_name, fields[field_name].python_value(value))
            else:
                setattr(inst, field_name, value)
        inst.clear_dirty(list(fields.keys()))
        return inst.set_id(key.to_legacy_urlsafe().decode())

    #queryObj - weedata QueryBuilder object
    #query - datastore query object
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

            for op in query_dict.keys():
                if op == Filter.NOR:
                    raise ValueError('datastore does not support nor query')

            converted = []
            for op in query_dict.keys():
                if op in (Filter.OR, Filter.AND): #recrusive
                    flts = list(chain.from_iterable(to_ds_query(subquery) for subquery in query_dict[op]))
                    converted.append(qr.Or(flts) if op == Filter.OR else qr.And(flts))

            #plain fields, every one of them is appended exactly once
            for field, condition in query_dict.items():
                if isinstance(condition, dict):
                    for op2, value in condition.items():
                        converted.append(qr.PropertyFilter(field, op2, value))
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
    def create_entity(self, data: dict, model, key=None, parent_key=None):
        if not key:
            key = self.generate_key(model._meta.name, parent_key=parent_key)
        entity = datastore.Entity(key=key, exclude_from_indexes=model._meta.exclude_from_indexes)
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
        if key is None:
            raise ValueError('Can not build a datastore key from None')
        if isinstance(key, Key):
            return key
        if isinstance(key, bytes):
            key = key.decode('utf-8')
        if kind and (isinstance(key, int) or key.isdigit()):
            return self.generate_key(kind, int(key))
        else:
            return Key.from_legacy_urlsafe(key)

    def key_to_id(self, key):
        #convert a native key to the string form stored in id/foreign key fields
        return key.to_legacy_urlsafe().decode() if isinstance(key, Key) else key

    #return the datastore key of an instance, deriving it from the app-level id when needed
    def model_key(self, model):
        if model._key is None:
            gid = model.get_id()
            if gid:
                model._key = self.ensure_key(gid, model._meta.name)
        return model._key

    def drop_table(self, model, parent_key=None):
        #compatible for class and instance
        kind = model._meta.name if isinstance(model, (BaseModel, Model)) else model
        query = self.client.query(kind=kind, ancestor=parent_key)
        #query.projection = ['__key__']
        query.keys_only()
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
    def __init__(self, project, dbUrl='mongodb://127.0.0.1:27017/'):
        super().__init__()
        if pymongo is None: # pragma: no cover
            raise ImportError('pymongo is required for MongoDbClient')
        self.project = project
        self.dbUrl = dbUrl
        self.client = pymongo.MongoClient(self.dbUrl, connect=False)
        self._db = self.client[project]

    @classmethod
    def db_id_name(cls):
        return "_id"

    def insert_one(self, klass, data: dict):
        model = klass(**data)
        data = model.dicts(remove_id=True, db_value=True)
        id_ = self._db[klass._meta.name].insert_one(data).inserted_id
        return str(id_)

    def insert_many(self, klass, datas: list):
        if not datas: #pymongo refuses an empty list
            return []
        datas = [klass(**data).dicts(remove_id=True, db_value=True) for data in datas]
        ids = self._db[klass._meta.name].insert_many(datas).inserted_ids
        return [str(id_) for id_ in ids]

    def update_one(self, model):
        id_ = model.get_id()
        if id_: #update
            data = model.dicts(remove_id=True, db_value=True, only_dirty=True)
            if data:
                self._db[model._meta.name].update_one({'_id': self.ensure_key(id_)}, {'$set': data})
                model.clear_dirty(list(data.keys()))
            return model
        else: #insert
            data = model.dicts(remove_id=True, db_value=True)
            model.clear_dirty(list(data.keys()))
            return model.set_id(self.insert_one(model.__class__, data))

    def delete_one(self, model):
        id_ = model.get_id()
        if id_:
            return self._db[model._meta.name].delete_one({'_id': self.ensure_key(id_)}).deleted_count
        else:
            return 0

    def delete_many(self, models):
        return sum([self.delete_one(model) for model in models])

    def execute(self, queryObj, page_size=500, parent_key=None, limit=None, as_dict=False):
        klass = queryObj.model_class
        collection = self._db[klass._meta.name]
        sort = [(item[1:], pymongo.DESCENDING) if item.startswith('-') else (item, pymongo.ASCENDING) for item in queryObj._order]
        projection = self.build_projection(queryObj)
        limit = limit if (limit and limit > 0) else queryObj._limit
        if queryObj._distinct:
            #distinct returns raw field values, model instances do not apply here
            for data in collection.distinct(queryObj._distinct[0], queryObj.filters()):
                yield data
        else:
            with collection.find(queryObj.filters(), projection=projection) as cursor:
                if sort:
                    cursor = cursor.sort(sort)
                if limit:
                    cursor = cursor.limit(limit)
                for item in cursor:
                    inst = self.make_instance(klass, item)
                    yield inst.dicts() if (inst and as_dict) else inst

    def count(self, queryObj, parent_key=None):
        kwargs = {}
        if queryObj._limit: #a limited select counts up to the limit, like peewee does
            kwargs['limit'] = queryObj._limit
        return self._db[queryObj.model_class._meta.name].count_documents(queryObj.filters(), **kwargs)

    #make Model instance from database data
    def make_instance(self, klass, raw):
        inst = klass()
        fields = inst._meta.fields
        for field_name, value in raw.items():
            if field_name in fields:
                setattr(inst, field_name, fields[field_name].python_value(value))
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
        if key is None:
            raise ValueError('Can not build an ObjectId from None')
        if isinstance(key, bytes):
            key = key.decode('utf-8')
        try:
            return ObjectId(key)
        except Exception as e:
            raise ValueError(f'Invalid ObjectId: {key!r}') from e

    def key_to_id(self, key):
        return str(key)

    #keys: a single key or a list of (key, direction) pairs
    def create_index(self, model, keys, unique=False, **kwargs):
        self._db[model._meta.name].create_index(keys, unique=unique, **kwargs)

    def drop_table(self, model):
        #compatible for class, instance and plain name
        name = model if isinstance(model, str) else model._meta.name
        self._db.drop_collection(name)

    def close(self):
        self.client.close()


class RedisDbClient(NosqlClient):
    bytes_store = True
    urlsafe_alphabet = '0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz'

    def __init__(self, project, dbUrl='redis://127.0.0.1:6379/0', key_sep=':'):
        super().__init__()
        if redis is None: # pragma: no cover
            raise ImportError('redis is required for RedisDbClient')
        self.redis = redis.from_url(dbUrl)
        self.prefix = f'{project}{key_sep}'
        self.key_sep = key_sep
        self.indexes = defaultdict(set)

    @classmethod
    def op_map(cls, op):
        return {Filter.EQ: '==', Filter.NE: '!=', Filter.LT: '<', Filter.GT: '>', Filter.LE: '<=',
            Filter.GE: '>=', Filter.IN: 'in', Filter.NIN: 'not in'}.get(op, op)

    #generate id of a 22 characters string instead of 36 characters UUID
    @classmethod
    def generate_id(cls):
        id_ = uuid.uuid4().int
        digits = []
        while id_: #62 == len(urlsafe_alphabet)
            digits.append(cls.urlsafe_alphabet[int(id_ % 62)])
            id_ //= 62
        return ''.join(digits[::-1]) if digits else '0'

    #id_ - build key for entity, index - build key for index (field name or tuple(name, value))
    def build_key(self, model, *, id_=None, index=None):
        #compatible for class and instance
        name = model._meta.name if isinstance(model, (BaseModel, Model)) else model
        sep = self.key_sep
        if id_ is not None:
            id_ = id_.decode('utf-8') if isinstance(id_, bytes) else id_
            return f'{self.prefix}{name}{sep}{id_}'
        elif isinstance(index, tuple):
            return f'{self.prefix}__index__{sep}{name}{sep}{index[0]}{sep}{index[1]}'
        elif index is not None:
            return f'{self.prefix}__index__{sep}{name}{sep}{index}'
        else:
            raise ValueError('Both id_ and index are None') # pragma: no cover

    @classmethod
    def db_id_name(cls):
        return "id"

    def insert_one(self, klass, data: dict):
        id_ = self.generate_id()
        model = klass(**data)
        data = model.dicts(remove_id=True, db_value=True)
        key = self.build_key(klass, id_=id_)
        self.save_hash(key, data)
        indexes = self.indexes.get(klass._meta.name, None)
        if indexes:
            self.add_index(indexes, klass, data, id_)
        return id_

    #redis can not store None values, absent fields are read back as None
    def save_hash(self, key, data):
        null_fields = [k for k, v in data.items() if v is None]
        data = {k: v for k, v in data.items() if v is not None}
        if data:
            self.redis.hset(key, mapping=data) #hmset is deprecated
        if null_fields:
            self.redis.hdel(key, *null_fields)

    def insert_many(self, klass, datas: list):
        return [self.insert_one(klass, data) for data in datas]

    def update_one(self, model):
        id_ = model.get_id()
        if id_: #update
            data = model.dicts(remove_id=True, db_value=True)
            if data:
                key = self.build_key(model, id_=id_)
                #need to update index?
                index_changed = False
                if self.indexes.get(model._meta.name, []):
                    old_data = self.redis.hgetall(key)
                    if old_data:
                        old_data[self.db_id_name()] = id_
                        index_changed = model.index_changed(self.make_instance(model.__class__, old_data))
                self.save_hash(key, data)
                if index_changed:
                    self.rebuild_index(model.__class__)
                model.clear_dirty(list(data.keys()))
            return model
        else: #insert
            data = model.dicts(remove_id=True)
            model.clear_dirty(list(data.keys()))
            return model.set_id(self.insert_one(model.__class__, data))

    def delete_one(self, model):
        id_ = model.get_id()
        cnt = 0
        if id_:
            cnt = self.redis.delete(self.build_key(model, id_=id_))
            if cnt and self.indexes.get(model._meta.name, None): #delete index if exists
                self.drop_index(model)
        return cnt

    def delete_many(self, models):
        return sum([self.delete_one(model) for model in models])

    def execute(self, queryObj, page_size=500, parent_key=None, limit=None, as_dict=False):
        klass = queryObj.model_class
        _filters = queryObj._filters
        limit = limit if (limit and limit > 0) else queryObj._limit
        if len(_filters) == 1:
            flt = _filters[0]
            if flt.isFilterById(self.db_id_name()):
                inst = self.get_by_id(klass, flt.value)
                if inst: #no match must not yield a None item
                    yield inst.dicts() if as_dict else inst
                return
            elif self.indexes.get(klass._meta.name) and self.isFilterByIndex(klass, flt):
                yield from self.get_by_index(klass, flt, as_dict, limit=limit)
                return

        filters = [flt.clone('utf-8') for flt in _filters]
        fields = {name.encode('utf-8'): inst for name, inst in klass._meta.fields.items()}
        results = []
        key_sep = self.key_sep.encode('utf-8')
        id_name = self.db_id_name().encode('utf-8')
        order = [o.lstrip('-') for o in queryObj._order]
        #All fields have to be some in reverse attribute
        reverse = any(o.startswith('-') for o in queryObj._order)

        cnt = 0
        for key, data in self.iter_data(klass, type_='key_data'):
            data[id_name] = key.rsplit(key_sep, 1)[-1] #set primary key
            if all(self._matches_query(data, flt, fields) for flt in filters):
                results.append(data)
                cnt += 1
                if not order and limit and cnt >= limit:
                    break

        results = [self.make_instance(klass, r) for r in results]
        if order:
            def sort_key(inst):
                #None sorts after all normal values and must not crash the comparison
                vals = []
                for name in order:
                    v = getattr(inst, name, None)
                    vals.append((v is None, v))
                return tuple(vals)
            results.sort(key=sort_key, reverse=reverse)

        for inst in (results[:limit] if limit else results):
            yield inst.dicts() if (inst and as_dict) else inst

    def isFilterByIndex(self, model, flt):
        return (not flt.bit_op and flt.op == Filter.EQ and flt.item in self.indexes.get(model._meta.name, []))

    #type_: key | index | key_data
    def iter_data(self, klass, type_='key'):
        cursor = 0
        id_= '*' if type_.startswith('key') else None
        index = '*' if type_ == 'index' else None
        key_only = bool(type_ != 'key_data')
        pattern = self.build_key(klass, id_=id_, index=index)
        while True:
            cursor, keys = self.redis.scan(cursor, match=pattern, count=500)
            for key in keys:
                yield key if key_only else (key, self.redis.hgetall(key))
            if cursor == 0:
                break

    def get_by_id(self, klass, id_):
        data = self.redis.hgetall(self.build_key(klass, id_=id_))
        if data:
            data[self.db_id_name()] = id_
            return self.make_instance(klass, data)
        else:
            return None

    def get_by_index(self, klass, flt, as_dict=False, limit=0):
        key = self.build_key(klass, index=(flt.item, flt.value))
        cnt = 0
        for id_ in self.redis.smembers(key):
            if limit and (cnt >= limit):
                return
            inst = self.get_by_id(klass, id_)
            if inst: #skip stale index entries
                cnt += 1
                yield inst.dicts() if as_dict else inst

    def _matches_query(self, data: dict, flt: Filter, fields: dict):
        if not flt.bit_op:
            item = flt.item
            if item not in fields:
                return False

            op = flt.op
            value = flt.value
            dbValue = fields[item].python_value(data.get(item, None))
            if dbValue is None and op in (Filter.LT, Filter.GT, Filter.LE, Filter.GE):
                return False #None is not comparable, matches no ordering condition

            return (((op == Filter.EQ) and (dbValue == value)) or
                ((op == Filter.NE) and (dbValue != value)) or
                ((op == Filter.LT) and (dbValue < value)) or
                ((op == Filter.GT) and (dbValue > value)) or
                ((op == Filter.LE) and (dbValue <= value)) or
                ((op == Filter.GE) and (dbValue >= value)) or
                ((op == Filter.IN) and (dbValue in value)) or
                ((op == Filter.NIN) and (dbValue not in value)))
        elif flt.bit_op == Filter.AND:
            return all(self._matches_query(data, c, fields) for c in flt.children)
        elif flt.bit_op == Filter.OR:
            return any(self._matches_query(data, c, fields) for c in flt.children)
        elif flt.bit_op == Filter.NOR:
            return not any(self._matches_query(data, c, fields) for c in flt.children)
        else:
            raise ValueError(f"Unsupported bit operator: {flt.bit_op}") # pragma: no cover

    def count(self, queryObj, parent_key=None):
        return len(list(self.execute(queryObj)))

    #make Model instance from database data
    def make_instance(self, klass, raw):
        inst = klass()
        fields = klass._meta.fields
        for name, value in raw.items():
            name = name.decode('utf-8') if isinstance(name, bytes) else name
            setattr(inst, name, fields[name].python_value(value) if name in fields else value)

        inst.clear_dirty(list(fields.keys()))
        return inst.set_id(str(getattr(inst, self.db_id_name())))

    def ensure_key(self, key, kind=None):
        if isinstance(key, Model):
            key = key.get_id()
        if key is None:
            raise ValueError('Can not build a key from None')
        if isinstance(key, bytes):
            key = key.decode('utf-8')
        return str(key)

    #keys: a single field name, a list of field names, or a list of (name, direction) pairs
    def create_index(self, model, keys, unique=False, **kwargs):
        if isinstance(keys, str):
            keys = [keys]
        else:
            keys = [key[0] if isinstance(key, (list, tuple)) else key for key in keys]
        for key in keys:
            self.indexes[model._meta.name].add(key)

    #data is already db_value format
    def add_index(self, indexes, klass, data, id_):
        for field_name in indexes:
            value = data.get(field_name, None)
            if value is not None: #index is id set
                value = value.decode('utf-8') if isinstance(value, bytes) else str(value)
                index = self.build_key(klass, index=(field_name, value))
                self.redis.sadd(index, id_)

    def rebuild_index(self, klass):
        self.drop_index(klass)
        indexes = self.indexes.get(klass._meta.name, [])
        indexes = [(idx, self.build_key(klass, index=(idx, ''))) for idx in indexes]
        if not indexes:
            return #This model have no index required  # pragma: no cover

        for key, data in self.iter_data(klass, type_='key_data'):
            id_ = key.rsplit(self.key_sep.encode('utf-8'), 1)[-1]
            for field_name, index in indexes:
                value = data.get(field_name.encode('utf-8'), None)
                if value is not None: #index is id set
                    self.redis.sadd(f'{index}{value.decode("utf-8")}', id_)

    #drop the whole index of table if model is a class, otherwise drop a record only
    def drop_index(self, model):
        if isinstance(model, Model): #instance, drop one record only
            id_ = model.get_id()
            for field_name in self.indexes.get(model._meta.name, []):
                value = getattr(model, field_name, None)
                if value is not None:
                    value = model._meta.fields[field_name].db_value(value).decode('utf-8')
                    index = self.build_key(model, index=(field_name, value))
                    self.redis.srem(index, id_)
        else: #drop the whole index of table
            for key in self.iter_data(model, type_='index'):
                self.redis.delete(key)

    def drop_table(self, model):
        assert(isinstance(model, BaseModel)) #is a class
        self.drop_index(model)
        for key in self.iter_data(model, type_='key'):
            self.redis.delete(key)

#use pickle instead of json for pickle can save bytes directly
class PickleDbClient(RedisDbClient):
    #pickle://dbName?bakBeforeWrite=yes
    def __init__(self, dbName, bakBeforeWrite=True):
        NosqlClient.__init__(self)
        if '://' in dbName:
            ret = urlparse(dbName)
            dbName = ret.netloc or ret.path
            if ret.netloc and re.match(r'^[A-Za-z]:$', ret.netloc): #windows drive inside the netloc
                dbName = ret.netloc + (ret.path or '/')
            _plat = sys.platform.lower()
            if ('win32' in _plat or 'win64' in _plat): #windows平台
                dbName = dbName.lstrip('/')
            elif dbName.startswith('//'):
                dbName = dbName[1:]

            qs = parse_qs(ret.query)
            if 'bakBeforeWrite' in qs:
                bakBeforeWrite = qs['bakBeforeWrite'][0].lower() in ('yes', 'true', '1')

        if dbName != ':memory:' and not os.path.isabs(dbName):
            self.dbName = os.path.join(os.path.dirname(__file__), dbName)
        else:
            self.dbName = dbName
        self.bakDbName = self.dbName + '.bak'
        self.bakBeforeWrite = bakBeforeWrite
        self.prefix = ''
        self.key_sep = ':'
        self.indexes = defaultdict(set)
        self.load_db()

    def load_db(self):
        if self.dbName == ':memory:':
            self.pickleDb = {}
            return

        self.pickleDb = None
        if os.path.exists(self.dbName):
            try:
                with open(self.dbName, 'rb') as f:
                    self.pickleDb = pickle.loads(f.read())
            except Exception:
                pass
        if os.path.exists(self.bakDbName):
            if self.bakBeforeWrite and not isinstance(self.pickleDb, dict):
                try:
                    with open(self.bakDbName, 'rb') as f:
                        self.pickleDb = pickle.loads(f.read())
                    if isinstance(self.pickleDb, dict):
                        shutil.copyfile(self.bakDbName, self.dbName)
                except Exception:
                    pass
            elif not self.bakBeforeWrite:
                try:
                    os.remove(self.bakDbName)
                except Exception:
                    pass

        if not isinstance(self.pickleDb, dict):
            self.pickleDb = {}

    def save_db(self):
        if self.dbName == ':memory:':
            return

        if self.bakBeforeWrite and os.path.exists(self.dbName):
            shutil.copyfile(self.dbName, self.bakDbName)
        with open(self.dbName, 'wb') as f:
            f.write(pickle.dumps(self.pickleDb))

    #id_ - build key for entity, index - build key for index (field name)
    def build_key(self, model, *, id_=None, index=None):
        return super().build_key(model, id_=id_, index=index).encode('utf-8')

    def insert_one(self, klass, data: dict):
        id_ = self.generate_id()
        data = klass(**data).dicts(remove_id=True, db_value=True)
        data = {key.encode('utf-8'): value for key, value in data.items()}
        self.pickleDb[self.build_key(klass, id_=id_)] = data
        self.save_db()
        return id_

    def update_one(self, model):
        id_ = model.get_id()
        if id_: #update
            data = model.dicts(remove_id=True, db_value=True)
            if data:
                model.clear_dirty(list(data.keys()))
                data = {key.encode('utf-8'): value for key, value in data.items()}
                self.pickleDb[self.build_key(model, id_=id_)] = data
                self.save_db()
            return model
        else: #insert
            data = model.dicts(remove_id=True)
            model.clear_dirty(list(data.keys()))
            return model.set_id(self.insert_one(model.__class__, data))

    def delete_one(self, model):
        id_ = model.get_id()
        if id_ and self.pickleDb.pop(self.build_key(model, id_=id_), None) is not None:
            self.save_db()
            return 1
        else:
            return 0

    def iter_data(self, klass, type_='key'):
        id_= '' if type_.startswith('key') else None
        index = '' if type_ == 'index' else None
        key_only = bool(type_ != 'key_data')
        pattern = self.build_key(klass, id_=id_, index=index)
        for key in [x for x in self.pickleDb if x.startswith(pattern)]:
            yield key if key_only else (key, self.pickleDb[key])

    def get_by_id(self, klass, id_):
        data = self.pickleDb.get(self.build_key(klass, id_=id_), None)
        if data:
            data = dict(data) #do not touch the stored record
            data[self.db_id_name()] = id_
            return self.make_instance(klass, data)
        else:
            return None

    #keys: a single key or a list of (key, direction) pairs
    def create_index(self, model, keys, unique=False, **kwargs):
        pass

    def drop_table(self, model):
        pattern = self.build_key(model, id_='')
        for key in [x for x in self.pickleDb if x.startswith(pattern)]:
            del self.pickleDb[key]
        self.save_db()
