#!/usr/bin/env python3
# -*- coding:utf-8 -*-
#Regression tests for boundary-condition and bug fixes
import datetime
from test_base import *
from weedata.queries import _FieldProxy, UpdateQueryBuilder

class FixUser(TestModel):
    name = CharField(index=True)
    age = IntegerField()

class FixTweet(TestModel):
    author = ForeignKeyField(FixUser, backref='tweets')
    content = CharField()

class TestFilterObjects(BaseTestCase):
    def test_filter_not_mutated_by_and(self):
        f1 = (FixUser.name == 'a') & (FixUser.age == 1)
        children_before = len(f1.children)
        f2 = f1 & (FixUser.name == 'b')
        self.assertEqual(len(f1.children), children_before)
        self.assertIsNot(f1, f2)
        self.assertEqual(len(f2.children), 3)

    def test_filter_not_mutated_by_invert(self):
        base = (FixUser.name == 'a')
        neg = ~base
        self.assertEqual(base.bit_op, None)
        self.assertEqual(base.item, 'name')
        self.assertEqual(neg.bit_op, Filter.NOR)
        self.assertEqual(len(neg.children), 1)

    def test_between_is_inclusive(self):
        f = FixUser.age.between(1, 3)
        self.assertEqual(len(f.children), 2)
        self.assertEqual(f.children[0].op, Filter.GE)
        self.assertEqual(f.children[1].op, Filter.LE)

    def test_between_swapped_bounds(self):
        f = FixUser.age.between(3, 1)
        self.assertEqual(f.children[0].value, 1)
        self.assertEqual(f.children[1].value, 3)

    def test_duplicate_top_or_groups_are_anded(self):
        q = FixUser.select().where((FixUser.name == 'a') | (FixUser.name == 'b'),
                                   (FixUser.name == 'c') | (FixUser.name == 'd'))
        merged = q.filters()
        self.assertIn(Filter.AND, merged)
        self.assertEqual(len(merged[Filter.AND]), 2)
        for entry in merged[Filter.AND]:
            self.assertIn(Filter.OR, entry)

    def test_single_top_or_unchanged(self):
        q = FixUser.select().where((FixUser.name == 'a') | (FixUser.name == 'b'))
        self.assertIn(Filter.OR, q.filters())

    def test_pk_filter_accepts_int(self):
        #int id builds a native key filter, or mongo rejects it with a clear ValueError
        try:
            flt = FixUser.id == 5
            self.assertEqual(flt.item, database.db_id_name())
        except ValueError:
            pass

    def test_pk_filter_accepts_id_list(self):
        try:
            flt = FixUser.id.in_([1, 2])
            self.assertEqual(flt.op, Filter.IN)
            self.assertIsInstance(flt.value, list)
        except ValueError:
            pass #mongodb ids are hex strings, int ids are rejected with a clear error

    def test_safe_eval_sandbox(self):
        proxy = _FieldProxy(FixUser(name='x', age=1), FixUser._meta.fields)
        self.assertEqual(UpdateQueryBuilder.safe_eval('(e.age + 1)', {'e': proxy}), 2)
        with self.assertRaisesCtx(NameError):
            UpdateQueryBuilder.safe_eval('(e._meta)', {'e': proxy})
        with self.assertRaisesCtx(NameError):
            UpdateQueryBuilder.safe_eval('(e.__class__)', {'e': proxy})

