"""Order-line and visit facts for reproducible, correctly deduplicated metrics.

Amounts are non-negative integer cents. An order discount is allocated across
lines with largest remainder, with line_id as a deterministic tie-breaker.
These functions do not write or publish datasets.
"""
from collections import defaultdict
from datetime import date, timedelta
import random


def _text(value, name):
    if not isinstance(value, str) or not value.strip() or value != value.strip():
        raise ValueError(f"{name} must be non-empty text without outer whitespace")
    return value


def _day(value):
    try:
        parsed = date.fromisoformat(value)
    except (TypeError, ValueError):
        raise ValueError("date must be YYYY-MM-DD") from None
    if value != parsed.isoformat():
        raise ValueError("date must be YYYY-MM-DD")
    return value


def _cents(value, name):
    if type(value) is not int or value < 0:
        raise ValueError(f"{name} must be non-negative integer cents")
    return value


def normalize_details(visits, lines):
    """Validate visits and order lines, and return allocated, independent copies.

    order_id is globally unique in a dataset; every order references a visitor
    that appears in the visit facts. Categories can overlap across an order.
    """
    if not isinstance(visits, list) or not isinstance(lines, list):
        raise ValueError("visits and lines must be lists")
    visit_ids, visitors, clean_visits = set(), set(), []
    for row in visits:
        if not isinstance(row, dict) or set(row) != {'event_id', 'visitor_id', 'date', 'channel', 'region'}:
            raise ValueError("invalid visit fields")
        clean = {k: _text(row[k], k) for k in ('event_id', 'visitor_id', 'channel', 'region')}
        clean['date'] = _day(row['date'])
        if clean['event_id'] in visit_ids:
            raise ValueError("duplicate visit event_id")
        visit_ids.add(clean['event_id'])
        visitors.add(clean['visitor_id'])
        clean_visits.append(clean)

    orders, line_ids = defaultdict(list), set()
    for row in lines:
        required = {'order_id', 'line_id', 'visitor_id', 'date', 'category', 'gross_cents', 'order_discount_cents'}
        if not isinstance(row, dict) or set(row) != required:
            raise ValueError("invalid order line fields")
        clean = {k: _text(row[k], k) for k in ('order_id', 'line_id', 'visitor_id', 'category')}
        clean['date'] = _day(row['date'])
        for key in ('gross_cents', 'order_discount_cents'):
            clean[key] = _cents(row[key], key)
        key = (clean['order_id'], clean['line_id'])
        if key in line_ids:
            raise ValueError("duplicate order line key")
        if clean['visitor_id'] not in visitors:
            raise ValueError("order visitor missing from visits")
        line_ids.add(key)
        orders[clean['order_id']].append(clean)

    clean_lines = []
    for order_id, group in sorted(orders.items()):
        if len({(r['visitor_id'], r['date'], r['order_discount_cents']) for r in group}) != 1:
            raise ValueError(f"inconsistent order fields: {order_id}")
        gross = sum(r['gross_cents'] for r in group)
        discount = group[0]['order_discount_cents']
        if discount > gross:
            raise ValueError("discount exceeds order gross")
        # No allocation is possible or needed when the entire order is zero.
        allocations = {r['line_id']: (discount * r['gross_cents'] // gross if gross else 0) for r in group}
        remaining = discount - sum(allocations.values())
        ranked = sorted(group, key=lambda r: (-(discount * r['gross_cents'] % gross) if gross else 0, r['line_id']))
        for row in ranked[:remaining]:
            allocations[row['line_id']] += 1
        for row in group:
            allocated = allocations[row['line_id']]
            clean_lines.append({**row, 'allocated_discount_cents': allocated, 'net_cents': row['gross_cents'] - allocated})
    clean_visits.sort(key=lambda r: r['event_id'])
    clean_lines.sort(key=lambda r: (r['order_id'], r['line_id']))
    return clean_visits, clean_lines


def summarize(visits, lines, start, end):
    """Return period UV and distinct orders; category order counts may overlap."""
    start, end = _day(start), _day(end)
    if start > end:
        raise ValueError("start date must not follow end date")
    visits, lines = normalize_details(visits, lines)
    visits = [r for r in visits if start <= r['date'] <= end]
    lines = [r for r in lines if start <= r['date'] <= end]
    categories = defaultdict(lambda: {'orders': set(), 'net_cents': 0})
    for row in lines:
        categories[row['category']]['orders'].add(row['order_id'])
        categories[row['category']]['net_cents'] += row['net_cents']
    return {
        'visits': len(visits),
        'unique_visitors': len({r['visitor_id'] for r in visits}),
        'orders': len({r['order_id'] for r in lines}),
        'gmv_cents': sum(r['net_cents'] for r in lines),
        'categories': {k: {'orders': len(v['orders']), 'gmv_cents': v['net_cents']}
                       for k, v in sorted(categories.items())},
        'category_orders_additive': False,
    }


def generate_ecommerce_details(seed=41):
    """Generate a reproducible 90-day synthetic order-line/visit dataset.

    Explicitly a synthetic fixture, not a representation of real customers.
    The late-period drop in paid-channel order propensity is injected; no
    statistical or causal conclusion follows solely from the generator.
    """
    if type(seed) is not int:
        raise ValueError("seed must be an integer")
    rng = random.Random(seed)
    visits, lines = [], []
    channels = ('付费投放', '自然流量', '直播', '联盟')
    regions = ('华东', '华北', '华南')
    categories = ('服饰', '食品', '家居', '数码')
    for day in range(90):
        current_date = (date(2026, 8, 1) + timedelta(days=day)).isoformat()
        for offset in range(128):
            # Visitors return across days, so period UV cannot be summed daily.
            visitor = f'synthetic-u{offset:04d}'
            channel = channels[offset % len(channels)]
            region = regions[(offset // len(channels)) % len(regions)]
            event_id = f'synthetic-e{day:03d}-{offset:03d}'
            visits.append(dict(event_id=event_id, visitor_id=visitor, date=current_date,
                               channel=channel, region=region))
            probability = .14 if day >= 60 and channel == '付费投放' else .28
            if rng.random() >= probability:
                continue
            order_id = f'synthetic-o{day:03d}-{offset:03d}'
            line_count = 2 if rng.random() < .2 else 1
            gross = [rng.randrange(30, 201) * 100 for _ in range(line_count)]
            discount = min(sum(gross), rng.randrange(0, 501))
            first_category = rng.randrange(len(categories))
            for index, amount in enumerate(gross):
                lines.append(dict(order_id=order_id, line_id=f'{index:02d}', visitor_id=visitor,
                                  date=current_date, category=categories[(first_category + index) % len(categories)],
                                  gross_cents=amount, order_discount_cents=discount))
    return visits, lines
