import unittest
from app.domain.event_matching import match_events


def event(identifier, day, line='ecommerce', scope=None):
    return dict(id=identifier, business_line=line, title='促销活动', start=day, end=day,
                scope=scope or {}, source='模拟活动日历')


class EventMatchingTests(unittest.TestCase):
    def test_three_day_boundary_and_scope(self):
        events = [event('a', '2026-09-28'), event('b', '2026-09-27'),
                  event('c', '2026-10-05'), event('d', '2026-10-06'),
                  event('wrong-line', '2026-10-01', 'consumer'),
                  event('wrong-region', '2026-10-01', scope={'region': ['华北']}),
                  event('region', '2026-10-01', scope={'region': ['华东']})]
        matches = match_events(events, 'ecommerce', '2026-10-01', '2026-10-02', {'region': '华东'})
        self.assertEqual([e['id'] for e in matches], ['a', 'region', 'c'])
        self.assertTrue(all('尚不能证明因果' in e['evidence_status'] for e in matches))

    def test_multiday_overlap_and_bad_scope(self):
        spanning = {**event('long', '2026-09-01'), 'end': '2026-10-01'}
        self.assertEqual(len(match_events([spanning], 'ecommerce', '2026-10-04', '2026-10-04', {})), 1)
        with self.assertRaises(ValueError):
            match_events([event('x', '2026-10-01', scope={'unknown': ['x']})], 'ecommerce', '2026-10-01', '2026-10-02', {})
