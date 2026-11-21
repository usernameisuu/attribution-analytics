"""Exact monetary inputs and reproducible attribution, independent of HTTP or models."""
from dataclasses import dataclass
from decimal import Decimal, localcontext
from itertools import combinations
from math import factorial
from typing import Callable, Mapping

D = Decimal


def number(value: object) -> Decimal:
    try:
        result = D(str(value))
    except Exception as exc:
        raise ValueError("数值格式无效") from exc
    if not result.is_finite():
        raise ValueError("数值必须有限")
    return result


@dataclass(frozen=True)
class Factor:
    key: str
    label: str
    baseline: Decimal
    current: Decimal
    contribution: Decimal


@dataclass(frozen=True)
class Breakdown:
    method: str
    baseline: Decimal
    current: Decimal
    factors: tuple[Factor, ...]
    unit: str = "元"

    @property
    def delta(self) -> Decimal:
        return self.current - self.baseline

    def as_dict(self) -> dict:
        # API transmits decimals as strings; rounding belongs to presentation.
        delta = self.delta
        return {
            "method": self.method, "unit": self.unit,
            "baseline": str(self.baseline), "current": str(self.current),
            "delta": str(delta),
            "change_rate": str(delta / self.baseline) if self.baseline else None,
            "residual": str(delta - sum((f.contribution for f in self.factors), D(0))),
            "factors": [dict(key=f.key, label=f.label, baseline=str(f.baseline),
                             current=str(f.current), contribution=str(f.contribution),
                             contribution_rate=str(f.contribution / delta)
                             if abs(delta) > D("1e-20") else None) for f in self.factors],
        }


def validate_pair(base: Mapping, current: Mapping) -> None:
    if not base or set(base) != set(current):
        raise ValueError("两期必须提供相同且非空的因子集合")


def additive(base: Mapping, current: Mapping, coefficients: Mapping,
             labels: Mapping) -> Breakdown:
    validate_pair(base, current)
    if set(base) != set(coefficients):
        raise ValueError("每个因子必须有明确系数")
    b = {k: number(v) for k, v in base.items()}
    c = {k: number(v) for k, v in current.items()}
    weights = {k: number(v) for k, v in coefficients.items()}
    factors = tuple(Factor(k, labels.get(k, k), b[k], c[k],
                           (c[k] - b[k]) * weights[k]) for k in b)
    return Breakdown("additive", sum((b[k]*weights[k] for k in b), D(0)),
                     sum((c[k]*weights[k] for k in c), D(0)), factors)


def product(values: Mapping[str, Decimal]) -> Decimal:
    result = D(1)
    for value in values.values():
        result *= value
    return result


def shapley(base: Mapping, current: Mapping, evaluate: Callable,
            labels: Mapping, unit: str = "元") -> Breakdown:
    validate_pair(base, current)
    keys = tuple(base)
    n = len(keys)
    if n > 8:
        raise ValueError("精确因子 Shapley 最多支持 8 个因子，请使用层级分解")
    b, c = ({k: number(v) for k, v in source.items()} for source in (base, current))
    with localcontext() as ctx:
        ctx.prec = 50
        cache: dict[frozenset, Decimal] = {}

        def value(subset: frozenset) -> Decimal:
            if subset not in cache:
                try:
                    cache[subset] = number(evaluate({k: c[k] if k in subset else b[k] for k in keys}))
                except ArithmeticError as exc:
                    raise ValueError("反事实组合含除零或无效数值，无法分解") from exc
            return cache[subset]

        factors = []
        for key in keys:
            others = [k for k in keys if k != key]
            contribution = D(0)
            for size in range(n):
                weight = D(factorial(size)*factorial(n-size-1))/D(factorial(n))
                for subset in combinations(others, size):
                    selected = frozenset(subset)
                    contribution += weight*(value(selected | {key})-value(selected))
            factors.append(Factor(key, labels.get(key, key), b[key], c[key], contribution))
        return Breakdown("shapley_exact", value(frozenset()), value(frozenset(keys)), tuple(factors), unit)


def multiplicative(base: Mapping, current: Mapping, labels: Mapping) -> Breakdown:
    validate_pair(base, current)
    b, c = ({k: number(v) for k, v in source.items()} for source in (base, current))
    if any(v <= 0 for v in (*b.values(), *c.values())):
        result = shapley(b, c, product, labels)
        return Breakdown("shapley_exact_lmdi_not_applicable", result.baseline,
                         result.current, result.factors)
    with localcontext() as ctx:
        ctx.prec = 50
        y0, y1 = product(b), product(c)
        mean = y0 if y0 == y1 else (y1-y0)/(y1.ln()-y0.ln())
        factors = tuple(Factor(k, labels.get(k, k), b[k], c[k],
                               mean*(c[k]/b[k]).ln()) for k in b)
        return Breakdown("lmdi", y0, y1, factors)


def ratio_slices(base: Mapping[str, tuple], current: Mapping[str, tuple],
                 labels: Mapping) -> Breakdown:
    """Two-factor Shapley for N/D, allocated to disjoint additive slices."""
    validate_pair(base, current)
    b = {k: (number(v[0]), number(v[1])) for k, v in base.items()}
    c = {k: (number(v[0]), number(v[1])) for k, v in current.items()}
    n0, d0 = (sum((v[i] for v in b.values()), D(0)) for i in (0, 1))
    n1, d1 = (sum((v[i] for v in c.values()), D(0)) for i in (0, 1))
    if d0 <= 0 or d1 <= 0:
        raise ValueError("两期整体分母必须大于零")
    with localcontext() as ctx:
        ctx.prec = 50
        cn = (1/d0+1/d1)/2
        cd = -(n0+n1)/(2*d0*d1)
        factors = tuple(Factor(k, labels.get(k, k), b[k][0], c[k][0],
                               100*(cn*(c[k][0]-b[k][0])+cd*(c[k][1]-b[k][1]))) for k in b)
        return Breakdown("ratio_shapley_allocated", 100*n0/d0, 100*n1/d1, factors, "百分点")
