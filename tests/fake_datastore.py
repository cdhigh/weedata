#!/usr/bin/env python3
# -*- coding:utf-8 -*-
#google cloud datastore simplest emulator

import json, datetime, os, random, pickle
thisDir = os.path.dirname(os.path.abspath(__file__))
dbName = os.path.normpath(os.path.join(thisDir, 'fake_datastore.pkl'))
jsonDbName = os.path.normpath(os.path.join(thisDir, 'fake_datastore.json')) #for reading

def SaveDbJson():
    with open(dbName, 'wb') as f:
        f.write(pickle.dumps(dbJson))
    #with open(jsonDbName, 'w', encoding='utf-8') as f:
    #    f.write(json.dumps(dbJson, indent=2, default=str))

class google:
    pass

class DatastoreDatabase:
    def __init__(self, project):
        self.project = project
    def __enter__(self, *args, **kwargs):
        return self
    def __exit__(self, *args, **kwargs):
        pass

class datastore:
    entities = {}

    @property
    def client(self):
        return Client()

    @classmethod
    def Entity(cls, key):
        class _Entity:
            def __init__(self, key):
                self.key = key
                self.data = None
            def update(self, data):
                self.data = data
            def __str__(self):
                return f'key={str(self.key)}, data={self.data}'
        
        if key not in cls.entities:
            cls.entities[key] = _Entity(key)
        return cls.entities[key]

    class Client:
        cache_keys = []
        def __init__(self, project, namespace, credentials, _http):
            self.project = project
            self.namespace = namespace
            self.credentials = credentials
            self._http = _http
        def key(self, name, identifier=None, parent=None):
            return Key(name, identifier, parent)
        def put(self, entity):
            key = str(entity.key)
            if key in dbJson:
                dbJson[key].update(entity.data)
            else:
                dbJson[key] = entity.data
            SaveDbJson()
        def put_multi(self, entities):
            for e in entities:
                self.put(e)
            SaveDbJson()
        def delete(self, key):
            key = str(key)
            if key in dbJson:
                del dbJson[key]
            SaveDbJson()
        def delete_multi(self, keys):
            for key in keys:
                self.delete(key)
        def query(self, kind, ancestor=None):
            return DBQuery(kind)
        def aggregation_query(self, query):
            return AggreQueryBuilder(query)

        def transaction(self, **args):
            class Transaction:
                def __enter__(self, *args, **kwargs):
                    return self
                def __exit__(self, *args, **kwargs):
                    pass
            return Transaction()
            
        def close(self):
            return

class Key:
    _id_sn = 0
    def __init__(self, name, identifier=None, parent=None):
        self.name = name
        self.identifier = int(identifier or self.next_key_id())
        self.parent = parent
    
    @classmethod
    def next_key_id(cls):
        cls._id_sn += 1
        return cls._id_sn
        
    def to_legacy_urlsafe(self):
        return str(self).encode()

    def __str__(self):
        return f'{self.name}:{self.identifier:06d}:KEY'

    def __eq__(self, other):
        return ((other.__class__ == self.__class__) and (other.name == self.name) and 
            (other.identifier == self.identifier) and (other.parent == self.parent))

    def __hash__(self):
        return hash((self.name, self.identifier, self.parent))

    @classmethod
    def from_legacy_urlsafe(cls, key):
        if isinstance(key, str):
            n, i, k = key.split(':')
            return Key(n, i)
        else:
            return key

    def __getstate__(self): #pickling
        return (self.name, self.identifier, self.parent)
    def __setstate__(self, d): #unpickling
        self.name, self.identifier, self.parent = d

