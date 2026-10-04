"""Versioned pilot adapters and lossless discovery records.

This module changes observation and campaign composition, not technology physics.
Raw inputs and operating states are authoritative; compact features are derived.
"""
from __future__ import annotations
import ast
import gzip
import hashlib
import itertools
import json
from dataclasses import asdict, is_dataclass, replace
from pathlib import Path
from types import SimpleNamespace

from .experiment_contract import DiscoveryContract, validate_discovery_contract
from .network_worlds import make_network_world
from .interface_examples import lifecycle_world
from .dynamic import run_policy, path_cost, path_objective
from .realizability import Capability, DesignRequirement, RealizabilitySpec
from .variation import MutationRule, RecombinationRule
from .vsr import VSRConfig, run_vsr, serializable_result
from .flows import audit_flow_block
from .flow_audit import audit_operating_state
from .stocks import audit_stock_run
from .attributes import audit_attribute_run
from .accounting import independent_path_ledger, CONVENTION
from .measurement.schema import standard_run_measurement
from .measurement.interfaces import interface_history

SCHEMA = 'discovery-pilot-1.0'
CONTRACT = validate_discovery_contract(DiscoveryContract(
    campaign='discovery_pilot_v1',
    dimensions=('production connectivity/lead/planning horizon', 'interface lifecycle/adapter/reliability/horizon',
                'physical seed/proposal stream/parent selection'),
    sampling='Declared factorial instrumentation pilot: 48 production + 32 interface + 16 VSR baseline attempts.',
    measurements=('raw inputs and epochs', 'service by requirement and unit', 'known/installed/operating designs',
                  'stocks/capabilities/WIP', 'cost components', 'search events and lineage', 'solver outcomes'),
    aggregation_level='History within world/scenario/policy; epochs are repeated observations, not independent worlds.',
    validation_plan='All pilot histories are exploration. Future validation must reserve complete generator ancestries; no pilot holdout claim.',
    solver_gate='Complete histories require optimal operating solves and physical/accounting audits. Certified infeasibility, unresolved solves and errors remain separate.'
))


def jsonable(value):
    if is_dataclass(value):
        return jsonable(asdict(value))
    if isinstance(value, dict):
        if all(isinstance(k, str) for k in value):
            return {k: jsonable(v) for k, v in value.items()}
        return {'__typed_mapping__': [[jsonable(k), jsonable(v)] for k, v in sorted(value.items(), key=lambda kv: repr(kv[0]))]}
    if isinstance(value, (list, tuple)):
        return [jsonable(v) for v in value]
    if isinstance(value, (set, frozenset)):
        return [jsonable(v) for v in sorted(value, key=repr)]
    if hasattr(value, 'item'):
        return value.item()
    return value


def canonical(value):
    return json.dumps(jsonable(value), sort_keys=True, separators=(',', ':'), allow_nan=False)


def ident(value, prefix=''):
    return prefix + hashlib.sha256(canonical(value).encode()).hexdigest()[:20]


def atomic_json(path, value):
    path = Path(path); path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + '.tmp')
    tmp.write_text(canonical(value) + '\n'); tmp.replace(path)


def atomic_trace(path, value):
    path = Path(path); path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + '.tmp')
    with gzip.open(tmp, 'wt', encoding='utf-8') as f:
        f.write(canonical(value))
    tmp.replace(path)


def read_trace(path):
    with gzip.open(path, 'rt', encoding='utf-8') as f:
        return json.load(f)


def pilot_specs():
    out = []
    for seed, connectivity, lead, horizon in itertools.product(range(4), ('sparse', 'rich'), (0, 1), (1, 3, 6)):
        out.append(dict(family='production', seed=seed, connectivity=connectivity, construction_lead=lead, horizon=horizon))
    for n, deprecate, adapter, reliability, horizon in itertools.product((1, 3), (None, 2), (.1, 3.), (False, True), (1, 5)):
        out.append(dict(family='interface', dependents=n, deprecate=deprecate, adapter_cost=adapter, reliability=reliability, horizon=horizon))
    for seed, connectivity, proposal_seed, parent_pool in itertools.product(range(2), ('separated', 'rich'), range(2), ('seeds', 'knowledge')):
        out.append(dict(family='vsr', seed=seed, connectivity=connectivity, proposal_seed=proposal_seed, parent_pool=parent_pool))
    return out


