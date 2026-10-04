"""Active finite residual stocks, connected to the common physical flow engine.

Deterministic inventory; chronological within the modeled operating bins. Only
opening-bin material may be withdrawn. New deposits are usable in the next bin.
No implicit cyclic stock boundary, free disposal, transport, or treatment.
"""
from __future__ import annotations
from dataclasses import asdict, dataclass, field
from math import isfinite
from typing import Mapping


@dataclass(frozen=True)
class StockSpec:
    form: str
    location: str
    capacity: float | tuple[float, ...] | None
    holding_charge: float = 0.0  # per closing unit per decision epoch, explicit private cost
    terminal_limit: float | None = None
    terminal_charge: float = 0.0

    def limit(self, k):
        return self.capacity[k] if isinstance(self.capacity, (tuple, list)) else self.capacity


@dataclass(frozen=True)
class StockSystem:
    stocks: Mapping[str, StockSpec]
    block_weights: tuple[float, ...]

    def validate(self, sc, K):
        fs = sc.flow_system
        if fs is None or not self.stocks:
            raise ValueError('Active stocks require explicit flows and at least one named stock')
        if len(self.block_weights) != K or any(not isfinite(w) or w <= 0 for w in self.block_weights):
            raise ValueError('One finite strictly positive stock-flow weight per decision epoch required')
        for name, spec in self.stocks.items():
            if name not in fs.destinations or fs.destinations[name].kind != 'stock':
                raise ValueError('Each active stock must refer to a registered stock destination')
            dest = fs.destinations[name]
            if spec.form not in fs.form_units or spec.location not in sc.locations:
                raise ValueError('Invalid stock form/location')
            if fs.form_units[spec.form] != dest.quantity_unit:
                raise ValueError('Stock form and destination quantity units differ')
            if spec.form in fs.spill_forms:
                raise ValueError('Active-stock forms must be closed; use an explicit release destination')
            bounds = list(spec.capacity) if isinstance(spec.capacity, (tuple, list)) else [spec.capacity] * K
            if len(bounds) != K or any(b is not None and (not isfinite(b) or b < 0) for b in bounds):
                raise ValueError('Stock capacity must be a nonnegative scalar, None, or a full epoch sequence')
            for v in (spec.holding_charge, spec.terminal_charge):
                if not isfinite(v) or v < 0: raise ValueError('Stock charges must be nonnegative and finite')
            if spec.terminal_limit is not None and (not isfinite(spec.terminal_limit) or spec.terminal_limit < 0):
                raise ValueError('Invalid global terminal stock limit')
            for d in sc.designs.values():
                if d.kind in {'sink', 'withdraw'} and d.destination == name:
                    if (d.form, d.loc) != (spec.form, spec.location):
                        raise ValueError('Stock intake/withdrawal must preserve its declared form and location')
        for d in sc.designs.values():
            if d.kind == 'withdraw' and d.destination not in self.stocks:
                raise ValueError('Every withdrawal must draw from an actively modeled stock')

    def initial(self, sc):
        return {n: float(sc.flow_system.destinations[n].initial_stock) for n in self.stocks}

    def manifest(self, sc):
        return {'stocks': {n: asdict(s) for n, s in self.stocks.items()},
                'block_weights': list(self.block_weights),
                'initial_stocks': self.initial(sc),
                'quantity_units': {n: sc.flow_system.destinations[n].quantity_unit for n in self.stocks},
                'semantics': 'pathwise inventory; withdrawal before new-bin deposits; explicit carry-over; global terminal boundary; reliability contingencies share opening stock and normal-state stock alone carries to the next decision epoch'}

    @classmethod
    def from_manifest(cls, manifest):
        return cls({n: StockSpec(**s) for n, s in manifest['stocks'].items()},
                   tuple(manifest['block_weights']))


def validate_context(sc, stocks, K, k0=0, stock_state=None, contingencies=None):
    if stocks is None:
        if stock_state is not None: raise ValueError('Stock state supplied without a stock model')
        if any(d.kind == 'withdraw' for d in sc.designs.values()):
            raise ValueError('Withdrawal modules require an active StockSystem')
        return None
    if not isinstance(stocks, StockSystem): raise TypeError('stocks must be a StockSystem')
    stocks.validate(sc, K)
    if not isinstance(k0, int) or not 0 <= k0 < K:
        raise ValueError('Stock window start must lie within the declared global trajectory')
    if k0 > 0 and stock_state is None:
        raise ValueError('A continuation window requires explicit inherited stock_state')
    state = stocks.initial(sc) if stock_state is None else dict(stock_state)
    if set(state) != set(stocks.stocks) or any(not isfinite(x) or x < -1e-6 for x in state.values()):
        raise ValueError('Inherited stock state must specify every active stock in nonnegative canonical quantities')
    # MILP/LP roundoff may put a nonnegative variable infinitesimally below zero.
    # Canonicalize only within the 1e-6 stock-audit tolerance; substantive negative inventories still fail.
    return {n:max(0.,x) for n,x in state.items()}


