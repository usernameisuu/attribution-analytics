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
        self.assertIn('事件结束距现期开始 3 天', matches[0]['match_basis'])
        self.assertIn('事件未限定该维度', matches[0]['match_basis'])
        self.assertIn('事件与现期时间重叠', matches[1]['match_basis'])
        self.assertIn('事件范围包含该值', matches[1]['match_basis'])
        self.assertIn('事件开始距现期结束 3 天', matches[2]['match_basis'])
        self.assertIn('未筛选的维度未核验重合', matches[2]['match_basis'])

    def test_multiday_overlap_and_bad_scope(self):
        spanning = {**event('long', '2026-09-01'), 'end': '2026-10-01'}
        result = match_events([spanning], 'ecommerce', '2026-10-04', '2026-10-04', {})
        self.assertEqual(len(result), 1)
        self.assertIn('未核验维度重合', result[0]['match_basis'])
        with self.assertRaises(ValueError):
            match_events([event('x', '2026-10-01', scope={'unknown': ['x']})], 'ecommerce', '2026-10-01', '2026-10-02', {})

    def test_old_archived_event_without_match_basis_remains_renderable(self):
        from app.modules.analysis.report import event_section
        old = {**event('old', '2026-10-01'), 'evidence_status':'候选关联，尚不能证明因果'}
        archived = {'mode':'archived', 'status':'available', 'checked_at':'2026-10-01T00:00:00Z',
                    'notice':'时间关联不证明因果', 'current_window':['2026-10-01','2026-10-02'],
                    'filters':{}, 'events':[old]}
        self.assertIn('旧归档未记录匹配依据', '\n'.join(event_section(archived)))