def ancestry(spec):
    # Conservative grouping: common physical seed across sizes, policies and VSR streams stays together.
    return 'interface-template-1' if spec['family'] == 'interface' else f"production-seed-{spec['seed']}"


def discovery_specs():
    """First breadth tranche; seeds 8 and 9 reserved intact for validation."""
    out = []
    for seed, n, connectivity, stock, shock, lead, horizon in itertools.product(
            range(4, 10), (3, 5), ('separated', 'rich'), (2., 12.), (False, True), (0, 1), (1, 2, 3, 6)):
        out.append(dict(family='production', seed=seed, n_sites=n, connectivity=connectivity,
                        residual_capacity=stock, quality_shock=shock, construction_lead=lead, horizon=horizon))
    for n, deprecate, adapter, direct, reliability, horizon in itertools.product(
            (1, 6), (None, 2), (.05, 5.), (False, True), (False, True), (1, 2, 3, 5)):
        out.append(dict(family='interface', dependents=n, deprecate=deprecate, adapter_cost=adapter,
                        direct=direct, reliability=reliability, horizon=horizon))
    for seed, connectivity, proposal_seed, parent_pool, evaluation_horizon in itertools.product(
            (4, 5, 8, 9), ('separated', 'rich'), range(4), ('seeds', 'knowledge'), (1, 3)):
        out.append(dict(family='vsr', seed=seed, connectivity=connectivity, proposal_seed=proposal_seed,
                        parent_pool=parent_pool, evaluation_horizon=evaluation_horizon))
    return [{**s, 'campaign': 'discovery_batch_v1'} for s in out]


def classify_exception(exc):
    text = str(exc)
    if text.startswith('Optimization not proved optimal: '):
        try:
            meta = ast.literal_eval(text.split(': ', 1)[1])
        except (ValueError, SyntaxError):
            return 'error', None
        return ('certified_infeasible' if meta.get('status') == 'Infeasible' else 'unresolved'), meta
    return 'error', None


def prepare(spec, time_limit):
    family = spec['family']
    if family == 'interface':
        sc, tr, prm, hist = lifecycle_world(spec['dependents'], spec['deprecate'], spec['adapter_cost'], spec.get('direct', False))
        cont = [{'name': 'incumbent_failure', 'p': .05, 'fail': ('I0',)}] if spec['reliability'] else None
        return dict(sc=sc, tr=tr, prm=prm, hist=hist, stocks=None, realizability=None, forbid=(),
                    contingencies=cont, metadata={'generator': 'interface-lifecycle-v1', 'direct_compatibility': spec.get('direct', False)},
                    cfg=None, mutation=(), recombination=(), time_limit=time_limit)
    n, K = (spec.get('n_sites', 4), 6) if family == 'production' else (3, 4)
    shock = family == 'production' and spec.get('quality_shock', True)
    w = make_network_world(n_sites=n, seed=spec['seed'], connectivity=spec['connectivity'], K=K,
                           residual_capacity=spec.get('residual_capacity', 8. if family == 'production' else 6.),
                           shock_site=0 if shock else None,
                           shock_epoch=3 if shock else None)
    sc, tr, prm = w.scenario, w.trajectory, w.params
    rs = None; cfg = None; rules = []; recomb = []; forbid = w.forbid
    if family == 'production':
        inherited = {v.design for v in w.history}
        tr = replace(tr, construction_lead={name: spec['construction_lead'] for name in sc.designs if name not in inherited})
        requirements = {name: DesignRequirement(build=('modern',), operate=('modern',), maintain=('modern',))
                        for name in sc.designs if name not in inherited}
        rs = RealizabilitySpec({'modern': Capability(0, 0, None)}, requirements, initially_ready=('modern',))
    else:
        designs = {name: d for name, d in sc.designs.items() if name not in w.forbid}
        sc = replace(sc, designs=designs); prm = replace(prm, life={name: prm.life[name] for name in designs}); forbid = ()
        for loc in sc.locations:
            for role in ('REFINE', 'FINISH_LOW', 'RECOVER'):
                name = role + '_' + loc
                rules.append(MutationRule(name, name, variable_sigma=.25, cost_log_sigma=.25))
            recomb.append(RecombinationRule('chain_' + loc, 'REFINE_' + loc, 'FINISH_LOW_' + loc, 'intermediate', loc, (.9, 1.1)))
        cfg = VSRConfig(seed=spec['proposal_seed'], parent_pool=spec['parent_pool'], proposals_per_epoch=2,
                        selection='individual', adoption_horizon=1, evaluation_horizon=spec.get('evaluation_horizon', 1),
                        evaluation_cost=.005, support_cost=.01, recombination_share=.25, time_limit=time_limit)
    return dict(sc=sc, tr=tr, prm=prm, hist=w.history, stocks=w.stocks, realizability=rs,
                forbid=forbid, contingencies=None, metadata=w.metadata, cfg=cfg,
                mutation=tuple(rules), recombination=tuple(recomb), time_limit=time_limit)


