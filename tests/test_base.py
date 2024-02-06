#!/usr/bin/env python3
# -*- coding:utf-8 -*-
from contextlib import contextmanager
from functools import wraps
import datetime, logging, os, re, unittest
from unittest import mock

from weedata import *

logger = logging.getLogger('weedata')

BACKEND = os.environ.get('WEEDATA_TEST_BACKEND', 'mongodb').lower()
VERBOSITY = int(os.environ.get('WEEDATA_TEST_VERBOSITY') or 1)
SLOW_TESTS = bool(os.environ.get('WEEDATA_SLOW_TESTS'))

def new_connection(**kwargs):
    if BACKEND == 'mongodb':
        return MongoDbClient("weedata_test", "mongodb://localhost:27017/")
    else:
        return DatastoreClient(project="kindleear")

database = new_connection()

class TestModel(Model):
    class Meta:
        database = database

class Person(TestModel):
    first = CharField()
    last = CharField()
    dob = DateField(index=True)

class Note(TestModel):
    author = CharField()
    content = TextField()


class Category(TestModel):
    parent = CharField()
    name = CharField(max_length=20, primary_key=True)


class Relationship(TestModel):
    from_person = CharField()
    to_person = CharField()


class Register(TestModel):
    value = IntegerField()


class User(TestModel):
    username = CharField()

class Account(TestModel):
    email = CharField()
    user = CharField()


class Tweet(TestModel):
    user = CharField()
    content = TextField()
    timestamp = TimestampField()


class Favorite(TestModel):
    user = CharField()
    tweet = CharField()


class Sample(TestModel):
    counter = IntegerField()
    value = FloatField(default=1.0)


class SampleMeta(TestModel):
    sample = CharField()
    value = FloatField(default=0.0)


class A(TestModel):
    a = TextField()
class B(TestModel):
    a = CharField()
    b = TextField()
class C(TestModel):
    b = CharField()
    c = TextField()


class Emp(TestModel):
    first = CharField()
    last = CharField()
    empno = CharField(unique=True)

class OCTest(TestModel):
    a = CharField(unique=True)
    b = IntegerField(default=0)
    c = IntegerField(default=0)


class UKVP(TestModel):
    key = TextField()
    value = IntegerField()
    extra = IntegerField()

class DfltM(TestModel):
    name = CharField()
    dflt1 = IntegerField(default=1)
    dflt2 = IntegerField(default=lambda: 2)
    dfltn = IntegerField(null=True)


class QueryLogHandler(logging.Handler):
    def __init__(self, *args, **kwargs):
        self.queries = []
        logging.Handler.__init__(self, *args, **kwargs)

    def emit(self, record):
        self.queries.append(record)

class BaseTestCase(unittest.TestCase):
    def setUp(self):
        self._qh = QueryLogHandler()
        logger.setLevel(logging.DEBUG)
        logger.addHandler(self._qh)

    def tearDown(self):
        logger.removeHandler(self._qh)

    def assertIsNone(self, value):
        self.assertTrue(value is None, '%r is not None' % value)

    def assertIsNotNone(self, value):
        self.assertTrue(value is not None, '%r is None' % value)

    @contextmanager
    def assertRaisesCtx(self, exceptions):
        try:
            yield
        except Exception as exc:
            if not isinstance(exc, exceptions):
                raise AssertionError('Got %s, expected %s' % (exc, exceptions))
        else:
            raise AssertionError('No exception was raised.')

    @property
    def history(self):
        return self._qh.queries

class DatabaseTestCase(BaseTestCase):
    database = database

    def setUp(self):
        super().setUp()

    def tearDown(self):
        super().tearDown()
        self.database.close()

    def execute(self, sql, params=None):
        pass

class ModelDatabaseTestCase(DatabaseTestCase):
    database = database
    requires = None

    def setUp(self):
        super().setUp()
        self._db_mapping = {}
        # Override the model's database object with test db.
        #if self.requires:
        #    for model in self.requires:
        #        self._db_mapping[model] = model._meta.database
        #        model._meta.set_database(self.database)

    def tearDown(self):
        # Restore the model's previous database object.
        #if self.requires:
        #    for model in self.requires:
        #        model._meta.set_database(self._db_mapping[model])
        super().tearDown()

class ModelTestCase(ModelDatabaseTestCase):
    database = database
    requires = None

    def setUp(self):
        super().setUp()
        if self.requires:
            self.database.drop_tables(self.requires, safe=True)

    def tearDown(self):
        if self.requires:
            self.database.drop_tables(self.requires, safe=True)
        super().tearDown()

def requires_models(*models):
    def decorator(method):
        @wraps(method)
        def inner(self):
            self.database.drop_tables(models, safe=True)
            self.database.create_tables(models)
            try:
                method(self)
            finally:
                self.database.drop_tables(models)
        return inner
    return decorator

def skip_if(expr, reason='n/a'):
    def decorator(method):
        return unittest.skipIf(expr, reason)(method)
    return decorator

def skip_unless(expr, reason='n/a'):
    def decorator(method):
        return unittest.skipUnless(expr, reason)(method)
    return decorator

def slow_test():
    def decorator(method):
        return unittest.skipUnless(SLOW_TESTS, 'skipping slow test')(method)
    return decorator

def requires_mongodb(method):
    return skip_unless(BACKEND == 'mongodb', 'requires mongodb')(method)

def requires_datastore(method):
    return skip_unless(BACKEND == 'datastore', 'requires datastore')(method)
