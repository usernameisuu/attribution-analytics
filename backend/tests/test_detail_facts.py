import copy
import unittest
from app.domain.detail_facts import generate_ecommerce_details, normalize_details, summarize


class DetailFactsTests(unittest.TestCase):
    def setUp(self):
        self.visits = [dict(event_id='e1', visitor_id='u1', date='2026-10-01', channel='直播', region='华东'),
                       dict(event_id='e2', visitor_id='u1', date='2026-10-02', channel='自然', region='华东')]
        self.lines = [dict(order_id='o1', line_id='l1', visitor_id='u1', date='2026-10-02', category='食品', gross_cents=100, order_discount_cents=1),
                      dict(order_id='o1', line_id='l2', visitor_id='u1', date='2026-10-02', category='服饰', gross_cents=100, order_discount_cents=1)]

    def test_deduplicate_and_allocate_discount_without_join_inflation(self):
        original = copy.deepcopy((self.visits, self.lines))
        result = summarize(self.visits, self.lines, '2026-10-01', '2026-10-02')
        self.assertEqual((result['visits'], result['unique_visitors'], result['orders'], result['gmv_cents']), (2, 1, 1, 199))
        self.assertEqual(sum(item['gmv_cents'] for item in result['categories'].values()), 199)
        self.assertEqual(sum(item['orders'] for item in result['categories'].values()), 2)
        self.assertFalse(result['category_orders_additive'])
        self.assertEqual((self.visits, self.lines), original)
        _, lines = normalize_details(list(reversed(self.visits)), list(reversed(self.lines)))
        self.assertEqual([r['allocated_discount_cents'] for r in lines], [1, 0])

    def test_period_is_filtered_before_distinct(self):
        result = summarize(self.visits, self.lines, '2026-10-01', '2026-10-01')
        self.assertEqual((result['visits'], result['unique_visitors'], result['orders'], result['gmv_cents']), (1, 1, 0, 0))

    def test_invalid_or_inconsistent_data_is_rejected(self):
        cases = [(self.visits + self.visits[:1], self.lines),
                 (self.visits, self.lines + self.lines[:1]),
                 (self.visits, [{**self.lines[0], 'visitor_id': 'unknown'}]),
                 (self.visits, [self.lines[0], {**self.lines[1], 'order_discount_cents': 2}]),
                 (self.visits, [{**self.lines[0], 'order_discount_cents': 101}]),
                 (self.visits, [{**self.lines[0], 'gross_cents': True}])]
        for visits, lines in cases:
            with self.subTest(lines=lines), self.assertRaises(ValueError):
                normalize_details(visits, lines)

    def test_generated_data_is_reproducible_and_covers_dimensions(self):
        visits, lines = generate_ecommerce_details()
        self.assertEqual((visits, lines), generate_ecommerce_details())
        self.assertGreaterEqual(len(visits), 10000)
        self.assertEqual(len({r['date'] for r in visits}), 90)
        self.assertEqual(len({r['channel'] for r in visits}), 4)
        self.assertEqual(len({r['region'] for r in visits}), 3)
        self.assertEqual(len({r['category'] for r in lines}), 4)
        totals = summarize(visits, lines, '2026-08-01', '2026-10-29')
        self.assertEqual(totals['visits'], len(visits))
        self.assertEqual(totals['unique_visitors'], 128)
        self.assertEqual(totals['orders'], len({r['order_id'] for r in lines}))
        discounts = {r['order_id']: r['order_discount_cents'] for r in lines}
        self.assertEqual(totals['gmv_cents'], sum(r['gross_cents'] for r in lines) - sum(discounts.values()))
