#!/usr/bin/env python3
# -*- coding:utf-8 -*-
from contextlib import contextmanager
from functools import wraps
import datetime, logging, os, re, unittest
from unittest import mock    
from weedata import *

logger = logging.getLogger('weedata')

def new_connection(**kwargs):
    backEnd = os.getenv('WEEDATA_TEST_BACKEND')
    if backEnd == 'mongodb':
        return MongoDbClient("weedata_test", "mongodb://127.0.0.1:27017/")
    elif backEnd == 'redis':
        return RedisDbClient("weedata", "redis://127.0.0.1:6379/")
    elif backEnd == 'pickle':
        return PickleDbClient(':memory:')
    elif backEnd == 'datastore':
        return DatastoreClient(project="kindleear")
    else:
        raise ValueError(f'Unsupported backEnd {backEnd}')

database = new_connection()

class TestModel(Model):
    class Meta:
        database = database

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

    def tearDown(self):
        super().tearDown()

class ModelTestCase(ModelDatabaseTestCase):
    database = database
    requires = None

    def setUp(self):
        super().setUp()
        if self.requires:
            self.database.drop_tables(self.requires, safe=True)
            self.database.create_tables(self.requires, safe=True)

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
        return unittest.skipUnless(bool(os.environ.get('WEEDATA_SLOW_TESTS')), 'skipping slow test')(method)
    return decorator

def requires_mongodb(method):
    return skip_unless(os.getenv('WEEDATA_TEST_BACKEND') == 'mongodb', 'requires mongodb')(method)

def requires_datastore(method):
    return skip_unless(os.getenv('WEEDATA_TEST_BACKEND') == 'datastore', 'requires datastore')(method)

def requires_redis(method):
    return skip_unless(os.getenv('WEEDATA_TEST_BACKEND') == 'redis', 'requires redis')(method)

def requires_pickle(method):
    return skip_unless(os.getenv('WEEDATA_TEST_BACKEND') == 'pickle', 'requires pickle')(method)    

def skip_if_datastore(method):
    return skip_if(os.getenv('WEEDATA_TEST_BACKEND') == 'datastore', 'skip if datastore')(method)
