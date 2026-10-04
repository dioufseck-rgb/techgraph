"""Representative-period accounting and a solver-independent replay ledger.

Preserves the existing finite-horizon convention: one D-day operating block per
decision epoch; committed annualized capital/lump charges continue to asset life
or the evaluation horizon, whichever ends first, even after early retirement.
Inherited capital is sunk and excluded. No salvage value or 730-day multiplier
is introduced here. Units are discounted representative-period cost units,
not the full cash expenditure of a twenty-year project.
"""
from __future__ import annotations
from math import isfinite
from .flows import replay_flow_cost
from .needs import enabled, replay_need_block

CONVENTION = 'representative-block-v1; horizon-truncated capital; no salvage'


def annual_to_block(sc) -> float:
    days = float(sc.days)
    if not isfinite(days) or days <= 0:
        raise ValueError('Scenario.days must be finite and positive')
    return days / 365.0


def capital_charges_by_epoch(sc, traj, prm, run):
    """Reconstruct commitments from realized builds, never from reported capital."""
    weight = annual_to_block(sc)
    capital = [0.0] * traj.K
    for built, epoch in enumerate(run['epochs']):
        for name, capacity in epoch['builds'].items():
            if capacity < 0:
                raise ValueError('Negative realized build')
            design = sc.designs[name]
            mult = traj.mult(name, built)
            charge = (1 - prm.fom_share) * design.annual_cost * mult * weight * capacity
            # New records retain the actual lump binary. Old records use the
            # historical positive-build convention for backwards compatibility.
            lump = epoch.get('lump_builds', {}).get(name, float(capacity > 1e-4))
            charge += design.fixed_cost * mult * weight * lump
            commission = built + traj.lead(name, built)
            for k in range(built, min(traj.K, commission + prm.life[name])):
                capital[k] += charge
    return capital


def reconcile_run(sc, traj, prm, run):
    """Attach path-comparable capital immediately, not only in a later summary."""
    for epoch, charge in zip(run['epochs'], capital_charges_by_epoch(sc, traj, prm, run)):
        epoch['capital'] = charge
    run['accounting'] = {'convention': CONVENTION, 'representative_days': sc.days,
                         'discount_per_epoch': traj.discount,
                         'epoch_weight': 1.0, 'terminal_salvage': 0.0}
    if enabled(sc):
        run['need_config']=sc.need_system.manifest()
        run['accounting']['objective']='expenditure_minus_delivered_optional_value'
    if getattr(sc,'attribute_system',None) is not None:
        run['attribute_config']=sc.attribute_system.manifest()
    if getattr(sc,'interface_system',None) is not None:
        run['interface_config']=sc.interface_system.manifest()
    return run


