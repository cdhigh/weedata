#!/usr/bin/env python3
# -*- coding:utf-8 -*-
from weedata import *
from test_base import ModelTestCase, TestModel

class T1(TestModel):
    pk = IntegerField()
    value = IntegerField()

class T2(TestModel):
    pk = IntegerField()
    value = IntegerField()

class T3(TestModel):
    pk = IntegerField()
    value = IntegerField()

class T4(TestModel):
    pk1 = IntegerField()
    pk2 = IntegerField()
    value = IntegerField()
    
class T5(TestModel):
    val = IntegerField(null=True)

class TestSaveNoData(ModelTestCase):
    requires = [T5]

    def test_save_no_data(self):
        t5 = T5.create()
        t5.val = 3
        t5.save()

        t5_db = T5.get(T5.id == t5.id)
        self.assertEqual(t5_db.val, 3)

        t5.val = None
        t5.save()

        t5_db = T5.get(T5.id == t5.id)
        self.assertTrue(t5_db.val is None)

    def test_save_no_data2(self):
        t5 = T5.create()

        t5_db = T5.get(T5.id == t5.id)
        t5_db.save()

        t5_db = T5.get(T5.id == t5.id)
        self.assertTrue(t5_db.val is None)
        