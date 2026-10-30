"""Conservative deterministic comparison, independent of document extraction."""
import math


def evaluate(rule, farm):
    key = rule['fact_key']
    op = rule['operator']
    expected = rule['expected']
    if key == 'minimum_selection_points':
        return 'manual_review'  # Possible points are deliberately not calculated yet.
    if rule.get('reference_date') or rule.get('exceptions'):
        return 'manual_review'
    if key == 'unknown' or op not in ('eq', 'neq', 'gte', 'lte', 'in', 'contains'):
        return 'manual_review'
    # Legacy rules refer to an endpoint. Always use the entire known interval.
    base = key[:-4] if key.endswith(('_min', '_max')) else key
    if base in ('cows', 'land', 'milk'):
        lo, hi = farm.get(base+'_min'), farm.get(base+'_max')
        if lo is None or hi is None:
            return 'unknown'
        if any(type(v) not in (int, float) or not math.isfinite(v) for v in (lo, hi, expected)) or lo > hi:
            return 'manual_review'
        if op == 'gte':
            yes, no = lo >= expected, hi < expected
        elif op == 'lte':
            yes, no = hi <= expected, lo > expected
        elif op in ('eq', 'neq'):
            yes, no = lo == hi == expected, expected < lo or expected > hi
            if op == 'neq':
                yes, no = no, yes
        else:
            return 'manual_review'
        if not yes and not no:
            return 'unknown'
    else:
        value = farm.get(key)
        if value is None:
            return 'unknown'
        try:
            if type(value) is bool and type(expected) is not bool:
                return 'manual_review'
            yes = {'eq': lambda: value == expected, 'neq': lambda: value != expected,
                   'gte': lambda: value >= expected, 'lte': lambda: value <= expected,
                   'in': lambda: value in expected, 'contains': lambda: expected in value}[op]()
        except (TypeError, ValueError):
            return 'manual_review'
    return 'met' if yes else ('unmet_fixed' if rule.get('fixed') else 'unmet_changeable')