class DBQuery:
    def __init__(self, kind, parent=None):
        self.kind = kind
        self.filters = []
        self.projection = []
        self.order = []
        self.distinct_on = None
    def add_filter(self, filter):
        self.filters.append(filter)
    def fetch(self, start_cursor=None, limit=None):
        results = []
        cnt = 0
        for key, data in dbJson.items():
            n, i, k = key.split(':')
            if n != self.kind: #key第一段是kind
                continue
            for ft in self.filters:
                if not self._entity_matches_query(key, data, ft):
                    break
            else:
                if self.projection:
                    for k in data:
                        if k not in self.projection:
                            data[k] = None
                results.append((Key.from_legacy_urlsafe(key), data))

        order = []
        reverse = False
        if self.order:
            for o in self.order: #All fields have to be some in reverse attribute
                if o.startswith('-'):
                    reverse = True
                order.append(o.lstrip('-'))
            if order[0] == 'id':
                results.sort(key=lambda x: x[0].identifier, reverse=reverse)
            else:
                results.sort(key=lambda x: x[1].get(*order), reverse=reverse)

        return QueryResult(results[:limit] if limit else results)

    def _entity_matches_query(self, key, entity, flt):
        if isinstance(flt, qr.PropertyFilter):
            item = flt.property_name
            op = flt.operator
            value = flt.value
            op = {'=': '==', 'IN': 'in', 'NOT_IN': 'not in'}.get(op, op)
            if isinstance(value, str):
                value = f'"{value}"'
            elif isinstance(value, datetime.datetime):
                d = value.strftime("%Y-%m-%d %H:%M:%S")
                value = f'datetime.datetime.strptime("{d}", "%Y-%m-%d %H:%M:%S")'
            
            if item == '__key__':
                expr = f'key {op} "{value}"'
                return eval(expr)
            else:
                expr = f'entity.get("{item}", None) {op} {value}'
                return eval(expr)            
        elif isinstance(flt, qr.CompositeFilter):
            filters = flt.filters
            if flt.op == qr.CompositeFilter.AND:
                for flt1 in filters:
                    if not self._entity_matches_query(key, entity, flt1):
                        return False
                return True
            elif flt.op == qr.CompositeFilter.OR:
                for flt1 in filters:
                    if self._entity_matches_query(key, entity, flt1):
                        return True
                return False
            else:
                raise ValueError(f"Unsupported composite operator: {query.operator}")
        
        else:
            raise ValueError(f"Unsupported query type: {type(query)}")

class AggreQueryResult:
    def __init__(self, value):
        self.value = value
        self.iterated = False
    def __iter__(self):
        return self
    def __next__(self):
        if not self.iterated:
            self.iterated = True
            return self
        else:
            raise StopIteration
    def __enter__(self, *args, **kwargs):
        return self
    def __exit__(self, *args, **kwargs):
        pass

class AggreQuery:
    def __init__(self, query, type_, field=None):
        self.query = query
        self.type_ = type_
        self.field = field
    def fetch(self):
        results = self.query.fetch()
        if self.type_ == 'count':
            value = len(list(results))
        elif self.type_ == 'sum':
            value = sum([r[1].get(field, 0) for r in results])
        else:
            data = [r[1].get(field, 0) for r in results]
            value = sum(data) / len(data) if data else 0
        return AggreQueryResult(value)

class AggreQueryBuilder:
    def __init__(self, query):
        self.query = query
    def count(self):
        return AggreQuery(self.query, 'count')
    def sum(self, field):
        return AggreQuery(self.query, 'sum', field)
    def avg(self, field):
        return AggreQuery(self.query, 'avg', field)

class QueryResult:
    def __init__(self, results):
        self.results = results
        self.current_pos = 0
    def __iter__(self):
        for key, data in self.results:
            d = DotDict(data)
            d.key = key
            yield d
    @property
    def next_page_token(self):
        return None

class DotDict(dict):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.key = None

    def __getattr__(self, key):
        try:
            return self[key]
        except:
            return None

    def __str__(self):
        return f'{self.key}: {self.items()}'


class qr:
    class PropertyFilter:
        def __init__(self, property_name, operator, value):
            self.property_name = property_name
            self.operator = operator
            self.value = value
        def __str__(self):
            return f'{self.property_name} {self.operator} {self.value}'

    class CompositeFilter:
        AND = 'AND'
        OR = 'OR'
        def __init__(self, logical_op, filters):
            self.op = logical_op
            self.filters = filters

    class Or(CompositeFilter):
        def __init__(self, filters):
            super().__init__(qr.CompositeFilter.OR, filters)
        def __str__(self):
            s = ['OR:']
            for f in self.filters:
                s.append('  [ {} ]'.format(str(f)))
            return '\n'.join(s)

    class And(CompositeFilter):
        def __init__(self, filters):
            super().__init__(qr.CompositeFilter.AND, filters)
        def __str__(self):
            s = ['AND:']
            for f in self.filters:
                s.append('  [ {} ]'.format(str(f)))
            return '\n'.join(s)

if os.path.exists(dbName):
    with open(dbName, 'rb') as f:
        dbJson = pickle.loads(f.read())

    ids = [int(item.split(':')[1]) for item in dbJson.keys()]
    max_id = max(ids) if ids else 0
    Key._id_sn = max_id + 1
else:
    dbJson = {}
