"""Bounded expression trees for pre-aggregated metric inputs; never uses eval."""
from decimal import Decimal, DecimalException, localcontext
import re

_NAME = re.compile(r'^[a-z][a-z0-9_]{0,63}$')
_OPS = {'add', 'sub', 'mul', 'div'}


def _name(value):
    if not isinstance(value, str) or not _NAME.fullmatch(value):
        raise ValueError('invalid metric name')
    return value


def _unit(value):
    if not isinstance(value, dict) or len(value) > 8:
        raise ValueError('invalid unit')
    result = {}
    for key, power in value.items():
        _name(key)
        if type(power) is not int or abs(power) > 8:
            raise ValueError('invalid unit exponent')
        if power:
            result[key] = power
    return result


def _combine(left, right, sign):
    result = dict(left)
    for key, value in right.items():
        result[key] = result.get(key, 0) + sign * value
    if any(abs(v) > 8 for v in result.values()):
        raise ValueError('unit exponent exceeds limit')
    return {k: v for k, v in result.items() if v}


def _number(value):
    if not isinstance(value, str) or len(value) > 64:
        raise ValueError('numeric values must be decimal strings')
    try:
        result = Decimal(value)
    except DecimalException:
        raise ValueError('invalid number') from None
    if not result.is_finite() or abs(result) > Decimal('1e18') or result.as_tuple().exponent < -18:
        raise ValueError('number outside supported range')
    return result


def validate_definitions(definitions):
    """Validate every metric's references, expression structure and units.

    This does not require data and deliberately does not assert that an
    expression is numerically defined for every possible input.
    """
    if not isinstance(definitions, dict) or not definitions or len(definitions) > 100:
        raise ValueError('invalid metric definitions')
    for name in definitions:
        _name(name)
    visiting, memo = set(), {}
    remaining = [1000]

    def metric(name):
        if name in memo:
            return memo[name]
        if name in visiting:
            raise ValueError('metric cycle')
        if name not in definitions:
            raise ValueError('unknown metric reference')
        definition = definitions[name]
        if not isinstance(definition, dict) or set(definition) != {'unit', 'expression'}:
            raise ValueError('invalid metric definition')
        declared = _unit(definition['unit'])
        visiting.add(name)
        actual = declared if definition['expression'] is None else expression(definition['expression'], 0)
        if actual != declared:
            raise ValueError('declared unit does not match expression')
        visiting.remove(name)
        memo[name] = declared
        return declared

    def expression(node, depth):
        remaining[0] -= 1
        if remaining[0] < 0 or depth > 16 or not isinstance(node, dict):
            raise ValueError('expression exceeds limits or is invalid')
        if set(node) == {'ref'}:
            return metric(_name(node['ref']))
        if set(node) == {'const'}:
            _number(node['const'])
            return {}
        if (set(node) != {'op', 'args'} or not isinstance(node['op'], str)
                or node['op'] not in _OPS or not isinstance(node['args'], list) or len(node['args']) != 2):
            raise ValueError('unsupported expression')
        left, right = (expression(arg, depth + 1) for arg in node['args'])
        if node['op'] in ('add', 'sub'):
            if left != right:
                raise ValueError('incompatible units')
            return left
        return _combine(left, right, 1 if node['op'] == 'mul' else -1)

    for name in definitions:
        metric(name)
    return memo


def evaluate(definitions, inputs, target):
    """Evaluate a metric and return Decimal value and unit dimensions.

    Definitions map names to {unit, expression}; expression is None for an
    input, otherwise {ref}, {const}, or binary {op, args}. Input values must
    already be aggregated at the requested scope. No persistence implied.
    """
    if not isinstance(definitions, dict) or len(definitions) > 100 or not isinstance(inputs, dict):
        raise ValueError('invalid metric definitions or inputs')
    for name in definitions:
        _name(name)
    _name(target)
    visiting, memo = set(), {}
    remaining = [1000]

    def metric(name):
        if name in memo:
            return memo[name]
        if name in visiting:
            raise ValueError('metric cycle')
        if name not in definitions:
            raise ValueError('unknown metric reference')
        definition = definitions[name]
        if not isinstance(definition, dict) or set(definition) != {'unit', 'expression'}:
            raise ValueError('invalid metric definition')
        declared = _unit(definition['unit'])
        visiting.add(name)
        if definition['expression'] is None:
            if name not in inputs:
                raise ValueError('missing aggregated input')
            result = (_number(inputs[name]), declared)
        else:
            result = expression(definition['expression'], 0)
            if result[1] != declared:
                raise ValueError('declared unit does not match expression')
        visiting.remove(name)
        memo[name] = result
        return result

    def expression(node, depth):
        remaining[0] -= 1
        if remaining[0] < 0 or depth > 16 or not isinstance(node, dict):
            raise ValueError('expression exceeds limits or is invalid')
        if set(node) == {'ref'}:
            return metric(_name(node['ref']))
        if set(node) == {'const'}:
            return _number(node['const']), {}
        if (set(node) != {'op', 'args'} or not isinstance(node['op'], str)
                or node['op'] not in _OPS or not isinstance(node['args'], list) or len(node['args']) != 2):
            raise ValueError('unsupported expression')
        a, ua = expression(node['args'][0], depth + 1)
        b, ub = expression(node['args'][1], depth + 1)
        op = node['op']
        if op in ('add', 'sub'):
            if ua != ub:
                raise ValueError('incompatible units')
            return (a + b if op == 'add' else a - b), ua
        if op == 'div' and b == 0:
            raise ValueError('division by zero')
        return (a * b if op == 'mul' else a / b), _combine(ua, ub, 1 if op == 'mul' else -1)

    try:
        with localcontext() as context:
            context.prec = 38
            value, unit = metric(target)
    except DecimalException:
        raise ValueError('metric arithmetic failed') from None
    if not value.is_finite() or abs(value) > Decimal('1e36'):
        raise ValueError('metric result outside supported range')
    return {'value': value, 'unit': unit}
