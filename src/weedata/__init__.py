#!/usr/bin/env python3
# -*- coding:utf-8 -*-
#an ORM/ODM for Google Cloud Datastore/MongoDB/redis, featuring a compatible interface with Peewee.
#Author: cdhigh <http://github.com/cdhigh>
#Repository: <https://github.com/cdhigh/weedata>

__version__ = '0.2.1'

from .client import DatastoreClient, MongoDbClient, RedisDbClient, PickleDbClient
from .model import Model
from .fields import *
from .queries import QueryBuilder, DeleteQueryBuilder, InsertQueryBuilder, UpdateQueryBuilder