def add_stock_epoch(prob, sc, stocks, k, previous, flow, tag=''):
    """Attach stock variables to already assembled physical operating activities."""
    if stocks is None: return None, {}
    from .backend import lp
    H, T = sc.hours, sc.periods
    weight = stocks.block_weights[k]
    handles = {}; closing = {}
    for idx, (name, spec) in enumerate(stocks.stocks.items()):
        dest = sc.flow_system.destinations[name]
        cap = spec.limit(k)
        levels = [lp.LpVariable(f'stock_{tag}_{idx}_{k}_{t}', 0, cap) for t in range(T + 1)]
        prob += levels[0] == dest.retention * previous[name]
        deposits = []; withdrawals = []
        for t in range(T):
            ins = lp.lpSum(weight * H * rates[t] for d, rates in flow['activities'].items()
                           if sc.designs[d].kind == 'sink' and sc.designs[d].destination == name)
            outs = lp.lpSum(weight * H * rates[t] for d, rates in flow['activities'].items()
                            if sc.designs[d].kind == 'withdraw' and sc.designs[d].destination == name)
            prob += outs <= levels[t]
            prob += levels[t + 1] == levels[t] + ins - outs
            deposits.append(ins); withdrawals.append(outs)
        terminal = k == len(stocks.block_weights) - 1
        if terminal and spec.terminal_limit is not None:
            prob += levels[-1] <= spec.terminal_limit
        charge = spec.holding_charge * levels[-1]
        if terminal: charge += spec.terminal_charge * levels[-1]
        handles[name] = {'epoch': k, 'previous': previous[name], 'levels': levels,
                         'deposits': deposits, 'withdrawals': withdrawals,
                         'natural_loss': (1 - dest.retention) * previous[name],
                         'removal_account': dest.removal_account, 'capacity': cap,
                         'quantity_unit': dest.quantity_unit, 'block_weight': weight,
                         'cost': charge, 'terminal_applies': terminal}
        closing[name] = levels[-1]
    return handles, closing


def extract_stock_epoch(handle):
    if handle is None: return {}
    from .backend import lp
    v = lambda x: float(lp.value(x))
    return {n: {'epoch': h['epoch'], 'stock_start': v(h['previous']),
                'levels': [v(x) for x in h['levels']],
                'deposits': [v(x) for x in h['deposits']],
                'withdrawals': [v(x) for x in h['withdrawals']],
                'stock_end': v(h['levels'][-1]), 'natural_loss': v(h['natural_loss']),
                'removal_account': h['removal_account'], 'capacity': h['capacity'],
                'quantity_unit': h['quantity_unit'], 'block_weight': h['block_weight'],
                'cost': v(h['cost']), 'terminal_applies': h['terminal_applies']}
            for n, h in handle.items()}


def replay_stock_epoch(sc, stocks, k, previous, flow_quantities):
    """Rebuild levels from primitive per-period activities, not saved stock totals."""
    H, T = sc.hours, sc.periods; weight = stocks.block_weights[k]
    entries = {}
    for name, spec in stocks.stocks.items():
        dest = sc.flow_system.destinations[name]
        retained = previous[name] * dest.retention
        levels = [retained]; ins = []; outs = []
        for t in range(T):
            intake = sum(weight * H * a['rates'][t] for d, a in flow_quantities['activity'].items()
                         if sc.designs[d].kind == 'sink' and sc.designs[d].destination == name)
            withdrawal = sum(weight * H * a['rates'][t] for d, a in flow_quantities['activity'].items()
                             if sc.designs[d].kind == 'withdraw' and sc.designs[d].destination == name)
            ins.append(intake); outs.append(withdrawal)
            levels.append(levels[-1] + intake - withdrawal)
        terminal = k == len(stocks.block_weights) - 1
        entries[name] = {'epoch': k, 'stock_start': previous[name], 'levels': levels,
                         'deposits': ins, 'withdrawals': outs, 'stock_end': levels[-1],
                         'natural_loss': previous[name] - retained, 'removal_account': dest.removal_account,
                         'capacity': spec.limit(k), 'quantity_unit': dest.quantity_unit,
                         'block_weight': weight, 'terminal_applies': terminal,
                         'cost': levels[-1] * (spec.holding_charge + (spec.terminal_charge if terminal else 0))}
    return entries


