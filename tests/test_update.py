#!/usr/bin/env python3
# -*- coding:utf-8 -*-
import datetime
from test_base import *

class User(Model):
    class Meta:
        database = database
    name = CharField(unique=True)
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
        Tweet.insert().execute()
        for t in tweets:
            self.t_ids.append(Tweet.insert({'user_id': id_, 'content': t[0], 'liked': t[1], 'disliked': t[2]}).execute())

    def test_get_upate(self):
        t = Tweet.select(Tweet.content, 'liked').where(Tweet.content == 'cloud').first()
        self.assertIn(t.disliked, [None, 8])
        self.assertEqual(t.liked, 40)
        self.assertEqual(t.content, 'cloud')
        t.content = 'CLOUD'
        t.save()
        t1 = Tweet.get_by_id(t.id)
        self.assertEqual(t1.content, 'CLOUD')

    def test_upate(self):
        User.update({User.times: (User.times + 10) * 2}).where(User.name == 'user2').execute()
        user = User.get(User.name == 'user2')
        self.assertEqual(user.times, 50)

        with database.atomic():
            User.update(times=1).where(User.name == 'user5').execute()
            user = User.get(User.name == 'user5')
            self.assertEqual(user.times, 1)

        with database.transaction():
            user.email = 'newemail@g.com'
            user.save()
            user = User.get(User.name == 'user5')
            self.assertEqual(user.email, 'newemail@g.com')

    def test_complicate_update(self):
        (Tweet.update({Tweet.liked: ((Tweet.liked / Tweet.disliked) + 1) * 3 }).
            where(Tweet.content.in_(['AI', 'backend'])).execute())
        ts = list(Tweet.select().where((Tweet.content == 'AI') | (Tweet.content == 'backend')).execute())
        self.assertEqual(set([t.content for t in ts]), set(['AI', 'backend']))
        self.assertEqual(set([t.liked for t in ts]), set([18, 33]))
        self.assertEqual(set([t.disliked for t in ts]), set([10, 2]))

    def test_get_or_create(self):
        user, created = User.get_or_create(name='user6', defaults={'day': datetime.datetime(1940, 10, 9), 'email': 'other@e.com', 'times': 0})
        self.assertEqual(created, False)
        self.assertEqual(user.email, 'user6@e.com')

        user, created = User.get_or_create(name='user7', defaults={'day': datetime.datetime(1940, 11, 9), 'email': '7@e.com', 'times': 11})
        self.assertEqual(created, True)
        self.assertEqual(user.email, '7@e.com')

        user = User.get(name='user7')
        self.assertEqual(user.name, 'user7')
        self.assertEqual(user.email, '7@e.com')
        self.assertEqual(user.times, 11)

        user.name = 'user8' #test rebuild index
        user.save()
        user = User.get(name='user8')
        self.assertEqual(user.email, '7@e.com')

        user.delete_instance()

    def test_replace(self):
        d = datetime.datetime
        id_ = User.get(name='user1').id
        data = {'name': 'user1', 'day': d(1990, 5, 15), 'email': 'new@e.com', 'times': 30}
        self.assertEqual(list(User.replace(data)), [id_])
        self.assertEqual(User.get(User.id == id_).times, 30)
        id_ = User.replace(name='user10', day=d(1990, 5, 15), email='10@10', times=100).execute()
        self.assertEqual(User.get(User.name == 'user10').times, 100)
        self.assertEqual(User.get(User.id == id_).email, '10@10')

        #Tweet without unique fields
        with self.assertRaisesCtx(AttributeError):
            Tweet.replace(user_id='user1', content='new', liked=1, disliked=20).execute()

        with self.assertRaisesCtx(ValueError):
            Tweet.replace('user1', 'new', 1, 20).execute()
        