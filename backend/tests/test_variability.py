from decimal import Decimal

from app.domain.datasets import normalize
from app.domain.variability import baseline_variability


def test_baseline_daily_variability_and_zero_denominator_days():
    triples = [(100,5,1000),(0,0,0),(200,10,3000),(100,5,1000),(100,5,1000),(100,5,1000)]
    rows = [dict(date=f'2026-10-0{i}', channel='直播', region='华东', category='食品', segment='新客',
                 visitors=str(visits), orders=str(orders), revenue=str(revenue), material='0', logistics='0',
                 commission='0', other='0', tax='0', spend='0')
            for i,(visits,orders,revenue) in enumerate(triples, 1)]
    rows,_ = normalize(rows)
    scope = {'baseline':['2026-10-01','2026-10-03'], 'current':['2026-10-04','2026-10-06'],
             'filters':{'channel':'直播'}, 'group_by':'region'}
    result = baseline_variability('ecommerce', rows, scope)
    by_key = {item['key']:item for item in result['factors']}
    assert result['days'] == 3 and result['missing_dates'] == 0
    assert Decimal(by_key['visitors']['mean']) == 100
    assert Decimal(by_key['visitors']['stddev']) == 100
    assert Decimal(by_key['visitors']['relative_percent']) == 100
    assert by_key['basket']['n'] == 2 and by_key['basket']['missing_days'] == 1
    assert Decimal(by_key['basket']['mean']) == 250
    assert by_key['conversion']['n'] == 2 and Decimal(by_key['conversion']['stddev']) == 0
    assert '不是预测区间' in result['notice']


def test_one_day_has_no_sample_deviation():
    rows = [dict(date=f'2026-10-0{i}', channel='直播', region='华东', category='食品', segment='新客',
                 visitors='1', orders='1', revenue='100', material='0', logistics='0',
                 commission='0', other='0', tax='0', spend='0') for i in (1,2)]
    rows,_ = normalize(rows)
    scope = {'baseline':['2026-10-01','2026-10-01'], 'current':['2026-10-02','2026-10-02'],
             'filters':{}, 'group_by':'channel'}
    result = baseline_variability('consumer', rows, scope)
    assert result['metric']['stddev'] is None
    assert all(item['relative_percent'] is None for item in result['factors'])
