#!/usr/bin/env python3
# -*- coding:utf-8 -*-
import datetime
from weedata import *
from test_base import *

from bson.objectid import ObjectId 

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
    
class TestQueryExecution(ModelTestCase):
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

    def test_selection(self):
        query = list(User.select())
        self.assertEqual(len(query), 6)
        query = list((Tweet.select().order_by(Tweet.liked)))
        self.assertEqual(query[0].dicts(remove_id=True), {'user_id':self.ids[1], 'content': 'java', 'liked': 2, 'disliked': 6})
        self.assertEqual(query[1].dicts(remove_id=True), {'user_id':self.ids[4], 'content': 'machinelearning', 'liked': 3, 'disliked': 15})
        query = list(User.select().limit(2))
        self.assertEqual(len(query), 2)

    def test_select_first_get(self):
        query = User.select().order_by(User.day)
        self.assertEqual(query.first().name, 'user4')
        query = Tweet.select().where(Tweet.liked == 100)
        self.assertIsNone(query.first())
        self.assertEqual(User.select().where(User.name == 'user6').get().email, 'user6@e.com')
        self.assertIsNone(User.select().where(User.name == 'x').get())

    def test_select_in_between(self):
        t1 = Tweet.select().where(Tweet.content.in_(['programming', 'python']))
        self.assertEqual(set(t.content for t in t1), set(['programming', 'python']))
        t2 = list(Tweet.select().where(Tweet.content.not_in(['backend', 'cloud'])))
        contents = [t.content for t in t2]
        self.assertTrue('backend' not in contents)
        self.assertTrue('cloud' not in contents)

        d = datetime.datetime
        users = list(User.select().where(User.day.between(d(1995,1,1), d(1999,12,31))).execute())
        emails = set([u.email for u in users])
        self.assertEqual(emails, set(['user5@e.com', 'user6@e.com']))

        ts = list(Tweet.select().where(Tweet.liked.between(61, 54)).execute())
        contents = set([t.content for t in ts])
        self.assertEqual(contents, set(['algorithm', 'python', 'agile']))
    
    #@requires_mongodb
    def test_select_and(self):
        user = User.select().where((User.name != 'user1') & (User.name != 'user2')).first()
        self.assertTrue((user.name != 'user1') and (user.name != 'user2'))

        user = User.select().where(User.name != 'user1').where(User.name != 'user2').first()
        self.assertTrue((user.name != 'user1') and (user.name != 'user2'))

        user = User.select().where((User.name == 'user1') & (User.times == 25)).first()
        self.assertEqual(user, None)

        users = User.select().where(((User.name != 'user1') & (User.name != 'user2') & (User.name != 'user3')))
        names = [u.name for u in users]
        self.assertTrue(('user1' not in names) and ('user2' not in names) and ('user3' not in names))

    #@requires_mongodb
    def test_select_or(self):
        usernames = set([user.name for user in User.select().where((User.name == 'user4') | (User.name == 'user3'))])
        self.assertEqual(usernames, set(['user4', 'user3']))

        users = User.select().where(((User.name > 'user5') | (User.name < 'user2'))).order_by(User.name)
        names = [u.name for u in users]
        self.assertEqual(names, ['user1', 'user6'])

    @requires_mongodb
    def test_select_nor(self):
        usernames = set([user.name for user in User.select().where(~(User.name == 'user4'))])
        self.assertEqual(usernames, set(['user1', 'user2', 'user3', 'user5', 'user6']))

        usernames = set([user.name for user in User.select().where(~(User.name != 'user4'))])
        self.assertEqual(usernames, set(['user4']))

        usernames = set([user.name for user in User.select().where(~((User.name == 'user4') | (User.name == 'user3')))])
        self.assertEqual(usernames, set(['user1', 'user2', 'user5', 'user6']))

        users = User.select().where(~((User.name > 'user5') | (User.name < 'user2'))).order_by(User.name)
        names = [u.name for u in users]
        self.assertEqual(names, ['user2', 'user3', 'user4', 'user5'])

    #@requires_mongodb
    def test_select_different_field(self):
        query = User.select().where((User.name != 'user1') & (User.email != 'user2@e.com') & (User.times == 0))
        self.assertEqual(query.first().name, 'user6')
        query = User.select().where(((User.name > 'user3') | (User.email >= 'user6@e.com')) & (User.times == 0))
        self.assertEqual(query.first().name, 'user6')

    @requires_mongodb
    def test_select_count(self):
        self.assertEqual(User.select().count(), len(self.users))
        self.assertEqual(Tweet.select().count(), len(self.t_ids))

        query = User.select().where(User.times >= 25)
        self.assertEqual(query.count(), 3)

        query = Tweet.select().where(Tweet.content == 'foo')
        self.assertEqual(query.count(), 0)

    #@requires_mongodb
    def test_select_partial(self):
        query = list(User.select(User.id))
        self.assertEqual(query[0].dicts()['name'], None)
        self.assertTrue(query[0].dicts()['id'])

    def test_get_by_id(self):
        user = User.get_by_id(self.ids[2])
        self.assertEqual(user.name, 'user3')

        user = User.get_by_key(self.ids[5])
        self.assertEqual(user.name, 'user6')
        
        user = User.get_or_none(User.id == self.ids[0])
        self.assertEqual(user.name, 'user1')

    @requires_mongodb
    def test_get_by_obj_id(self):
        user = User.get_by_key(ObjectId(self.ids[5]))
        self.assertEqual(user.name, 'user6')
        