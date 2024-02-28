#!/usr/bin/env python3
# -*- coding:utf-8 -*-
import datetime
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
    user = ForeignKeyField(User, backref='tweets', on_delete=True)
    content = TextField()
    liked = IntegerField()
    disliked = IntegerField()
    
class TestUpdating(ModelTestCase):
    database = database
    requires = [User, Tweet]

    def setUp(self):
        super().setUp()
        d = datetime.datetime
        self.user_datas = [
            {'name': 'user1', 'day': d(1990, 5, 15), 'email': 'user1@e.com', 'times': 20},
            {'name': 'user2', 'day': d(1985, 8, 22), 'email': 'user2@e.com', 'times': 15},
            {'name': 'user3', 'day': d(1980, 11, 8), 'email': 'user3@e.com', 'times': 30},
            {'name': 'user4', 'day': d(1978, 3, 4), 'email': 'user4@e.com', 'times': 25},
            {'name': 'user5', 'day': d(1995, 9, 17), 'email': 'user5@e.com', 'times': 25},
            {'name': 'user6', 'day': d(1999, 12, 10), 'email': 'user6@e.com', 'times': 0}
        ]
        self.users = [User.create(**data) for data in self.user_datas]
        tweets = [
            [('programming', 50, 10), ('technology', 30, 5), ('developer', 45, 8), ('coding', 25, 3),],
            [('algorithm', 60, 12), ('software', 40, 7), ('python', 55, 9), ('java', 2, 6),],
            [('database', 33, 4), ('web', 48, 11), ('debugging', 38, 8), ('frontend', 42, 7),],
            [('backend', 20, 2), ('AI', 50, 10)],
            [('machinelearning', 3, 15),],
            [('cloud', 40, 8), ('git', 30, 6), ('agile', 55, 12), ('cybersecurity', 28, 5),],
        ]
        self.t_ids = []
        for idx, user in enumerate(self.users):
            self.create_tweets(user, tweets[idx])

    def create_tweets(self, user, tweets):
        for t in tweets:
            self.t_ids.append(Tweet.insert({'user': user, 'content': t[0], 'liked': t[1], 'disliked': t[2]}).execute())

    def test_delete(self):
        self.assertEqual(Tweet.get_or_none(Tweet.content == 'algorithm').liked, 60)
        user = next(User.select().where(User.name == 'user2').execute())
        user.delete_instance()
        user = User.get(User.name == 'user2')
        self.assertEqual(user, None)
        self.assertEqual(Tweet.get_or_none(Tweet.content == 'algorithm'), None)
        
        User.delete().where(User.name == 'user5').execute()
        user = User.get(User.name == 'user5')
        self.assertEqual(user, None)
        self.assertEqual(Tweet.get_or_none(Tweet.content == 'machinelearning'), None)

        user = User.get(User.name == 'user1')
        self.assertEqual(user.name, 'user1')

        User.delete_by_id(self.users[0].id)
        self.assertEqual(User.get(User.name == 'user1'), None)

        t = Tweet.get()
        self.assertTrue(t != None)
        Tweet.delete().execute()
        t = Tweet.get()
        self.assertTrue(t == None)
        