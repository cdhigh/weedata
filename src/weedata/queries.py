#!/usr/bin/env python3
# -*- coding:utf-8 -*-
#An ORM/ODM for Google Cloud Datastore/MongoDB/redis, featuring a compatible interface with Peewee.
#Author: cdhigh <http://github.com/cdhigh>
#Repository: <https://github.com/cdhigh/weedata>
#Pypi package: <https://pypi.org/project/weedata>
import re
from .fields import Field, PrimaryKeyField, UpdateExpr, Filter

class QueryBuilder:
    def __init__(self, model_class, *args):
        self.model_class = model_class
        _meta = model_class._meta
        self.kind = _meta.name
        self.client = _meta.client
        if self.client is None:
            raise ValueError(f'Model "{self.kind}" is not bound to a database client')
        self._filters = []
        self._projection = []
        for field in args:
            if isinstance(field, PrimaryKeyField):
                self._projection.append(self.client.db_id_name())
            elif isinstance(field, Field):
                self._projection.append(field.name)
            elif field:
                self._projection.append(field)
        self._order = []
        self._distinct = []
        self._limit = 0

    def where(self, *filters):
        self._filters.extend(filters)
        return self

    def filter_by_key(self, key):
        if key is None:
            #a None key would silently drop the filter otherwise, returning arbitrary records
            raise ValueError('Can not filter by a None key (get_by_id(None) returns None)')
        key = self.client.ensure_key(key, self.kind)
        self._filters.append(Filter(self.client.db_id_name(), Filter.EQ, key))
        return self

    def filter_by_id(self, id_):
        return self.filter_by_key(id_)

    def order_by(self, *fields):
        self._order.extend([(field.name if isinstance(field, Field) else field) for field in fields])
        return self

    def limit(self, limit: int):
        try:
            limit = int(limit)
        except (TypeError, ValueError):
            raise ValueError(f'limit must be an integer, got {limit!r}') from None
        self._limit = max(0, limit) #a negative limit means no limit, same as zero
        return self

    def distinct(self, field):
        distinct_field = field.name if isinstance(field, Field) else field
        self._distinct = [distinct_field]
        return self

    #the parameter limit will override the property of query object
    def execute(self, page_size=500, parent_key=None, limit=None):
        return self.client.execute(self, page_size=page_size, parent_key=parent_key, limit=limit)

    def dicts(self, page_size=500, parent_key=None, limit=None):
        return self.client.execute(self, page_size=page_size, parent_key=parent_key,
            limit=limit, as_dict=True)

    def get(self):
        try:
            return next(self.execute(page_size=1, limit=1))
        except StopIteration:
            return None

    first = get

    def count(self):
        return self.client.count(self)

    #return a nested dict {item: {op: [value1, value2]}, item: {op: value}}
    #ready for mongodb query
    def filters(self):
        def convert_filters(flts):
            if not flts:
                return {}
            merged = {}
            or_groups = []
            for f_item in flts:
                if f_item.bit_op == Filter.OR:
                    or_groups.append([convert_filters([f]) for f in f_item.children])
                elif f_item.bit_op == Filter.NOR:
                    merged.setdefault(f_item.bit_op, []).append(convert_filters(f_item.children))
                elif f_item.bit_op:
                    #'$and' is associative, all entries of the same operator are kept
                    merged.setdefault(f_item.bit_op, []).extend(
                        [convert_filters([f]) for f in f_item.children])
                else:
                    item, value = f_item.item, f_item.value
                    op = self.client.op_map(f_item.op)
                    eq_op = self.client.op_map(Filter.EQ)
                    ne_op = self.client.op_map(Filter.NE)
                    in_op = self.client.op_map(Filter.IN)
                    nin_op = self.client.op_map(Filter.NIN)
                    merged.setdefault(item, {})
                    if op == ne_op: #convert multiple "!=" to "not in"
                        if nin_op in merged[item]:
                            merged[item][nin_op].append(value)
                        elif ne_op in merged[item]:
                            merged[item][nin_op] = [merged[item].pop(ne_op), value]
                        else:
                            merged[item][op] = value
                    elif op == eq_op: #convert multiple "==" to "in"
                        if in_op in merged[item]:
                            merged[item][in_op].append(value)
                        elif eq_op in merged[item]:
                            merged[item][in_op] = [merged[item].pop(eq_op), value]
                        else:
                            merged[item][op] = value
                    else:
                        merged[item][op] = value
            if len(or_groups) == 1:
                merged[Filter.OR] = or_groups[0]
            elif or_groups:
                #several top-level OR groups are ANDed with each other and with the rest
                merged.setdefault(Filter.AND, []).extend({Filter.OR: g} for g in or_groups)
            return merged
        return convert_filters(self._filters)

    def __iter__(self):
        return iter(self.execute())

