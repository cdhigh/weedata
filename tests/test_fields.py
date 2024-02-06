#!/usr/bin/env python3
# -*- coding:utf-8 -*-
import calendar, datetime, time, uuid
from weedata import *
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

        vals = [(i.value, i.value_null)
                for i in IntModel.select().order_by(IntModel.value)]
        self.assertEqual(vals, [
            (1, None),
            (2, 20)])

class FloatModel(TestModel):
    value = FloatField()
    value_null = FloatField(null=True)

class TestFloatField(ModelTestCase):
    requires = [FloatModel]

    def test_float_field(self):
        f1 = FloatModel.create(value=1.23)
        f2 = FloatModel.create(value=3.14, value_null=0.12)

        query = FloatModel.select().order_by(FloatModel.id)
        self.assertEqual([(f.value, f.value_null) for f in query],
                         [(1.23, None), (3.14, 0.12)])

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
        self.assertEqual(vals, [
            ('f', False),
            ('n', None),
            ('t', True)])


class DateModel(TestModel):
    date = DateField(null=True)
    time = TimeField(null=True)
    date_time = DateTimeField(null=True)

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
        return ','.join(value) if value else ''

    def python_value(self, value):
        return value.split(',') if value else []

class Todo(TestModel):
    content = TextField()
    tags = ListField()

class TestCustomField(ModelTestCase):
    requires = [Todo]
    def test_custom_field(self):
        t1 = Todo.create(content='t1', tags=['t1-a', 't1-b'])
        t2 = Todo.create(content='t2', tags=[])

        t1_db = Todo.get(Todo.id == t1.id)
        self.assertEqual(t1_db.tags, ['t1-a', 't1-b'])

        t2_db = Todo.get(Todo.id == t2.id)
        self.assertEqual(t2_db.tags, [])

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
        self.assertEqual(sb_db.text_field, b'b1')
        self.assertEqual(sb_db.char_field, b'b1')

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
        