def independent_path_ledger(sc, traj, prm, run):
    """Reprice saved quantities without an optimizer or reported cost fields.

    Capital comes from build records; maintenance from each epoch's living
    vintages; operation from state-specific flow, fuel, and shortfall quantities.
    Works for records produced by this change set (including contingencies).
    This is an accounting check, not an independent physical-feasibility proof.
    """
    weight = annual_to_block(sc)
    capital = capital_charges_by_epoch(sc, traj, prm, run)
    output = []
    stock_config = run.get("stock_config")
    if stock_config is not None:
        from .stocks import StockSystem, replay_stock_epoch
        stock_spec = StockSystem.from_manifest(stock_config)
        stock_previous = dict(run.get("initial_stocks") or stock_spec.initial(sc))
    for k, epoch in enumerate(run['epochs']):
        if 'vintages' not in epoch or 'operating_states' not in epoch:
            raise ValueError('Replay requires saved vintages and operating_states; rerun the model')
        fom = sum(prm.fom_share * v['annual_cost'] * weight * v['alive']
                  * (1 + prm.aging * (k - v['built'])) for v in epoch['vintages'])
        operating, emissions, unmet, benefit = 0.0, 0.0, 0.0, 0.0
        for state in epoch['operating_states']:
            p = state['probability']
            if enabled(sc):
                benefit += p * replay_need_block(sc,state['flow']['needs'],epoch=k,valuation_epoch=k)['benefit']
            raw = traj.fuel_price[k] * state['fuel_purchased_MWh'] + sc.voll * state['unmet_MWh']
            if sc.flow_system is not None:
                extra = replay_flow_cost(sc,state['flow'])
                # Original aggregate unmet_MWh includes new energy demands: remove
                # that default penalty, then add their declared energy/mass penalties.
                raw += extra['cost'] - sc.voll * extra['energy_unmet']
            em = extra["emissions"] if sc.flow_system is not None else 0.0
            for name, activity in state['throughput'].items():
                d = sc.designs[name]
                if d.kind in {'convert', 'renewable', 'transport'}:
                    raw += d.var_cost * activity
                if d.kind == 'convert':
                    em += d.emis * activity / d.eff
            operating += p * raw
            emissions += p * em
            unmet += p * state['unmet_MWh']
        integration_cost = 0.0
        if run.get('integration_config') is not None:
            tasks = run['integration_config']['tasks']
            completed = epoch['integration']['completed_tasks']
            integration_cost = sum(tasks[t]['completion_cost'] for t in completed)
        realizability_cost = 0.0
        if run.get('realizability_config') is not None:
            caps = run['realizability_config']['capabilities']
            realizability_cost = sum(caps[x['capability']]['acquire_cost'] for x in epoch.get('realizability',{}).get('acquired',[]))
        stock_cost = 0.0
        if stock_config is not None:
            states=epoch["operating_states"]
            normal=next((state for state in states if state.get('name')=='normal'),states[0])
            rebuilt = replay_stock_epoch(sc, stock_spec, k, stock_previous, normal["flow"])
            stock_cost = sum(s["cost"] for s in rebuilt.values())
            stock_previous = {n: s["stock_end"] for n, s in rebuilt.items()}
        switching_cost, congestion_cost = _realism_replay(sc, run, k)
        cost = capital[k] + fom + operating + integration_cost + realizability_cost + stock_cost + switching_cost + congestion_cost
        output.append({'epoch': k, 'capital': capital[k], 'fom': fom, 'ops_cost': operating,
                       'emissions': emissions, 'unmet_MWh': unmet, 'integration_cost':integration_cost,
                       'realizability_cost':realizability_cost, 'stock_cost':stock_cost, 'service_benefit':benefit,
                       'switching_cost':switching_cost, 'congestion_cost':congestion_cost,
                       'discounted_benefit':traj.discount**k*benefit,
                       'discounted_objective':traj.discount**k*(cost-benefit),
                       'discounted_cost': traj.discount ** k * cost})
    return {'convention': CONVENTION, 'epochs': output,
            'path_cost': sum(e['discounted_cost'] for e in output),
            'path_benefit':sum(e['discounted_benefit'] for e in output),
            'path_objective':sum(e['discounted_objective'] for e in output),
            'path_net_value':-sum(e['discounted_objective'] for e in output)}


def _realism_replay(sc, run, k):
    """Reprice v4 operating frictions from saved throughput and corridor use."""
    cfg = run.get('realism_config')
    if not cfg:
        return 0.0, 0.0
    epochs = run['epochs']; e = epochs[k]; sw = 0.0; cong = 0.0
    c = cfg.get('switching_cost', 0.0) or 0.0
    if c > 0 and k > 0:
        cur = {n: x for n, x in e['throughput'].items() if sc.designs[n].kind == 'process'}
        prev = {n: x for n, x in epochs[k-1]['throughput'].items() if sc.designs[n].kind == 'process'}
        sw = c * sum(abs(cur.get(n, 0.0) - prev.get(n, 0.0)) for n in set(cur) | set(prev))
    u0, cc = cfg.get('congestion', (1.0, 0.0))
    if cc > 0 and u0 < 1:
        for cname, use in e.get('corridor_use', {}).items():
            cap = e['capacity'].get(cname, 0.0)
            cong += sum(sc.hours * cc * max(0.0, u - u0 * cap) for u in use)
    return sw, cong
