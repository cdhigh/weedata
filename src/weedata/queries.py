#!/usr/bin/env python3
# -*- coding:utf-8 -*-
#an ORM/ODM for Google Cloud Datastore/MongoDB, featuring a compatible interface with Peewee.
#Author: cdhigh <http://github.com/cdhigh>
#Repository: <https://github.com/cdhigh/weedata>
import re
from collections import defaultdict
from .fields import Field, PrimaryKeyField, arith_op, UpdateExpr, Filter

class QueryBuilder:
    def __init__(self, model_class, *args):
        self.model_class = model_class
        _meta = model_class._meta
        self.kind = _meta.name
        self.client = _meta.client
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
        if key:
            key = self.client.ensure_key(key, self.kind)
            self._filters.append(Filter(self.client.db_id_name(), "$eq", key))
        return self

    def filter_by_id(self, id_):
        return self.filter_by_key(id_)

    def order_by(self, *fields):
        self._order.extend([(field.name if isinstance(field, Field) else field) for field in fields])
        return self

    def limit(self, limit: int):
        self._limit = limit
        return self

    def distinct_on(self, field):
        distinct_field = field.name if isinstance(field, Field) else field
        self._distinct = [distinct_field]
        return self

    def execute(self, page_size=500, parent_key=None):
        return self.client.execute(self, page_size=page_size, parent_key=parent_key)
        
    def first(self):
        result = None
        try:
            result = next(self.execute(page_size=1))
        except TypeError:
            pass
        except StopIteration:
            pass
        return result

    def get(self):
        return self.first()

    def count(self):
        return self.client.count(self)

    #return a nested dict {item: {op: [value1, value2]}, item: {op: value}}
    #ready for mongodb query
    def filters(self):
        def convert_filters(flts):
            if not flts:
                return {}
            merged = {}
            for f_item in flts:
                if f_item.bit_op == '$nor':
                    merged[f_item.bit_op] = [convert_filters(f_item.children)]
                elif f_item.bit_op:
                    merged[f_item.bit_op] = [convert_filters([f]) for f in f_item.children]
                else:
                    item, value = f_item.item, f_item.value
                    op = self.client.op_map(f_item.op)
                    eq_op = self.client.op_map('$eq')
                    ne_op = self.client.op_map('$ne')
                    in_op = self.client.op_map('$in')
                    nin_op = self.client.op_map('$nin')
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
            return merged
        return convert_filters(self._filters)

    def __iter__(self):
        return iter(self.execute())

    def __repr__(self):
        return f"<QueryBuilder filters: {self._filters}, ordered by: {self._order}>"

class DeleteQueryBuilder(QueryBuilder):
    def execute(self):
        models = [m for m in super().execute()]
        self.client.delete_many(models)
        return len(models)

    def __repr__(self):
        return f"<DeleteQueryBuilder filters: {self._filters}>"

class InsertQueryBuilder:
    def __init__(self, model_class, to_insert):
        self.model_class = model_class
        self.client = model_class._meta.client
        self.to_insert = to_insert

    def execute(self):
        if isinstance(self.to_insert, list):
            return self.client.insert_many(self.model_class, self.to_insert)
        elif self.to_insert: #dict
            return self.client.insert_one(self.model_class, self.to_insert)

    def __iter__(self):
        ids = self.execute()
        return iter(ids if isinstance(ids, list) else [ids])

class ReplaceQueryBuilder:
    def __init__(self, model_class, to_replace: dict):
        self.model_class = model_class
        self.client = model_class._meta.client
        self.to_replace = to_replace

    def execute(self):
        model = self.model_class
        fields = model._meta.fields
        data = self.to_replace
        for name in data:
            if fields[name].unique:
                dbItem = model.get_or_none(getattr(model, name) == data[name])
                if dbItem:
                    for name in data:
                        setattr(dbItem, name, data[name])
                else:
                    dbItem = model(**data)
                dbItem.save()
                return getattr(dbItem, model._meta.primary_key)

        raise AttributeError('Replace query requires at lease one unique field')

    def __iter__(self):
        ids = self.execute()
        return iter(ids if isinstance(ids, list) else [ids])

class UpdateQueryBuilder(QueryBuilder):
    def __init__(self, model_class, to_update):
        super().__init__(model_class)
        self._update = to_update #is a dict

    def execute(self):
        cnt = 0
        for e in super().execute():
            get_field = e._meta.fields.get
            for field_name, value in self._update.items():
                field = get_field(field_name, None)
                if field:
                    if isinstance(value, UpdateExpr):
                        #value = eval(str(value))
                        value = self.my_safe_eval(str(value), {}, locals())
                    setattr(e, field_name, value)
            self.client.update_one(e)
            cnt += 1
        return cnt

    @classmethod
    def my_safe_eval(cls, txt, g_dict, l_dict):
        code = compile(txt, '<user input>', 'eval')
        reason = None
        banned = ('eval', 'compile', 'exec', 'getattr', 'hasattr', 'setattr', 'delattr',
            'classmethod', 'globals', 'help', 'input', 'isinstance', 'issubclass', 'locals',
            'open', 'print', 'property', 'staticmethod', 'vars', 'os')
        for name in code.co_names:
            if re.search(r'^__\S*__$', name):
                reason = 'dunder attributes not allowed'
            elif name in banned:
                reason = 'arbitrary code execution not allowed'
            if reason:
                raise NameError(f'{name} not allowed : {reason}')
        return eval(code, g_dict, l_dict)

    def __repr__(self):
        return f"<UpdateQueryBuilder filters: {self._filters}>"