def input_record(ctx, spec):
    sc, tr = ctx['sc'], ctx['tr']
    return jsonable(dict(scenario=sc, trajectory=tr, params=ctx['prm'], history=ctx['hist'],
        stocks=None if ctx['stocks'] is None else ctx['stocks'].manifest(sc),
        realizability=None if ctx['realizability'] is None else ctx['realizability'].manifest(),
        forbid=ctx['forbid'], contingencies=ctx['contingencies'], generator=ctx['metadata'],
        policy=ctx['cfg'] if ctx['cfg'] is not None else {'horizon': spec['horizon'], 'expectations': 'true within planning window'},
        operators={'mutation': ctx['mutation'], 'recombination': ctx['recombination']},
        clocks={'decision_epochs': tr.K, 'operating_periods': sc.periods, 'hours_per_operating_period': sc.hours, 'representative_days': sc.days},
        accounting=CONVENTION,
        capabilities={'physical_stocks': 'disabled' if ctx['stocks'] is None else 'enabled',
                      'capability_readiness': 'disabled' if ctx['realizability'] is None else 'enabled_initially_ready',
                      'interfaces': 'disabled' if sc.interface_system is None else 'enabled',
                      'search': 'enabled' if ctx['cfg'] else 'disabled_fixed_known_catalog',
                      'counterfactuals': 'not_measured_in_instrumentation_pilot'}))


def audit_run(ctx, run):
    sc, tr = ctx['sc'], ctx['tr']
    for e in run['epochs']:
        for state in e['operating_states']:
            audit_operating_state(sc, state)
            audit_flow_block(sc, state['flow'], state['physical']['capacities'])
            for demand in state['flow'].get('demands', {}).values():
                if max(demand.get('unmet_rates', [0.])) > 1e-6:
                    raise AssertionError('Required service unmet in pilot')
    if ctx['stocks'] is not None:
        if not audit_stock_run(sc, ctx['stocks'], run)['passed']: raise AssertionError('Stock audit')
    if sc.attribute_system is not None:
        if not audit_attribute_run(sc, run, trajectory=tr)['passed']: raise AssertionError('Attribute audit')
    ledger = independent_path_ledger(sc, tr, ctx['prm'], run)
    delta = abs(ledger['path_objective'] - path_objective(tr, run))
    if delta > 1e-5 * max(1., abs(ledger['path_objective'])): raise AssertionError('Independent accounting mismatch')
    return {'passed': True, 'objective_replay_error': delta, 'ledger': ledger}