class DeleteQueryBuilder(QueryBuilder):
    def execute(self):
        #consume the whole result first, the cascade deletes below may hit the same kind
        models = list(super().execute())
        for m in models:
            #delete on cascade
            for field in [f for f in m._meta.backref.values() if f.on_delete]:
                field.model.delete().where(field == m).execute()

        return self.client.delete_many(models)

class InsertQueryBuilder:
    def __init__(self, model_class, to_insert):
        self.model_class = model_class
        self.client = model_class._meta.client
        if self.client is None:
            raise ValueError(f'Model "{model_class._meta.name}" is not bound to a database client')
        self.to_insert = to_insert

    def execute(self):
        if isinstance(self.to_insert, dict):
            return self.client.insert_one(self.model_class, self.to_insert)
        if isinstance(self.to_insert, (list, tuple)) or (
                hasattr(self.to_insert, '__iter__') and not isinstance(self.to_insert, (str, bytes))):
            return self.client.insert_many(self.model_class, list(self.to_insert))
        return None

    def __iter__(self):
        if not hasattr(self, '_result'):
            #execute once only, iterating the builder twice must not duplicate inserts
            self._result = self.execute()
        ids = self._result
        return iter(ids if isinstance(ids, list) else [ids])

class ReplaceQueryBuilder:
    def __init__(self, model_class, to_replace: dict):
        self.model_class = model_class
        self.client = model_class._meta.client
        if self.client is None:
            raise ValueError(f'Model "{model_class._meta.name}" is not bound to a database client')
        self.to_replace = to_replace

    def execute(self):
        model = self.model_class
        fields = model._meta.fields
        data = self.to_replace
        unknown = [name for name in data if name not in fields]
        if unknown:
            raise ValueError(f'Model "{model._meta.name}" has no field(s): {unknown}')

        unique_names = [name for name in data if fields[name].unique]
        if not unique_names:
            raise ValueError('Replace query requires at least one unique field')

        name = unique_names[0]
        dbItem = model.get_or_none(getattr(model, name) == data[name])
        if dbItem:
            for key, value in data.items():
                setattr(dbItem, key, value)
        else:
            dbItem = model(**data)
        dbItem.save()
        return dbItem.get_id()

    def __iter__(self):
        if not hasattr(self, '_result'):
            self._result = self.execute()
        ids = self._result
        return iter(ids if isinstance(ids, list) else [ids])

class _FieldProxy:
    #restricted namespace for safe_eval: only field values of one instance are reachable
    def __init__(self, instance, fields):
        object.__setattr__(self, 'instance', instance)
        object.__setattr__(self, 'fields', fields)

    def __getattr__(self, name):
        if name in object.__getattribute__(self, 'fields'):
            return getattr(object.__getattribute__(self, 'instance'), name)
        raise NameError(f"'{name}' is not a model field")

class UpdateQueryBuilder(QueryBuilder):
    banned_names = ('eval', 'compile', 'exec', 'getattr', 'hasattr', 'setattr', 'delattr',
        'classmethod', 'globals', 'help', 'input', 'isinstance', 'issubclass', 'locals',
        'open', 'print', 'property', 'staticmethod', 'vars', 'os', '__import__')

    def __init__(self, model_class, to_update):
        super().__init__(model_class)
        unknown = [name for name in to_update if name not in model_class._meta.fields]
        if unknown:
            raise ValueError(f'Model "{model_class._meta.name}" has no field(s): {unknown}')
        self._update = to_update #is a dict

    def execute(self):
        if not self._update:
            return 0
        cnt = 0
        for e in super().execute():
            fields = e._meta.fields
            proxy = _FieldProxy(e, fields)
            for field_name, value in self._update.items():
                if isinstance(value, UpdateExpr):
                    value = self.safe_eval(str(value), {'e': proxy})
                setattr(e, field_name, value)
            self.client.update_one(e)
            cnt += 1
        return cnt

    @staticmethod
    def safe_eval(txt, local_dict):
        code = compile(txt, '<user input>', 'eval')
        proxy = local_dict.get('e', None)
        field_names = set(getattr(proxy, 'fields', {}) or {}) if proxy is not None else set()
        for name in code.co_names:
            if name == 'e' or name in field_names:
                continue #legitimate attribute access on the instance proxy
            if re.search(r'^__\S*__$', name):
                raise NameError(f'{name} not allowed : dunder attributes not allowed')
            if name in UpdateQueryBuilder.banned_names:
                raise NameError(f'{name} not allowed : arbitrary code execution not allowed')
        #no builtins and only the field proxy are visible inside the expression
        return eval(code, {'__builtins__': {}}, local_dict)
