#!/usr/bin/env python3
# -*- coding:utf-8 -*-
#An ORM/ODM for Google Cloud Datastore/MongoDB/redis, featuring a compatible interface with Peewee.
#Author: cdhigh <http://github.com/cdhigh>
#Repository: <https://github.com/cdhigh/weedata>
#Pypi package: <https://pypi.org/project/weedata>
import os, sys, uuid, pickle, shutil
from itertools import chain
from operator import attrgetter
from collections import defaultdict
from urllib.parse import urlparse, parse_qs

try:
    from google.cloud import datastore
    from google.cloud.datastore import Key
    from google.cloud.datastore import query as qr
except ImportError:  # pragma: no cover
    datastore = None

try:
    import pymongo
    from bson.objectid import ObjectId
except ImportError:  # pragma: no cover
    pymongo = None

try:
    import redis
except ImportError:  # pragma: no cover
    redis = None

from .model import Model, BaseModel
from .fields import Filter

#if os.environ.get('WEEDATA_TEST_BACKEND') == 'datastore':
#    from fake_datastore import *
#    print('Alert: using fake datastore stub!!!')

class NosqlClient(object):
    bytes_store = False #For redis, it's True

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
        entity = self.create_entity(data, kind=klass._meta.name)
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
                entities.append(self.create_entity(data, kind=kind))
            self.client.put_multi(entities)
            ids.extend([e.key.to_legacy_urlsafe().decode() for e in entities])
        return ids

    def update_one(self, model):
        data = model.dicts(remove_id=True, db_value=True, only_dirty=bool(model._key))
        entity = self.create_entity(data, kind=model._meta.name, key=model._key)
        if data:
            self.client.put(entity)
            model.clear_dirty(list(data.keys()))
        return model.set_id(entity.key.to_legacy_urlsafe().decode())
        
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

    def execute(self, queryObj, page_size=500, parent_key=None, limit=None):
        klass = queryObj.model_class
        kind = klass._meta.name
        query = self.client.query(kind=kind, ancestor=parent_key)
        self.apply_query_condition(queryObj, query)

        limit = limit if limit else queryObj._limit
        batch_size = min(page_size, limit) if limit else page_size
        yield from self.query_fetch(query, batch_size, limit, klass)

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
        kind = queryObj.model_class._meta.name
        query = self.client.query(kind=kind, ancestor=parent_key)
        self.apply_query_condition(queryObj, query)
        query_func = getattr(self.client.aggregation_query(query=query), func)
        query = query_func(arg) if arg else query_func()
        with query.fetch() as result:
            return next(result).value if result else 0

    #generate model instance(klass!=None) or entity(klass=None)
    def query_fetch(self, query, batch_size=500, limit=0, klass=None):
        cursor = None
        count = 0
        while True:
            last_entity = None
            result = query.fetch(start_cursor=cursor, limit=batch_size)

            for entity in result:
                last_entity = self.make_instance(klass, entity) if klass else entity
                yield last_entity
                count += 1
            cursor = result.next_page_token
            if not cursor or (last_entity is None) or (limit and (count >= limit)):
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

            converted = []
            for op in query_dict.keys():
                if op in (Filter.OR, Filter.AND): #recrusive
                    flts = list(chain.from_iterable([to_ds_query(subquery) for subquery in query_dict[op]]))
                    converted.append(qr.Or(flts) if op == Filter.OR else qr.And(flts))
                elif op == Filter.NOR:
                    raise ValueError('datastore does not support nor query')
                else:
                    for field, condition in query_dict.items():
                        if isinstance(condition, dict):
                            for op2, value in condition.items():
                                converted.append(qr.PropertyFilter(field, op2, value))
                        else:
                            converted.append(qr.PropertyFilter(field, '=', condition))
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

    def drop_table(self, model, parent_key=None):
        #compatible for class and instance
        kind = model._meta.name if isinstance(model, (BaseModel, Model)) else model
        query = self.client.query(kind=kind, ancestor=parent_key)
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
    def __init__(self, project, dbUrl='mongodb://127.0.0.1:27017/'):
        self.project = project
        self.dbUrl = dbUrl
        self.client = pymongo.MongoClient(self.dbUrl)
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
        datas = [klass(**data).dicts(remove_id=True, db_value=True) for data in datas]
        ids = self._db[klass._meta.name].insert_many(datas).inserted_ids
        return [str(id_) for id_ in ids]
        
    def update_one(self, model):
        id_ = model.get_id()
        if id_: #update
            data = model.dicts(remove_id=True, db_value=True, only_dirty=True)
            if data:
                self._db[model._meta.name].update({'_id': ObjectId(id_)}, {'$set': data})
                model.clear_dirty(list(data.keys()))
            return model
        else: #insert
            data = model.dicts(remove_id=True)
            model.clear_dirty(list(data.keys()))
            return model.set_id(self.insert_one(model.__class__, data))
     
    def delete_one(self, model):
        if model._id:
            return self._db[model._meta.name].delete_one({'_id': model._id}).deleted_count
        else:
            return 0

    def delete_many(self, models):
        return sum([self.delete_one(model) for model in models])
        
    def execute(self, queryObj, page_size=500, parent_key=None, limit=None):
        klass = queryObj.model_class
        collection = self._db[klass._meta.name]
        sort = [(item[1:], pymongo.DESCENDING) if item.startswith('-') else (item, pymongo.ASCENDING) for item in queryObj._order]
        projection = self.build_projection(queryObj)
        limit = limit if limit else queryObj._limit
        if queryObj._distinct:
            for data in collection.distinct(queryObj._distinct[0], queryObj.filters()):
                yield data
        else:
            with collection.find(queryObj.filters(), projection=projection) as cursor:
                if sort:
                    cursor = cursor.sort(sort)
                if limit:
                    cursor = cursor.limit(limit)
                for item in cursor:
                    yield self.make_instance(klass, item)

    def count(self, queryObj, parent_key=None):
        return self._db[queryObj.model_class._meta.name].count_documents(queryObj.filters())

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
        else:
            return ObjectId(key)

    #keys: a single key or a list of (key, direction) pairs
    def create_index(self, model, keys, unique=False, **kwargs):
        self._db[model._meta.name].create_index(keys, unique=unique, **kwargs)

    def drop_table(self, model):
        model = model._meta.name if issubclass(model, Model) else model
        self._db.drop_collection(model)

    def close(self):
        self.client.close()


