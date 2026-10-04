"""Shared compiler for legacy operating primitives.

This module is intentionally behavior-preserving.  It owns the equations for
convert, renewable, transport and store designs so static and dynamic engines
cannot drift independently.  Explicit multi-port process/sink/withdraw designs
remain compiled by :mod:`techgraph.flows`.
"""
from __future__ import annotations

from .backend import lp

LEGACY_KINDS = frozenset({'convert','renewable','transport','store'})


def period_weights(sc):
    """Operating weight of each period (1.0 everywhere unless representative days are declared)."""
    w = getattr(sc, 'period_weights', None)
    if w is None:
        return [1.0] * sc.periods
    if len(w) != sc.periods or any(x <= 0 for x in w):
        raise ValueError('period_weights must have one positive weight per period')
    if getattr(sc, 'flow_system', None) is not None or (sc.hub_energy > 0):
        raise NotImplementedError('period_weights are supported for legacy designs without a daily hub requirement')
    return [float(x) for x in w]


def _vc(sc, d, t):
    """Variable cost of design d in period t (time-varying if d.var_cost_profile names a profile)."""
    key = getattr(d, 'var_cost_profile', None)
    return d.var_cost * sc.profiles[key][t] if key else d.var_cost


def cycle_blocks(sc):
    """(start, length) of each block within which storage cycles and flexible load shifts are balanced."""
    blocks = getattr(sc, 'cycle_blocks', None)
    if blocks:
        cover = sorted(blocks)
        pos = 0
        for s0, n in cover:
            if s0 != pos or n <= 0:
                raise ValueError('cycle_blocks must tile all periods in order')
            pos += n
        if pos != sc.periods:
            raise ValueError('cycle_blocks must cover all periods')
        return list(cover)
    L = getattr(sc, 'cycle_length', None) or sc.periods
    if sc.periods % L:
        raise ValueError('cycle_length must divide periods')
    return [(s0, L) for s0 in range(0, sc.periods, L)]


def next_period(sc, t):
    """Successor of period t for storage dynamics: cyclic within its block (whole horizon by default)."""
    for s0, n in cycle_blocks(sc):
        if s0 <= t < s0 + n:
            return s0 + (t + 1 - s0) % n
    raise ValueError(f'period {t} outside the horizon')


def add_legacy_module_activity(prob, sc, caps, balance, *, tag='', cap_links=None):
    """Compile legacy module activities into a common balance map.

    Returns ``(cost_terms, emissions, activities, records)``.  ``records`` is
    the historical dynamic-engine activity vector mapping.  ``cap_links`` is
    optionally populated for static LP capacity-rent extraction.
    """
    T, H = sc.periods, sc.hours
    periods = range(T)
    W = period_weights(sc)
    cost, emissions, activities, records = [], [], {}, {}
    cap_links = cap_links if cap_links is not None else None

    def v(prefix, name, t):
        suffix = f'_{tag}' if tag else ''
        return lp.LpVariable(f'{prefix}_{name}{suffix}_{t}', lowBound=0)

    def cname(prefix, name, t):
        suffix = f'_{tag}' if tag else ''
        return f'{prefix}_{name}{suffix}_{t}'

    def link(name, constraint, coef=1.0):
        if cap_links is not None:
            cap_links.setdefault(name, []).append((constraint, coef))

    for name, c in caps.items():
        d = sc.designs[name]
        if d.kind not in LEGACY_KINDS:
            continue
        series = {}
        if d.kind == 'convert':
            a = [v('a', name, t) for t in periods]
            for t in periods:
                cn = cname('cap', name, t)
                prob += a[t] <= c, cn
                link(name, cn, 1.0)
                balance[(d.form_out,d.loc,t)].append(H*a[t])
                balance[(d.form_in,d.loc,t)].append(-H/d.eff*a[t])
                cost.append(W[t]*_vc(sc,d,t)*H*a[t])
                emissions.append(W[t]*d.emis*H/d.eff*a[t])
            series['output'] = a
            records[name] = a
        elif d.kind == 'renewable':
            prof = sc.profiles[d.profile]
            a = [v('a', name, t) for t in periods]
            for t in periods:
                cn = cname('avail', name, t)
                prob += a[t] <= prof[t]*c, cn
                link(name, cn, prof[t])
                balance[(d.form_out or 'elec',d.loc,t)].append(H*a[t])
                cost.append(W[t]*_vc(sc,d,t)*H*a[t])
            series['output'] = a
            records[name] = a
        elif d.kind == 'transport':
            fw = [v('f', name, t) for t in periods]
            bw = [v('b', name, t) for t in periods] if d.bidirectional else []
            for t in periods:
                cn = cname('capf', name, t)
                prob += fw[t] <= c, cn
                link(name, cn, 1.0)
                balance[(d.form,d.loc_from,t)].append(-H*fw[t])
                balance[(d.form,d.loc_to,t)].append(H*(1-d.loss)*fw[t])
                cost.append(W[t]*_vc(sc,d,t)*H*fw[t])
                if bw:
                    cn2 = cname('capb', name, t)
                    prob += bw[t] <= c, cn2
                    link(name, cn2, 1.0)
                    balance[(d.form,d.loc_to,t)].append(-H*bw[t])
                    balance[(d.form,d.loc_from,t)].append(H*(1-d.loss)*bw[t])
                    cost.append(W[t]*_vc(sc,d,t)*H*bw[t])
            series['forward'] = fw
            if bw: series['backward'] = bw
            records[name] = fw + bw
        elif d.kind == 'store':
            ch=[v('c',name,t) for t in periods]
            ds=[v('d',name,t) for t in periods]
            so=[v('s',name,t) for t in periods]
            init = (getattr(sc, 'store_initial', None) or {}).get(name)
            se = v('se', name, 0) if init is not None else None
            for t in periods:
                for prefix, expr in [('pch',ch[t]*d.duration_h),('pdis',ds[t]*d.duration_h),('soc',so[t])]:
                    cn=cname(prefix,name,t); prob += expr <= c, cn; link(name,cn,1.0)
                if init is None:
                    prob += so[next_period(sc,t)] == so[t] + H*(d.eta_c*ch[t]-ds[t]/d.eta_d), cname('dyn',name,t)
                else:                                   # rolling horizon: no wrap-around; the last step fills the end level
                    nxt = so[t+1] if t+1 < len(periods) else se
                    prob += nxt == so[t] + H*(d.eta_c*ch[t]-ds[t]/d.eta_d), cname('dyn',name,t)
                balance[(d.form,d.loc,t)].extend([-H*ch[t],H*ds[t]])
            series={'charge':ch,'discharge':ds,'level':so}
            if init is not None:
                prob += so[0] == init, cname('init',name,0)
                cn=cname('soce',name,0); prob += se <= c, cn; link(name,cn,1.0)
                val = (getattr(sc, 'store_terminal_value', None) or {}).get(name, 0.0)
                if val: cost.append(-val*se)
                series['end'] = [se]
            records[name] = ds
        for (fn, key), fix in ((getattr(sc, 'fixed_activity', None) or {}).items()):
            if fn == name and key in series:
                for t, val in fix.items():
                    prob += series[key][t] == val, cname('fix'+key[:3],name,t)
        activities[name] = series
    return cost, emissions, activities, records
