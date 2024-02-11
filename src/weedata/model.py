#!/usr/bin/env python3
# -*- coding:utf-8 -*-
#an ORM/ODM for Google Cloud Datastore/MongoDB, featuring a compatible interface with Peewee.
#Author: cdhigh <http://github.com/cdhigh>
#Repository: <https://github.com/cdhigh/weedata>
import copy
from .fields import Field, FieldDescriptor, PrimaryKeyField, DoesNotExist, Filter
from .queries import QueryBuilder, DeleteQueryBuilder, InsertQueryBuilder, UpdateQueryBuilder

class BaseModel(type):
    inheritable_options = ['client', 'order_by', 'primary_key']

    def __new__(cls, name, bases, attrs):
        if not bases:
            return super(BaseModel, cls).__new__(cls, name, bases, attrs)

        meta_options = {}
        meta = attrs.pop('Meta', None)
        if meta:
            meta_options.update((k, v) for k, v in meta.__dict__.items() if not k.startswith('_'))
            #for compatibilty, app code use the name "database", convert to "client" here
            if 'database' in meta_options:
                client = meta_options.pop('database', None)
                meta_options['client'] = client

        for b in bases:
            base_meta = getattr(b, '_meta', None)
            if not base_meta:
                continue
            
            for (k, v) in base_meta.__dict__.items():
                if k in cls.inheritable_options and k not in meta_options:
                    meta_options[k] = v

            for (k, v) in b.__dict__.items():
                if isinstance(v, FieldDescriptor) and k not in attrs:
                    attrs[k] = copy.deepcopy(v.field_inst)

        meta_options.setdefault('client', None)
        meta_options.setdefault('primary_key', 'id')
        attrs[meta_options['primary_key']] = PrimaryKeyField()

        # initialize the new class and set the magic attributes
        cls = super(BaseModel, cls).__new__(cls, name, bases, attrs)
        cls._meta = ModelOptions(cls, **meta_options)
        cls._data = None
        cls._dirty = None

        # replace the fields with field descriptors, calling the add_to_class hook
        for name, attr in cls.__dict__.items():
            if isinstance(attr, Field):
                attr.add_to_class(cls, name)
        
        cls._meta.prepared()
        return cls

class ModelOptions(object):
    def __init__(self, cls, client=None, order_by=None, primary_key='id', **kwargs):
        self.model_class = cls
        self.name = cls.__name__
        self.fields = {}
        self.defaults = {}
        self.client = client #database here is actually a database client
        self.order_by = order_by
        self.primary_key = primary_key
        
    def prepared(self):
        for field in self.fields.values():
            if field.default is not None:
                self.defaults[field] = field.default

class Model(object, metaclass=BaseModel):
    def __init__(self, **kwargs):
        self._key = kwargs.get('_key', None)
        self._data = dict((f.name, v()) for f, v in self._meta.defaults.items())
        self._dirty = {'__key__': True, '_id': True}
        for name, value in kwargs.items():
            setattr(self, name, value)

    @classmethod
    def create(cls, **kwargs):
        inst = cls(**kwargs)
        return inst.save()

    @classmethod
    def select(cls, *args):
        return QueryBuilder(cls, *args)

    @classmethod
    def delete(cls):
        return DeleteQueryBuilder(cls, getattr(cls, cls._meta.primary_key, None))

    @classmethod
    def update(cls, *args, **kwargs):
        return UpdateQueryBuilder(cls, cls.combine_args_kwargs(*args, **kwargs))

    @classmethod
    def insert(cls, *args, **kwargs):
        return InsertQueryBuilder(cls, cls.combine_args_kwargs(*args, **kwargs))
        
    @classmethod
    def insert_many(cls, datas: list):
        return InsertQueryBuilder(cls, datas)

    @classmethod
    def combine_args_kwargs(cls, *args, **kwargs):
        if (len(args) > 1) or (args and not isinstance(args[0], dict)):
            raise ValueError('The keyword argument have to be a dict')
        args = args[0] if args else {}
        args.update(kwargs)
        return dict(((f.name if isinstance(f, Field) else f), v) for f, v in args.items())
        
    @classmethod
    def get(cls, *query, **filters):
        sq = cls.select()
        if query:
            # Handle simple lookup using just the primary key.
            if len(query) == 1 and isinstance(query[0], str):
                sq = sq.filter_by_id(query[0])
            else:
                sq = sq.where(*query)
        for item, value in filters.items():
            sq = sq.where(Filter(item, "$eq", value))
        return sq.get()

    @classmethod
    def get_or_create(cls, **kwargs):
        defaults = kwargs.pop('defaults', {})
        query = cls.select()
        for field, value in kwargs.items():
            query = query.where(getattr(cls, field) == value)

        model = query.get()
        if model:
            return model, False
        else:
            if defaults:
                kwargs.update(defaults)
            with cls._meta.client.atomic():
                return cls.create(**kwargs), True

    @classmethod
    def get_or_none(cls, query=None):
        try:
            return cls.get(query)
        except:
            return None

    @classmethod
    def get_by_key(cls, key):
        return cls.select().filter_by_key(key).first()

    @classmethod
    def get_by_id(cls, sid):
        return cls.select().filter_by_id(sid).first()

    @classmethod
    def delete_by_id(cls, pk):
        return cls.delete().filter_by_id(pk).execute()
        
    def save(self, **kwargs):
        id_ = self.client.update_one(self)
        setattr(self, self._meta.primary_key, id_)
        return self

    def delete_instance(self, **kwargs):
        self.client.delete_one(self)

    @property
    def client(self):
        return self._meta.client

    #Convert model into a dict
    #: params only=[Model.title, ...]
    #: params exclude=[Model.title, ...]
    #: remove_id - remove key and id field from dict
    #: db_value - if prepared for saving to db
    #: only_dirty - export items unsaved only
    def dicts(self, **kwargs):
        only = [x.name for x in kwargs.get('only', [])]
        exclude = [x.name for x in kwargs.get('exclude', [])]
        should_skip = lambda n: (n in exclude) or (only and (n not in only))
        db_value = kwargs.get('db_value', False)
        only_dirty = kwargs.get('only_dirty', False)

        data = {}
        for name, field in self._meta.fields.items():
            if not should_skip(name) and (not only_dirty or self._dirty.get(name, False)):
                value = getattr(self, name, None)
                data[name] = field.db_value(value) if db_value else value

        if kwargs.get('remove_id'):
            data.pop('_key', None)
            data.pop('id', None)
            data.pop('_id', None)
        return data

    @classmethod
    def bind(cls, client):
        cls._meta.client = client
        
    @classmethod
    def create_table(cls, **kwargs):
        pass

    @classmethod
    def drop_table(cls, **kwargs):
        self.client.drop_table(cls._meta.name)

    def atomic(self, **kwargs):
        return self.client.transaction(**kwargs)

    def clear_dirty(self, field_name):
        field_name = field_name if isinstance(field_name, list) else [field_name]
        excluded = ['__key__', '_id', self.client.db_id_name()]
        for name in field_name:
            if name not in excluded:
                self._dirty[name] = False
