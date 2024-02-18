#!/usr/bin/env python3
# -*- coding:utf-8 -*-
#an ORM/ODM for Google Cloud Datastore/MongoDB, featuring a compatible interface with Peewee.
#Author: cdhigh <http://github.com/cdhigh>
#Repository: <https://github.com/cdhigh/weedata>

__all__ = [
    'DoesNotExist', 'Field', 'PrimaryKeyField', 'BooleanField', 'IntegerField', 'BigIntegerField',
    'SmallIntegerField', 'BitField', 'TimestampField', 'IPField', 'FloatField', 'DoubleField',
    'DecimalField', 'CharField', 'TextField', 'FixedCharField', 'UUIDField', 'BlobField',
    'DateTimeField', 'DateField', 'TimeField', 'JSONField', 
]

import datetime

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
    
class DoesNotExist(Exception):
    pass

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

class Field(object):
    def __init__(self, default=None, enforce_type=False, index=False, unique=False, **kwargs):
        self.default = default if callable(default) else lambda: default
        self.enforce_type = enforce_type
        self.index = index
        self.unique = unique
    
    def __eq__(self, other):
        return ((other.__class__ == self.__class__) and (other.name == self.name) and 
            (other.model == self.model))

    def __hash__(self):
        return hash((self.model.__name__, self.name))

    def check_type(self, value):
        return True

    def add_to_class(self, klass, name):
        self.name = name
        self.model = klass
        klass._meta.fields[name] = self
        setattr(klass, name, FieldDescriptor(self))

    def db_value(self, value):
        return value

    @classmethod
    def python_value(self, value):
        return value

    __eq__ = comp_op('$eq')
    __ne__ = comp_op('$ne')
    __lt__ = comp_op('$lt')
    __gt__ = comp_op('$gt')
    __le__ = comp_op('$lte')
    __ge__ = comp_op('$gte')
    in_ = comp_op('$in')
    not_in = comp_op('$nin')
    
    def between(self, other1, other2):
        if other1 <= other2:
            child1 = self._generate_filter("$gt", other1)
            child2 = self._generate_filter("$lt", other2)
        else:
            child1 = self._generate_filter("$lt", other1)
            child2 = self._generate_filter("$gt", other2)
        return Filter(bit_op='$and', children=[child1, child2])

    def _generate_filter(self, op, other):
        if self.enforce_type and not self.check_type(other):
            raise ValueError("Comparing field {} with '{}' of type {}".format(self.name, other, type(other)))
        return Filter(self.name, op, other)

    def asc(self):
        return self.name
        
    def desc(self):
        return '-{}'.format(self.name)

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

class BooleanField(Field):
    pass

class IntegerField(Field):
    def check_type(self, value):
        return isinstance(value, int)

BigIntegerField = IntegerField
SmallIntegerField = IntegerField
BitField = IntegerField
TimestampField = IntegerField
IPField = IntegerField

class FloatField(Field):
    def check_type(self, value):
        return isinstance(value, float)

DoubleField = FloatField
DecimalField = FloatField

class CharField(Field):
    def check_type(self, value):
        return isinstance(value, str)

TextField = CharField
FixedCharField = CharField
UUIDField = CharField

class BlobField(Field):
    pass

class DateTimeField(Field):
    def check_type(self, value):
        return isinstance(value, datetime.datetime)

class DateField(Field):
    def check_type(self, value):
        return isinstance(value, datetime.date)

class TimeField(Field):
    def check_type(self, value):
        return isinstance(value, datetime.time)

class JSONField(Field):
    def check_type(self, value):
        json_types = [bool, int, float, str, list, dict, tuple]
        return any(isinstance(value, json_type) for json_type in json_types)

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
    def __init__(self, item=None, op=None, value=None, bit_op=None, children=None):
        self.item = item
        self.op = op
        self.value = value
        self.bit_op = bit_op #If composed of & | ~
        self.children = children or []

    def clone(self):
        return Filter(self.item, self.op, self.value, self.bit_op, self.children)

    __and__ = filter_op('$and')
    __or__ = filter_op('$or')

    def __invert__(self):
        self.children = [self.clone()]
        self.bit_op = '$nor' #use '$nor' instead Of '$not' can simplfy code generation
        self.item = self.op = self.value = None
        return self

    def __str__(self):
        if self.children:
            s = []
            for c in self.children:
                s.append(str(c))
                return f'{self.bit_op}\n' + '\n'.join(s)
        else:
            return f"[{self.item} {self.op} {self.value}]"
    