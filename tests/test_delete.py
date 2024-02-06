#!/usr/bin/env python3
# -*- coding:utf-8 -*-
import datetime
from weedata import *
from test_base import *

class User(Model):
    class Meta:
        database = database
    name = CharField()
    day = DateTimeField()
    email = CharField()
    times = IntegerField()

class Tweet(Model):
    class Meta:
        database = database
    user_id = CharField()
    content = TextField()
    liked = IntegerField()
    disliked = IntegerField()

class Register(Model):
    class Meta:
        database = database
    value = CharField()
    
class TestUpdating(ModelTestCase):
    database = database
    requires = [User, Tweet, Register]

    def setUp(self):
        super().setUp()
        d = datetime.datetime
        self.users = [
            {'name': 'user1', 'day': d(1990, 5, 15), 'email': 'user1@e.com', 'times': 20},
            {'name': 'user2', 'day': d(1985, 8, 22), 'email': 'user2@e.com', 'times': 15},
            {'name': 'user3', 'day': d(1980, 11, 8), 'email': 'user3@e.com', 'times': 30},
            {'name': 'user4', 'day': d(1978, 3, 4), 'email': 'user4@e.com', 'times': 25},
            {'name': 'user5', 'day': d(1995, 9, 17), 'email': 'user5@e.com', 'times': 25},
            {'name': 'user6', 'day': d(1999, 12, 10), 'email': 'user6@e.com', 'times': 0}
        ]
        self.ids = list(User.insert_many(self.users))
        tweets = [
            [('programming', 50, 10), ('technology', 30, 5), ('developer', 45, 8), ('coding', 25, 3),],
            [('algorithm', 60, 12), ('software', 40, 7), ('python', 55, 9), ('java', 2, 6),],
            [('database', 33, 4), ('web', 48, 11), ('debugging', 38, 8), ('frontend', 42, 7),],
            [('backend', 20, 2), ('AI', 50, 10)],
            [('machinelearning', 3, 15),],
            [('cloud', 40, 8), ('git', 30, 6), ('agile', 55, 12), ('cybersecurity', 28, 5),],
        ]
        self.t_ids = []
        for idx, id_ in enumerate(self.ids):
            self.create_tweets(self.ids[idx], tweets[idx])

    def create_tweets(self, id_, tweets):
        for t in tweets:
            self.t_ids.append(Tweet.insert({'user_id': id_, 'content': t[0], 'liked': t[1], 'disliked': t[2]}).execute())

    def test_delete(self):
        user = next(User.select().where(User.name == 'user2').execute())
        user.delete_instance()
        user = User.get(User.name == 'user2')
        self.assertEqual(user, None)
        
        User.delete().where(User.name == 'user5').execute()
        user = User.get(User.name == 'user5')
        self.assertEqual(user, None)
        user = User.get(User.name == 'user1')
        self.assertEqual(user.name, 'user1')

        t = Tweet.get()
        self.assertTrue(t != None)
        Tweet.delete().execute()
        t = Tweet.get()
        self.assertTrue(t == None)
        