class TestDataQueries(ModelTestCase):
    database = database
    requires = [FixUser, FixTweet]

    def setUp(self):
        super().setUp()
        self.ids = list(FixUser.insert_many([
            {'name': 'alpha', 'age': 1},
            {'name': 'beta', 'age': 2},
            {'name': 'gamma', 'age': 3},
        ]).execute())
        alpha = FixUser.get_by_id(self.ids[0])
        self.t_ids = [
            FixTweet.insert({'author': alpha, 'content': 'hello'}).execute(),
            FixTweet.insert({'author': alpha.id, 'content': 'world'}).execute(),
        ]

    def test_between_inclusive(self):
        ages = sorted(u.age for u in FixUser.select().where(FixUser.age.between(1, 3)))
        self.assertEqual(ages, [1, 2, 3])

    def test_get_by_id_none(self):
        self.assertIsNone(FixUser.get_by_id(None))
        self.assertIsNone(FixUser.get_by_key(None))

    def test_startswith_unicode(self):
        FixUser.create(name='abc中文', age=9)
        names = [u.name for u in FixUser.select().where(FixUser.name.startswith('abc'))]
        self.assertIn('abc中文', names)

    def test_dicts_limit_forwarded(self):
        self.assertEqual(len(list(FixUser.select().dicts(limit=2))), 2)

    def test_double_save_no_duplicate(self):
        u = FixUser.create(name='saver', age=10)
        u.name = 'saver2'
        u.save()
        self.assertEqual(FixUser.select().where(FixUser.name == 'saver').count(), 0)
        self.assertEqual(FixUser.select().where(FixUser.name == 'saver2').count(), 1)

    def test_delete_instance_after_create(self):
        u = FixUser.create(name='doomed', age=11)
        self.assertEqual(u.delete_instance(), 1)
        self.assertIsNone(FixUser.get_by_id(u.id))

    def test_fk_reassignment_refreshes_cache(self):
        beta = FixUser.get_by_id(self.ids[1])
        t = FixTweet.select().where(FixTweet.content == 'hello').first()
        self.assertEqual(t.author.name, 'alpha')
        t.author = beta.id
        self.assertEqual(t.author.name, 'beta')

    def test_fk_query_by_instance(self):
        alpha = FixUser.get_by_id(self.ids[0])
        tweets = list(FixTweet.select().where(FixTweet.author == alpha))
        self.assertEqual(len(tweets), 2)

    def test_fk_query_by_id_list(self):
        tweets = list(FixTweet.select().where(FixTweet.author.in_(self.ids[:2])))
        self.assertEqual(len(tweets), 2)

    def test_unknown_kwarg_rejected(self):
        with self.assertRaisesCtx(ValueError):
            FixUser(nmae='typo')

    def test_update_unknown_field_rejected(self):
        with self.assertRaisesCtx(ValueError):
            FixUser.update(nmae='typo').execute()

    def test_replace_unknown_field_rejected(self):
        with self.assertRaisesCtx(ValueError):
            FixUser.replace(name='alpha', nmae='typo').execute()

    def test_in_empty_matches_nothing(self):
        self.assertEqual(FixUser.select().where(FixUser.name.in_([])).count(), 0)

    def test_scan_with_none_field(self):
        FixUser.create(name='noage') #age left as None
        users = list(FixUser.select().where(FixUser.age > 0))
        self.assertEqual([u.name for u in users], ['alpha', 'beta', 'gamma'])

    def test_order_by_with_none_field(self):
        FixUser.create(name='noage1')
        FixUser.create(name='noage2')
        users = list(FixUser.select().order_by(FixUser.age))
        self.assertEqual(len(users), 5) #must not crash
        self.assertEqual([u.name for u in users][-2:], ['noage1', 'noage2'])

    def test_update_expr_quote_in_string(self):
        FixUser.update({FixUser.name: 'say "hi" ' + FixUser.name}).where(FixUser.name == 'alpha').execute()
        self.assertEqual(FixUser.get(name='say "hi" alpha').name, 'say "hi" alpha')

    def test_json_default_isolated(self):
        class JsModel(TestModel):
            data = JSONField(default={})
        JsModel.bind(self.database)
        j1 = JsModel()
        j2 = JsModel()
        j1.data['leak'] = 1
        self.assertEqual(j2.data, {})

    def test_model_base_has_no_primary_key(self):
        import weedata
        self.assertFalse(hasattr(weedata.Model, 'id'))

    def test_int_id_get_never_returns_wrong_record(self):
        #an int id either returns None or raises a clear error, never a random record
        try:
            user = FixUser.get(5)
            self.assertIsNone(user)
        except ValueError:
            pass

    def test_pk_comparison_with_none(self):
        with self.assertRaisesCtx(ValueError):
            FixUser.id == None #pylint: disable=comparison-with-callable