class RedisDbClient(NosqlClient):
    bytes_store = True
    urlsafe_alphabet = '0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz'

    def __init__(self, project, dbUrl='redis://127.0.0.1:6379/0', key_sep=':'):
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
        self.redis.hmset(self.build_key(klass, id_=id_), data)
        indexes = self.indexes.get(klass._meta.name, None)
        if indexes:
            self.add_index(indexes, klass, data, id_)
        return id_

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
                self.redis.hmset(key, data)
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
        
    def execute(self, queryObj, page_size=500, parent_key=None, limit=None):
        klass = queryObj.model_class
        _filters = queryObj._filters
        if len(_filters) == 1:
            flt = _filters[0]
            if flt.isFilterById(self.db_id_name()):
                yield self.get_by_id(klass, flt.value)
                return
            elif self.indexes.get(klass._meta.name) and self.isFilterByIndex(klass, flt):
                yield from self.get_by_index(klass, flt)
                return
            
        filters = [flt.clone('utf-8') for flt in _filters]
        fields = {name.encode('utf-8'): inst for name, inst in klass._meta.fields.items()}
        results = []
        key_sep = self.key_sep.encode('utf-8')
        id_name = self.db_id_name().encode('utf-8')
        limit = limit or queryObj._limit
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
            results.sort(key=attrgetter(*order), reverse=reverse)

        yield from (results[:limit] if limit else results)

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

    def get_by_index(self, klass, flt):
        key = self.build_key(klass, index=(flt.item, flt.value))
        for id_ in self.redis.smembers(key):
            yield self.get_by_id(klass, id_)

    def _matches_query(self, data: dict, flt: Filter, fields: dict):
        if not flt.bit_op:
            item = flt.item
            if item not in fields:
                return False

            op = flt.op
            value = flt.value
            dbValue = fields[item].python_value(data.get(item, None))

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
        return key.get_id() if isinstance(key, Model) else str(key)
    
    #keys: a single key or a list of (key, direction) pairs
    def create_index(self, model, keys, unique=False, **kwargs):
        keys = [key[0] for key in keys] if isinstance(keys, list) else [keys]
        for key in keys:
            self.indexes[model._meta.name].add(key)

    #data is already db_value format
    def add_index(self, indexes, klass, data, id_):
        for field_name in indexes:
            value = data.get(field_name, None)
            if value is not None: #index is id set
                value = klass._meta.fields[field_name].db_value(value).decode('utf-8')
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
        if '://' in dbName:
            ret = urlparse(dbName)
            dbName = ret.netloc or ret.path
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
            except:
                pass
        if os.path.exists(self.bakDbName):
            if self.bakBeforeWrite and not isinstance(self.pickleDb, dict):
                try:
                    with open(self.bakDbName, 'rb') as f:
                        self.pickleDb = pickle.loads(f.read())
                    if isinstance(self.pickleDb, dict):
                        shutil.copyfile(self.bakDbName, self.dbName)
                except:
                    pass
            elif not self.bakBeforeWrite:
                try:
                    os.remove(self.bakDbName)
                except:
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

class fakeTransation:
    def __enter__(self):
        return self
    def __exit__(self, exc_type, exc_val, exc_tb):
        pass