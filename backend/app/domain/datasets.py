"""Versioned, normalized daily facts. Counts are visits, never implied unique users."""
import csv
import hashlib
import io
import json
import random
from datetime import date, timedelta
from decimal import Decimal as D
from itertools import product
from .attribution import number, validate_input_precision

DIMENSIONS = ("channel", "region", "category", "segment")
MEASURES = ("visitors", "orders", "revenue", "material", "logistics", "commission", "other", "tax", "spend")
FIELDS = ("date", *DIMENSIONS, *MEASURES)


def _unique_json_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError('JSON 对象包含重复字段，请检查导入数据')
        result[key] = value
    return result


def normalize(rows: list[dict]) -> tuple[list[dict], str]:
    if not isinstance(rows, list) or not 1 <= len(rows) <= 20000:
        raise ValueError("数据需包含 1～20000 行")
    result, seen, coverage = [], set(), {}
    for index, row in enumerate(rows, 1):
        if not isinstance(row, dict) or set(row) != set(FIELDS):
            raise ValueError(f"第 {index} 行字段不完整或包含未知字段")
        day = date.fromisoformat(str(row["date"])).isoformat()
        if any(not isinstance(row[k],str) for k in DIMENSIONS):
            raise ValueError(f'第 {index} 行维度必须是文本')
        dimensions = tuple(row[k].strip() for k in DIMENSIONS)
        if any(not v or len(v) > 60 or any(ord(ch) < 32 for ch in v) for v in dimensions):
            raise ValueError(f"第 {index} 行维度为空、过长或含控制字符")
        key = (day, *dimensions)
        if key in seen:
            raise ValueError(f"第 {index} 行存在重复业务键")
        seen.add(key)
        values = {k: number(row[k]) for k in MEASURES}
        for value in values.values():
            validate_input_precision(value)
        if any(v < 0 or v > D('1e12') for v in values.values()):
            raise ValueError(f"第 {index} 行数值越界")
        if any(values[k] != values[k].to_integral_value() for k in ('visitors', 'orders')):
            raise ValueError("访问和订单计数必须为整数")
        if values['orders'] and not values['visitors'] or values['revenue'] and not values['orders']:
            raise ValueError("有订单必须有访问，有营收必须有订单")
        result.append(dict(date=day, **dict(zip(DIMENSIONS, dimensions)), **{k: str(v) for k, v in values.items()}))
        coverage.setdefault(day, set()).add(dimensions)
    days = sorted(coverage)
    if (date.fromisoformat(days[-1])-date.fromisoformat(days[0])).days + 1 != len(days):
        raise ValueError("数据覆盖日期有缺口，请显式提供无业务日期的零记录")
    if any(keys != coverage[days[0]] for keys in coverage.values()):
        raise ValueError("日期间维度覆盖不一致；新增/退出业务请提供明确的零记录")
    result.sort(key=lambda r: tuple(r[k] for k in ('date', *DIMENSIONS)))
    digest = hashlib.sha256(json.dumps(result, ensure_ascii=False, sort_keys=True).encode()).hexdigest()
    return result, digest


def parse_upload(content: str, format: str) -> tuple[list[dict], str]:
    if len(content.encode()) > 10_000_000:
        raise ValueError("导入内容不能超过 10 MB")
    if format == 'json':
        rows = json.loads(content, parse_float=str, parse_int=str, object_pairs_hook=_unique_json_object)
    elif format == 'csv':
        reader = csv.DictReader(io.StringIO(content.lstrip('\ufeff')))
        if not reader.fieldnames or len(reader.fieldnames)!=len(set(reader.fieldnames)):
            raise ValueError('CSV 表头重复或缺失')
        rows = list(reader)
    else:
        raise ValueError("仅支持 CSV 或 JSON")
    return normalize(rows)


def generate(scenario: str, seed: int = 41) -> list[dict]:
    if scenario not in ('ecommerce', 'consumer'):
        raise ValueError("未知业务线")
    rng, rows = random.Random(seed), []
    for day in range(90):
        for channel, region, category, segment in product(('付费投放','自然流量','直播','联盟'), ('华东','华北','华南'), ('服饰','食品','家居','数码'), ('新客','老客')):
            spend = D(rng.randrange(500, 1800))
            visits = int(180 + float(spend)*0.55 + rng.uniform(-50,50))
            rate = .048 * (0.58 if day >= 60 and channel == '付费投放' else 1)
            orders = max(1, round(visits*rate+rng.uniform(-3,3)))
            basket = D('180' if day >= 60 and category == '服饰' else '200')
            revenue = basket*orders
            material = revenue*D('.58' if scenario == 'consumer' and day >= 60 else '.50')
            rows.append(dict(date=(date(2026,8,1)+timedelta(days=day)).isoformat(), channel=channel, region=region, category=category, segment=segment,
                             visitors=str(visits), orders=str(orders), revenue=str(revenue), material=str(material), logistics=str(revenue*D('.1')),
                             commission=str(revenue*D('.05')), other=str(revenue*D('.1')), tax='0', spend=str(spend)))
    return normalize(rows)[0]