def audit_stock_run(sc, stocks, run, tolerance=1e-6):
    """Independent stock conservation, inventory availability, limit and charge checks."""
    stocks.validate(sc, len(run['epochs']))
    previous = dict(run.get('initial_stocks') or stocks.initial(sc))
    initial = dict(previous); rows = []; max_error = 0.0
    def eq(a, b, label):
        nonlocal max_error
        err = abs(a-b); max_error = max(max_error, err)
        if not isfinite(err) or err > tolerance: raise AssertionError(label)
    for k, epoch in enumerate(run['epochs']):
        states = epoch['operating_states']
        normal = next((state for state in states if state.get('name') == 'normal'), states[0])
        opening = dict(previous)
        rebuilt = replay_stock_epoch(sc, stocks, k, opening, normal['flow'])
        saved = epoch['stocks']
        # Reliability contingencies are pathwise stress states: every state starts
        # from the same inherited opening stock, while only the normal closing
        # state carries into the next decision epoch.
        for state in states:
            if not state.get('stocks'):
                raise AssertionError('Missing pathwise stock record')
            rb = replay_stock_epoch(sc, stocks, k, opening, state['flow'])
            ss = state['stocks']
            if set(ss) != set(rb): raise AssertionError('Incomplete pathwise stock record')
            for n,e in rb.items():
                if abs(e['stock_end']-ss[n]['stock_end'])>tolerance:
                    raise AssertionError('Incorrect pathwise stock end')
                if any(o > level+tolerance for o,level in zip(e['withdrawals'],e['levels'])):
                    raise AssertionError('Pathwise withdrawal exceeds opening-period stock')
                if e['capacity'] is not None and any(x > e['capacity']+tolerance for x in e['levels']):
                    raise AssertionError('Pathwise stock capacity exceeded')
        if set(saved) != set(rebuilt): raise AssertionError('Incomplete stock record')
        for name, e in rebuilt.items():
            s = saved[name]; spec = stocks.stocks[name]
            for field in ['epoch','stock_start','stock_end','natural_loss','cost','block_weight']:
                eq(e[field], s[field], 'Incorrect stock '+field)
            for field in ['removal_account','quantity_unit','capacity','terminal_applies']:
                if e[field] != s[field]: raise AssertionError('Incorrect stock metadata '+field)
            for field in ['levels','deposits','withdrawals']:
                if len(s[field]) != len(e[field]): raise AssertionError('Incomplete stock series')
                for a,b in zip(e[field],s[field]): eq(a,b,'Stock primitive mismatch '+field)
            if any(x < -tolerance for x in e['levels'] + e['deposits'] + e['withdrawals']):
                raise AssertionError('Negative inventory or movement')
            if any(o > level+tolerance for o,level in zip(e['withdrawals'],e['levels'])):
                raise AssertionError('Withdrawal exceeds opening-period stock')
            if e['capacity'] is not None and any(x > e['capacity']+tolerance for x in e['levels']):
                raise AssertionError('Stock capacity exceeded')
            if e['terminal_applies'] and spec.terminal_limit is not None and e['stock_end']>spec.terminal_limit+tolerance:
                raise AssertionError('Global terminal stock limit exceeded')
            previous[name] = e['stock_end']
        eq(sum(e['cost'] for e in rebuilt.values()),epoch['stock_cost'],'Incorrect epoch stock cost')
        rows.append({'epoch':k, 'stocks':rebuilt})
    totals = {n:{'deposited':sum(sum(row['stocks'][n]['deposits']) for row in rows),
                 'withdrawn':sum(sum(row['stocks'][n]['withdrawals']) for row in rows),
                 'natural_loss':sum(row['stocks'][n]['natural_loss'] for row in rows),
                 'initial':initial[n], 'final':previous[n]} for n in initial}
    for n,a in totals.items(): eq(a['initial']+a['deposited']-a['withdrawn']-a['natural_loss'],a['final'],'Global conservation failed')
    return {'passed':True, 'max_absolute_error':max_error, 'epochs':rows, 'totals':totals,
            'scope':'normal-path inventory conservation plus pathwise reliability-contingency bounds; contingency closing stocks do not carry between decision epochs'}
