#!/usr/bin/env python3
# -*- coding:utf-8 -*-
#an ORM/ODM for Google Cloud Datastore/MongoDB/redis, featuring a compatible interface with Peewee.
#Author: cdhigh <http://github.com/cdhigh>
#Repository: <https://github.com/cdhigh/weedata>

__all__ = [
    'DoesNotExist', 'Field', 'PrimaryKeyField', 'BooleanField', 'IntegerField', 'BigIntegerField',
    'SmallIntegerField', 'BitField', 'TimestampField', 'IPField', 'FloatField', 'DoubleField',
    'DecimalField', 'CharField', 'TextField', 'FixedCharField', 'UUIDField', 'BlobField',
    'DateTimeField', 'JSONField', 'ForeignKeyField', 'Filter',
]

import datetime, json
    
class DoesNotExist(Exception):
    pass

def filter_op(op):
    def inner(self, other):
        assert(isinstance(other, Filter))
        if self.bit_op == op:
            self.children.append(other)
            return self
        else:
            return Filter(bit_op=op, children=[self, other])
    return inner

class Filter:
    EQ = '$eq'
    NE = '$ne'
    LT = '$lt'
    GT = '$gt'
    LE = '$lte'
    GE = '$gte'
    IN = '$in'
    NIN = '$nin'
    AND = '$and'
    OR = '$or'
    NOR = '$nor'

    def __init__(self, item=None, op=None, value=None, bit_op=None, children=None):
        self.item = item
        self.op = op
        self.value = value
        self.bit_op = bit_op #If composed of & | ~
        self.children = children or []

    def isFilterById(self, idName):
        return (self.item == idName) and (self.op == self.EQ) and (not self.bit_op)

    def clone(self, encoding=None):
        children = [c.clone(encoding) for c in self.children]
        if encoding:
            item = self.item.encode(encoding) if isinstance(self.item, str) else self.item
            return Filter(item, self.op, self.value, self.bit_op, children)
        else:
            return Filter(self.item, self.op, self.value, self.bit_op, children)

    __and__ = filter_op('$and')
    __or__ = filter_op('$or')

    def __invert__(self):
        self.children = [self.clone()]
        self.bit_op = self.NOR #use '$nor' instead Of '$not' can simplfy code generation
        self.item = self.op = self.value = None
        return self

    def __str__(self): # pragma: no cover
        if self.children:
            s = []
            for c in self.children:
                s.append(str(c))
            return f'{self.bit_op}\n' + '\n'.join(s)
        else:
            return f"[{self.item} {self.op} {self.value}]"

class FieldDescriptor(object):
    def __init__(self, field):
        self.field_inst = field
        self.field_name = field.name

    def __get__(self, instance, instance_type=None):
        if instance:
            return instance._data.get(self.field_name)
        return self.field_inst

    def __set__(self, instance, value):
        field_name = self.field_name
        if self.field_inst.enforce_type and not self.field_inst.check_type(value):
            raise ValueError(f'Trying to set a different type of value to "{field_name}"')
        instance._data[field_name] = value
        instance._dirty[field_name] = True

class ForeignKeyDescriptor(FieldDescriptor):
    def __init__(self, field, foreign_model):
        super().__init__(field)
        self.foreign_model = foreign_model

    def get_object_or_id(self, instance):
        field_name = self.field_name
        foreign_id = instance._data.get(field_name)
        if foreign_id:
            obj = instance._obj_cache.get(field_name, None)
            if not obj:
                obj = self.foreign_model.get_by_id(foreign_id)
                instance._obj_cache[field_name] = obj
            return obj
        elif not self.field_inst.null:
            raise DoesNotExist(f'Foreign key {field_name} is null')
        return foreign_id

    def __get__(self, instance, instance_type=None):
        if instance:
            return self.get_object_or_id(instance)
        return self.field_inst # pragma: no cover

    def __set__(self, instance, value):
        field_name = self.field_name
        if isinstance(value, self.foreign_model):
            foreign_key = value.get_id()
            if not foreign_key:
                raise DoesNotExist(f'Foreign key {field_name} is null')
            instance._data[field_name] = foreign_key
            instance._obj_cache[field_name] = value
        else:
            instance._data[field_name] = value
        instance._dirty[field_name] = True