def epoch_records(ctx, run, events=()):
    sc = ctx['sc']; by_event = {e['epoch']: e for e in events}; records = []
    for k, e in enumerate(run['epochs']):
        normal = next(s for s in e['operating_states'] if s['name'] == 'normal')
        search = by_event.get(k)
        known = sorted(set(search['opening']['knowledge']) | set(search.get('knowledge_added', []))) if search else sorted(sc.designs)
        service = {}
        for name, d in normal['flow'].get('demands', {}).items():
            obligation = next(x for x in sc.flow_system.demands if x.name == name)
            service[name] = {'form': obligation.form, 'location': obligation.location,
                             'quantity_unit': sc.flow_system.form_units[obligation.form], 'rates': d}
        cap_units = {n: {'quantity': x, 'unit': sc.designs[n].activity_unit or 'native design capacity'} for n, x in e['capacity'].items()}
        records.append(dict(epoch=k, service_by_requirement=service, capacities=cap_units,
            active_designs=sorted(n for n, x in e['throughput'].items() if x > 1e-8),
            installed_designs=sorted(n for n, x in e['capacity'].items() if x > 1e-8), known_designs=known,
            realizability=e.get('realizability'), realizability_status='enabled' if ctx['realizability'] is not None else 'disabled',
            stocks=e.get('stocks') if ctx['stocks'] is not None else None,
            builds=e['builds'], orders=e.get('orders'), commissioned=e.get('commissioned'), wip=e.get('wip'),
            costs={name: e.get(name, 0.) for name in ('capital', 'fom', 'ops_cost', 'integration_cost', 'realizability_cost', 'stock_cost', 'service_benefit')},
            cost_convention=CONVENTION,
            search_charges=None if search is None else {n: search[n] for n in ('evaluation_charge', 'support_charge')},
            raw_operating_state_count=len(e['operating_states'])))
    return records


def execute(ctx, spec, checkpoint):
    if spec['family'] == 'vsr':
        result = run_vsr(ctx['sc'], ctx['tr'], ctx['prm'], ctx['hist'], ctx['mutation'],
                         recombination_rules=ctx['recombination'], config=ctx['cfg'], stocks=ctx['stocks'], epoch_callback=checkpoint)
        ctx = {**ctx, 'sc': result['scenario'], 'tr': result['trajectory'], 'prm': result['params']}
        run = result['run']; serial = serializable_result(result)
        if run['status'] != 'complete':
            return dict(status='certified_infeasible', run=run, search=serial, audit=serial['audit'],
                        epochs=epoch_records(ctx, run, result['events']), summary={'complete_objective': None})
        audit = audit_run(ctx, run)
        audit['search'] = serial['audit']
    else:
        run = run_policy(ctx['sc'], ctx['tr'], ctx['prm'], ctx['hist'], horizon=spec['horizon'],
                         forbid=ctx['forbid'], stocks=ctx['stocks'], realizability=ctx['realizability'],
                         contingencies=ctx['contingencies'], time_limit=ctx['time_limit'], epoch_callback=checkpoint)
        audit = audit_run(ctx, run); serial = None
    wrapper = SimpleNamespace(scenario=ctx['sc'], trajectory=ctx['tr'], metadata=ctx['metadata'])
    measurements = standard_run_measurement(wrapper, run).manifest()
    interfaces = interface_history(ctx['sc'], run, ('I0', 'I1', 'I2', 'B')) if spec['family'] == 'interface' else None
    summary = dict(complete_objective=path_objective(ctx['tr'], run), path_cost=path_cost(ctx['tr'], run),
                   research_cost=0. if serial is None else serial['research_cost'],
                   epochs=len(run['epochs']), solver_calls=len(run['solver_log']),
                   active_designs_by_epoch=[sorted(n for n,x in e['throughput'].items() if x>1e-8) for e in run['epochs']],
                   interfaces=interfaces)
    if serial is not None:
        summary['search_audit'] = serial['audit']; summary['all_in_objective'] = summary['complete_objective'] + summary['research_cost']
    return dict(status='complete', run=run, audit=audit, search=serial, measurements=measurements,
                epochs=epoch_records(ctx, run, () if serial is None else serial['events']), summary=summary)
