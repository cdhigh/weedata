#!/usr/bin/env python3
# -*- coding:utf-8 -*-
import calendar, datetime, time, uuid
from collections import defaultdict
from test_base import *

class IntModel(TestModel):
    value = IntegerField()
    value_null = IntegerField()

class DefaultValues(TestModel):
    data = IntegerField(default=17)
    data_callable = IntegerField(default=lambda: 1337)


class TestDefaultValues(ModelTestCase):
    requires = [DefaultValues]

    def test_default_values(self):
        d = DefaultValues()
        self.assertEqual(d.data, 17)
        self.assertEqual(d.data_callable, 1337)
        d.save()

        d_db = DefaultValues.get(DefaultValues.id == d.id)
        self.assertEqual(d_db.data, 17)
        self.assertEqual(d_db.data_callable, 1337)

    def test_defaults_create(self):
        d = DefaultValues.create()
        self.assertEqual(d.data, 17)
        self.assertEqual(d.data_callable, 1337)

        d_db = DefaultValues.get(DefaultValues.id == d.id)
        self.assertEqual(d_db.data, 17)
        self.assertEqual(d_db.data_callable, 1337)

class TestIntegerField(ModelTestCase):
    requires = [IntModel]

    def test_integer_field(self):
        i1 = IntModel.create(value=1)
        i2 = IntModel.create(value=2, value_null=20)

        vals = [(i.value, i.value_null) for i in IntModel.select().order_by(IntModel.value.asc())]
        self.assertEqual(vals, [(1, None), (2, 20)])

class FloatModel(TestModel):
    value = FloatField()
    value_null = FloatField(null=True)

class TestFloatField(ModelTestCase):
    requires = [FloatModel]

    def test_float_field(self):
        f1 = FloatModel.create(value=1.23)
        f2 = FloatModel.create(value=3.14, value_null=0.12)

        query = FloatModel.select()
        self.assertEqual(set([(f.value, f.value_null) for f in query]),
                         set([(1.23, None), (3.14, 0.12)]))

class BoolModel(TestModel):
    value = BooleanField(null=True)
    name = CharField()

class TestBooleanField(ModelTestCase):
    requires = [BoolModel]

    def test_boolean_field(self):
        BoolModel.create(value=True, name='t')
        BoolModel.create(value=False, name='f')
        BoolModel.create(value=None, name='n')

        vals = sorted((b.name, b.value) for b in BoolModel.select())
        self.assertEqual(vals, [('f', False), ('n', None), ('t', True)])

class User(TestModel):
    username = CharField()

class Tweet(TestModel):
    user = ForeignKeyField(User, backref='tweets')
    content = TextField()
    timestamp = TimestampField()

class U2(TestModel):
    username = TextField()

class T2(TestModel):
    user = TextField()
    content = TextField()

class BlobModel(TestModel):
    data = BlobField()

class TestBlobField(ModelTestCase):
    requires = [BlobModel]

    def test_blob_field(self):
        b = BlobModel.create(data=b'\xff\x01')
        b_db = BlobModel.get(BlobModel.data == b'\xff\x01')
        self.assertEqual(b.id, b_db.id)

        data = b_db.data
        if isinstance(data, memoryview):
            data = data.tobytes()
        elif not isinstance(data, bytes):
            data = bytes(data)
        self.assertEqual(data, b'\xff\x01')

class Item(TestModel):
    price = IntegerField()
    multiplier = FloatField(default=1.)

class ListField(TextField):
    def db_value(self, value):
        if self.bytes_store:
            return ','.join(value).encode('utf-8') if value is not None else b'None'
        else:
            return ','.join(value) if value else ''

    def python_value(self, value):
        if self.bytes_store:
            if value in [None, b'None']:
                return None
            elif value:
                return value.decode('utf-8').split(',')
            else:
                return []
        else:
            return value.split(',') if value else []

class Todo(TestModel):
    content = TextField()
    tags = ListField()
    jtags = JSONField()

class TestCustomField(ModelTestCase):
    requires = [Todo]
    def test_custom_field(self):
        t1 = Todo.create(content='t1', tags=['t1-a', 't1-b'], jtags=['t1-a', 't1-b'])
        t2 = Todo.create(content='t2', tags=[], jtags=[])

        t1_db = Todo.get(Todo.id == t1.id)
        self.assertEqual(t1_db.tags, ['t1-a', 't1-b'])
        self.assertEqual(t1_db.jtags, ['t1-a', 't1-b'])

        t2_db = Todo.get(Todo.id == t2.id)
        self.assertEqual(t2_db.tags, [])
        self.assertEqual(t2_db.jtags, [])

class SM(TestModel):
    text_field = TextField()
    char_field = CharField()

class TestStringFields(ModelTestCase):
    requires = [SM]

    def test_string_fields(self):
        bdata = b'b1'
        udata = b'u1'.decode('utf8')

        sb = SM.create(text_field=bdata, char_field=bdata)
        su = SM.create(text_field=udata, char_field=udata)

        sb_db = SM.get(SM.id == sb.id)
        self.assertIn(sb_db.text_field, [b'b1', 'b1'])
        self.assertIn(sb_db.char_field, [b'b1', 'b1'])

        su_db = SM.get(SM.id == su.id)
        self.assertEqual(su_db.text_field, 'u1')
        self.assertEqual(su_db.char_field, 'u1')