class BackRefDescriptor(object):
    def __init__(self, field):
        self.field_inst = field
        self.foreign_model = field.model

    def __get__(self, instance, instance_type=None):
        if instance:
            return self.foreign_model.select().where(self.field_inst == instance.get_id())
        return self # pragma: no cover

#Used for overloading arithmetic operators
def arith_op(op, reverse=False):
    def inner(self, other):
        return UpdateExpr(other, op, self) if reverse else UpdateExpr(self, op, other)
    return inner

#Used for overloading comparison operators
def comp_op(op):
    def inner(self, other):
        return self._generate_filter(op, other)
    return inner

class Field(object):
    def __init__(self, default=None, enforce_type=False, index=False, unique=False, null=False, **kwargs):
        self.default = default if callable(default) else lambda: default
        self.enforce_type = enforce_type
        self.index = index
        self.unique = unique
        self.null = null
        self.bytes_store = False
    
    def __eq__(self, other):
        return ((other.__class__ == self.__class__) and (other.name == self.name) and 
            (other.model == self.model))

    def __hash__(self):
        return hash((self.model.__name__, self.name))

    def check_type(self, value):
        return True

    def add_to_class(self, klass, name, bytes_store=False):
        self.name = name
        self.model = klass
        self.bytes_store = bytes_store
        klass._meta.fields[name] = self
        setattr(klass, name, FieldDescriptor(self))

    def db_value(self, value):
        return value

    def python_value(self, value):
        return value

    def between(self, other1, other2):
        if other1 <= other2:
            child1 = self._generate_filter(Filter.GT, other1)
            child2 = self._generate_filter(Filter.LT, other2)
        else:
            child1 = self._generate_filter(Filter.LT, other1)
            child2 = self._generate_filter(Filter.GT, other2)
        return Filter(bit_op=Filter.AND, children=[child1, child2])

    def _generate_filter(self, op, other):
        if self.enforce_type and not self.check_type(other):
            raise ValueError("Comparing field {} with '{}' of type {}".format(self.name, other, type(other)))
        return Filter(self.name, op, other)

    def asc(self):
        return self.name
        
    def desc(self):
        return '-{}'.format(self.name)

    __eq__ = comp_op(Filter.EQ)
    __ne__ = comp_op(Filter.NE)
    __lt__ = comp_op(Filter.LT)
    __gt__ = comp_op(Filter.GT)
    __le__ = comp_op(Filter.LE)
    __ge__ = comp_op(Filter.GE)
    in_ = comp_op(Filter.IN)
    not_in = comp_op(Filter.NIN)
    
    __add__ = arith_op('+')
    __sub__ = arith_op('-')
    __mul__ = arith_op('*')
    __truediv__ = arith_op('/')
    __floordiv__ = arith_op('//')
    __mod__ = arith_op('%')
    __pow__ = arith_op('**')
    __lshift__ = arith_op('<<')
    __rshift__ = arith_op('>>')
    __and__ = arith_op('&')
    __or__ = arith_op('|')
    __xor__ = arith_op('^')
    __radd__ = arith_op('+', reverse=True)
    __rsub__ = arith_op('-', reverse=True)
    __rmul__ = arith_op('*', reverse=True)

class PrimaryKeyField(Field):
    def _generate_filter(self, op, other):
        other = self.model._meta.client.ensure_key(other)
        return Filter(self.model._meta.client.db_id_name(), op, other)
    def db_value(self, value):
        if self.bytes_store:
            return value.encode('utf-8') if isinstance(value, str) else value
        else:
            return value
    def python_value(self, value):
        if self.bytes_store:
            return value.decode('utf-8') if isinstance(value, bytes) else value
        else:
            return value

class ForeignKeyField(Field):
    def __init__(self, model, backref=None, on_delete=None, **kwargs):
        super().__init__(**kwargs)
        self.foreign_model = model
        self.backref = backref
        self.on_delete = on_delete

    def add_to_class(self, klass, name, bytes_store=False):
        self.name = name
        self.model = klass
        self.bytes_store = bytes_store
        klass._meta.fields[name] = self
        setattr(klass, name, ForeignKeyDescriptor(self, self.foreign_model))
        self.foreign_model._meta.backref[self.backref or klass._meta.name + '_ref'] = self
        if self.backref:
            setattr(self.foreign_model, self.backref, BackRefDescriptor(self))

    def db_value(self, value):
        if isinstance(value, self.foreign_model):
            value = value.get_id()
        if self.bytes_store:
            return value.encode('utf-8') if isinstance(value, str) else value
        else:
            return value
    def python_value(self, value):
        if self.bytes_store:
            return value.decode('utf-8') if isinstance(value, bytes) else value
        else:
            return value    

    def _generate_filter(self, op, other):
        other = self.model._meta.client.ensure_key(other)
        return Filter(self.name, op, str(other))

