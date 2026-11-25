"""Frozen PRD arithmetic fixtures. These are not statistical or causal evidence."""
from decimal import Decimal as D
from .attribution import additive, multiplicative, number, shapley
from .metric_catalog import VERSION as METRIC_DEFINITION_VERSION

SCENARIOS = {
    "ecommerce": {
        "name": "电商 GMV 下滑", "metric": "GMV", "domain": "ecommerce",
        "baseline": {"visitors": "100000", "conversion": "0.05", "basket": "200"},
        "current": {"visitors": "120000", "conversion": "0.03", "basket": "180"},
        "labels": {"visitors": "访问次数", "conversion": "订单转化因子", "basket": "客单价"},
    },
    "consumer": {
        "name": "快消品利润异动", "metric": "净利润", "domain": "consumer",
        "baseline": {"revenue": "1000000", "material": "500000", "logistics": "100000", "commission": "50000", "other": "100000", "tax": "0"},
        "current": {"revenue": "950000", "material": "540000", "logistics": "110000", "commission": "57000", "other": "100000", "tax": "0"},
        "labels": {"revenue": "营收", "material": "原材料成本", "logistics": "物流履约", "commission": "渠道佣金", "other": "其他成本", "tax": "财务与税费"},
    },
}


def calculate(key: str) -> dict:
    if key not in SCENARIOS:
        raise ValueError("未知场景")
    scenario = SCENARIOS[key]
    if key == "ecommerce":
        result = multiplicative(scenario["baseline"], scenario["current"], scenario["labels"])
    else:
        result = additive(scenario["baseline"], scenario["current"],
                          {k: 1 if k == "revenue" else -1 for k in scenario["baseline"]}, scenario["labels"])
    response = dict(scenario_id=key, title=scenario["name"], metric=scenario["metric"],
                    dataset_version="prd-fixture-v1", algorithm_version="decimal-v4", metric_definition_version=METRIC_DEFINITION_VERSION,
                    data_kind="固定模拟样例", breakdown=result.as_dict(),
                    evidence_status="仅完成数学分解，尚未执行统计检验",
                    limitations=["固定汇总样例不具备独立统计观测，不能据此输出因果结论。"])
    if key == "consumer":
        def margin(values):
            return 100*(values["revenue"]-sum(v for k,v in values.items() if k != "revenue"))/values["revenue"]
        response["margin_breakdown"] = shapley(scenario["baseline"], scenario["current"], margin, scenario["labels"], "百分点").as_dict()
    return response


def simulate(key: str, changes: dict) -> dict:
    if key not in SCENARIOS:
        raise ValueError("未知场景")
    scenario = SCENARIOS[key]
    if not changes or set(changes) - set(scenario["current"]):
        raise ValueError("必须提供有效驱动因子")
    values = {k: number(v) for k,v in scenario["current"].items()}
    for k,v in changes.items():
        value = number(v)
        if value < 0 or value > D("1e12"):
            raise ValueError("模拟参数超出允许范围")
        if k == "conversion" and value > 1:
            raise ValueError("样例转化率必须在 0 到 1 之间")
        values[k] = value
    if key == "ecommerce":
        prediction = values["visitors"]*values["conversion"]*values["basket"]
    else:
        prediction = values["revenue"]-sum(v for k,v in values.items() if k != "revenue")
    actual = D(calculate(key)["breakdown"]["current"])
    return dict(prediction=str(prediction), improvement=str(prediction-actual),
                parameters={k:str(v) for k,v in values.items()},
                kind="条件性点估计", assumptions="未调整的因子保持现期值；不包含干预成本与因子联动。",
                interval=None)