class InvalidTypes(TestModel):
    tfield = TextField(enforce_type=True)
    ifield = IntegerField(enforce_type=True)
    ffield = FloatField(enforce_type=True)

class TestSqliteInvalidDataTypes(ModelTestCase):
    database = database
    requires = [InvalidTypes]

    def test_invalid_data_types(self):
        with self.assertRaisesCtx(ValueError):
            it = InvalidTypes.create(tfield=100, ifield='five', ffield='pi')
        with self.assertRaisesCtx(ValueError):
            it_db1 = InvalidTypes.get(InvalidTypes.tfield == 100)
            it_db2 = InvalidTypes.get(InvalidTypes.ifield == 'five')
            it_db3 = InvalidTypes.get(InvalidTypes.ffield == 'pi')

class U2(TestModel):
    username = TextField()


class T2(TestModel):
    user = ForeignKeyField(U2, backref='tweets', on_delete=True, null=True, enforce_type=True)
    content = TextField()

class TestForeignKeyField(ModelTestCase):
    requires = [User, Tweet, U2, T2]

    def test_set_fk(self):
        huey = User.create(username='huey')
        zaizee = User.create(username='zaizee')
        tweet = Tweet.create(content='meow', user=huey)
        self.assertEqual(tweet.user.username, 'huey')

        tweet = Tweet.create(content='purr', user=zaizee.id)
        self.assertEqual(tweet.user.username, 'zaizee')

    def test_follow_attributes(self):
        huey = User.create(username='huey')
        Tweet.create(content='meow', user=huey)
        Tweet.create(content='hiss', user=huey)

        query = Tweet.select().order_by(Tweet.content)
        self.assertEqual([(tweet.content, tweet.user.username) for tweet in query],
                         [('hiss', 'huey'), ('meow', 'huey')])
        self.assertEqual(set([t.content for t in huey.tweets]), set(['meow', 'hiss']))

        self.assertRaises(AttributeError, lambda: Tweet.user.foo)

        with self.assertRaisesCtx(DoesNotExist):
            Tweet.create(content='emu')

        with self.assertRaisesCtx(DoesNotExist):
            Tweet.create(content='emu', user=User(username='huey'))
        
    def test_disable_backref(self):
        class Person(TestModel):
            pass
        class Pet(TestModel):
            owner = ForeignKeyField(Person, backref='!')

        self.assertEqual(Pet.owner.backref, '!')
        self.assertRaises(AttributeError, lambda: Person.pet_set)

    def test_on_delete_behavior(self):
        users = []
        for username in ('u1', 'u2', 'u3'):
            user = U2.create(username=username)
            users.append(user)
            for i in range(3):
                T2.create(user=user, content='%s-%s' % (username, i))

        cnt = T2.delete().where(T2.user == users[0]).execute()
        self.assertEqual(cnt, 3)
        self.assertEqual(T2.select().count(), 6)

        u2 = U2.get(username='u2')
        u2.delete_instance()
        self.assertEqual(T2.select().count(), 3)

        self.assertEqual(T2.select().where(T2.user == users[0]).count(), 0)
        self.assertEqual(T2.select().where(T2.user == users[1]).count(), 0)
        self.assertEqual(T2.select().where(T2.user == users[2]).count(), 3)

        T2.create(content='emu', user=u2)
        self.assertEqual(T2.get(content='emu').user, None)


class EfModel(TestModel):
    i = IntegerField(enforce_type=True, default=0)
    f = FloatField(enforce_type=True, default=0.0)
    c = CharField(enforce_type=True, default='')
    b = BlobField(enforce_type=True, default=b'')
    dt = DateTimeField(enforce_type=True, default=datetime.datetime.now)
    j1 = JSONField(enforce_type=True, default=JSONField.list_default)
    j2 = JSONField(enforce_type=True, default=JSONField.dict_default)

class TestEnforcedField(ModelTestCase):
    requires = [EfModel]

    def test_enforce_type(self):
        with self.assertRaisesCtx(ValueError):
            EfModel.create(i='10')
        with self.assertRaisesCtx(ValueError):
            EfModel.create(f='10.0')
        with self.assertRaisesCtx(ValueError):
            EfModel.create(c=1)
        with self.assertRaisesCtx(ValueError):
            EfModel.create(b='str')
        with self.assertRaisesCtx(ValueError):
            EfModel.create(dt='str')
        with self.assertRaisesCtx(ValueError):
            EfModel.create(j1=EfModel)
        with self.assertRaisesCtx(ValueError):
            EfModel.create(j2=EfModel)

class DtModel(TestModel):
    dt = DateTimeField(enforce_type=True, default=datetime.datetime.now)
    
class TestDateTimeField(ModelTestCase):
    requires = [DtModel]

    def test_date_time(self):
        now = datetime.datetime.now().replace(microsecond=0)
        dt = DtModel.create(dt=now)
        self.assertEqual(DtModel.get(dt=now).dt, now)