class BooleanField(Field):
    def db_value(self, value):
        if self.bytes_store:
            return str(bool(value)).encode('utf-8') if value is not None else b'None'
        else:
            return value
    def python_value(self, value):
        if self.bytes_store:
            return {b'True': True, b'None': None}.get(value, False)
        else:
            return value

class IntegerField(Field):
    def check_type(self, value):
        return isinstance(value, int)
    def db_value(self, value):
        if self.bytes_store:
            return str(int(value)).encode('utf-8') if value is not None else b''
        else:
            return value
    def python_value(self, value):
        if self.bytes_store:
            return int(value.decode('utf-8')) if value else None
        else:
            return int(value) if value is not None else None

BigIntegerField = IntegerField
SmallIntegerField = IntegerField
BitField = IntegerField
TimestampField = IntegerField
IPField = IntegerField

class FloatField(Field):
    def check_type(self, value):
        return isinstance(value, (int, float))
    def db_value(self, value):
        if self.bytes_store:
            return str(float(value)).encode('utf-8') if value is not None else b''
        else:
            return value
    def python_value(self, value):
        if self.bytes_store:
            return float(value.decode('utf-8')) if value else None
        else:
            return float(value) if value is not None else None

DoubleField = FloatField
DecimalField = FloatField

class CharField(Field):
    def check_type(self, value):
        return isinstance(value, (str, bytes))
    def db_value(self, value):
        if self.bytes_store:
            return value.encode('utf-8') if isinstance(value, str) else value
        else:
            return value
    def python_value(self, value):
        if self.bytes_store:
            return value.decode('utf-8') if value is not None else None
        else:
            return value

TextField = CharField
FixedCharField = CharField
UUIDField = CharField

class BlobField(Field):
    def check_type(self, value):
        return isinstance(value, bytes)
    def db_value(self, value):
        return value
    def python_value(self, value):
        return value

class DateTimeField(Field):
    def check_type(self, value):
        return isinstance(value, datetime.datetime)
    def db_value(self, value):
        if self.bytes_store:
            return value.isoformat().encode('utf-8') if value is not None else b''
        else:
            return value
    def python_value(self, value):
        if self.bytes_store:
            return datetime.datetime.fromisoformat(value.decode('utf-8')) if value else None
        else:
            return value

class JSONField(Field):
    def check_type(self, value):
        json_types = [type(None), bool, int, float, str, list, dict, tuple]
        return any(isinstance(value, json_type) for json_type in json_types)
    def db_value(self, value):
        if self.bytes_store:
            return json.dumps(value).encode('utf-8')
        else:
            return value
    def python_value(self, value):
        if self.bytes_store:
            return json.loads(value.decode('utf-8')) if value else None
        else:
            return value

    @classmethod
    def list_default(cls):
        return []
    @classmethod
    def dict_default(cls):
        return {}


class UpdateExpr:
    def __init__(self, inst, op, other):
        self.inst = inst
        self.op = op
        self.other = other

    __add__ = arith_op('+')
    __sub__ = arith_op('-')
    __mul__ = arith_op('*')
    __truediv__ = arith_op('/')
    __floordiv__ = arith_op('//')
    __mod__ = arith_op('%')
    __pow__ = arith_op('**')
    __lshift__ = arith_op('<<')
    __rshift__ = arith_op('>>')
    __and__ = arith_op('&')
    __or__ = arith_op('|')
    __xor__ = arith_op('^')
    __radd__ = arith_op('+', reverse=True)
    __rsub__ = arith_op('-', reverse=True)
    __rmul__ = arith_op('*', reverse=True)

    def __str__(self):
        inst = self.inst
        if isinstance(inst, Field):
            inst = f'e.{inst.name}'
        elif isinstance(inst, str):
            inst = f'"{inst}"'
            
        other = self.other
        if isinstance(other, Field):
            other = f'e.{other.name}'
        elif isinstance(other, str):
            other = f'"{other}"'
        
        return f'({inst} {self.op} {other})'

