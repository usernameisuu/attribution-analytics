"""Match supplied, already-authorized business events as candidates, not causes."""
from datetime import date

DIMENSIONS = {'channel', 'region', 'category', 'segment'}
LABELS = {'channel':'渠道', 'region':'区域', 'category':'品类', 'segment':'客群'}


def _day(value):
    try:
        day = date.fromisoformat(value)
    except (TypeError, ValueError):
        raise ValueError('invalid date') from None
    if day.isoformat() != value:
        raise ValueError('date must use YYYY-MM-DD')
    return day


def _scope(value):
    if not isinstance(value, dict) or set(value) - DIMENSIONS:
        raise ValueError('invalid event scope')
    for key, values in value.items():
        if (not isinstance(values, list) or not 1 <= len(values) <= 100 or
                any(not isinstance(item, str) or not item.strip() or item != item.strip() or len(item) > 60 for item in values)):
            raise ValueError(f'invalid values for {key}')
    return value


def match_events(events, business_line, start, end, filters):
    """Return date/scope matches from events authorized by the caller.

    An absent event dimension means all values in that dimension. Authorization
    is deliberately not inferred here: the caller must pre-filter event access.
    """
    start, end = _day(start), _day(end)
    if start > end:
        raise ValueError('invalid analysis window')
    if not isinstance(business_line, str) or not business_line.strip():
        raise ValueError('invalid business line')
    if not isinstance(filters, dict) or set(filters) - DIMENSIONS:
        raise ValueError('invalid filters')
    if any(not isinstance(value, str) or not value.strip() for value in filters.values()):
        raise ValueError('invalid filter value')
    if not isinstance(events, list):
        raise ValueError('events must be a list')
    matches = []
    for event in events:
        if not isinstance(event, dict) or set(event) != {'id', 'business_line', 'title', 'start', 'end', 'scope', 'source'}:
            raise ValueError('invalid event')
        if any(not isinstance(event[k], str) or not event[k].strip() for k in ('id', 'business_line', 'title', 'source')):
            raise ValueError('event identity, title, line and source are required')
        event_start, event_end = _day(event['start']), _day(event['end'])
        scope = _scope(event['scope'])
        if event_start > event_end:
            raise ValueError('invalid event window')
        if event['business_line'] != business_line:
            continue
        # Difference comparisons avoid overflowing date.min/max when expanding.
        if (start - event_end).days > 3 or (event_start - end).days > 3:
            continue
        if any(key in scope and value not in scope[key] for key, value in filters.items()):
            continue
        if event_end < start:
            temporal = f'事件结束距现期开始 {(start-event_end).days} 天'
        elif event_start > end:
            temporal = f'事件开始距现期结束 {(event_start-end).days} 天'
        else:
            temporal = '事件与现期时间重叠'
        if filters:
            dimensions = '；'.join(f"{LABELS[key]}={value}（{'事件范围包含该值' if key in scope else '事件未限定该维度'}）"
                                  for key,value in sorted(filters.items()))
            dimensions += '；未筛选的维度未核验重合'
        else:
            dimensions = '分析未按维度筛选，未核验维度重合'
        matches.append({**event, 'scope': {key: list(values) for key, values in scope.items()},
                        'match_basis': f'{temporal}；{dimensions}。',
                        'evidence_status': '候选关联，尚不能证明因果'})
    return sorted(matches, key=lambda item: (item['start'], item['id']))
