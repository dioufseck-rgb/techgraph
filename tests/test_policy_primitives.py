"""Tests for per-period rules, stock and boundary measures, charges, escape steps, priority and non-electric substances."""
from dataclasses import replace
import pytest
from techgraph.catalog import Design, Scenario
from techgraph.dynamic import solve_window, Trajectory, Params
from techgraph.model import solve
from techgraph.policy import Measure, Requirement, Charge, apply_priority, lagged
from techgraph.institutions import EmissionCap
from techgraph.demands import Demand
from tests.test_institutions import world


def two_node():
    sc, tr, pm = world()
    d = dict(sc.designs)
    d['GAS_D'] = Design('GAS_D', 'convert', annual_cost=60_000, var_cost=20.0, form_in='fuel', form_out='elec', loc='D', max_cap=1e6)
    d['LINK'] = Design('LINK', 'transport', annual_cost=1_000, form='elec', loc_from='D', loc_to='A', loss=0.0, max_cap=1e6)
    sc = replace(sc, designs=d, fuel_sites=('A', 'D'))
    return sc, tr, Params(life={n: 10 for n in d}, fom_share=0.0, aging=0.0)


def flows(r, n):
    return r['epochs'][0]['hourly'][n]


def test_per_period_minimum_flow():
    sc, tr, pm = world()
    rule = Requirement('min_gas', '>=', lhs=((1.0, Measure('flow', ('GAS',))),), bound=30.0, per_period=True)
    r = solve_window(sc, tr, pm, 0, 0, [], institutions=[rule])
    assert min(flows(r, 'GAS')) >= 30.0 - 1e-6
    assert r['institutions'][0]['violation'] <= 1e-6


def test_per_period_minimum_stock_level():
    sc, tr, pm = world()
    rule = Requirement('min_level', '>=', lhs=((1.0, Measure('stock', ('BAT',))),), bound=50.0, per_period=True)
    r = solve_window(sc, tr, pm, 0, 0, [], institutions=[rule])
    assert r['epochs'][0]['capacity']['BAT'] >= 50.0 - 1e-6
    assert r['institutions'][0]['violation'] <= 1e-6


def test_boundary_inflow_ceiling():
    sc, tr, pm = two_node()
    free = solve_window(sc, tr, pm, 0, 0, [])
    assert sum(flows(free, 'LINK')[:24]) > 1.0                   # cheaper remote gas is imported
    cap = Requirement('import_cap', '<=', lhs=((1.0, Measure('boundary', locations=('A',))),), bound=24 * 40.0)
    r = solve_window(sc, tr, pm, 0, 0, [], institutions=[cap])
    assert r['institutions'][0]['violation'] <= 1e-6 and sum(flows(r, 'LINK')[:24]) <= 24 * 40.0 + 1e-3


def test_charge_amount_and_accounting():
    sc, tr, pm = world()
    base = solve_window(sc, tr, pm, 0, 0, [])
    ch = Charge('fuel_tax', terms=((5.0, Measure('flow', ('GAS',))),), accounting='transfer')
    r = solve_window(sc, tr, pm, 0, 0, [], institutions=[ch])
    rep = r['institutions'][0]
    assert rep['accounting'] == 'transfer' and rep['amount'] > 0
    assert r['objective'] >= base['objective'] - 1e-6


def test_escape_steps_on_a_cap():
    sc, tr, pm = world()
    d = dict(sc.designs); d['GAS'] = replace(d['GAS'], emis=1.0)
    sc = replace(sc, designs=d)
    pool = Requirement('cap', '<=', lhs=((1.0, Measure('byproduct')),), bound=0.0, escape_steps=((10.0, 500.0), (40.0, 1e9)))
    r = solve_window(sc, tr, pm, 0, 0, [], institutions=[pool])
    use = r['institutions'][0]['tier_use']
    assert use[0] == pytest.approx(500.0, rel=1e-6) and use[1] > 0       # the cheap step is exhausted first
    assert r['institutions'][0]['violation'] <= 1e-6


def test_priority_curtails_lower_rank_first():
    sc, tr, pm = world()
    dem = (Demand('homes', 'A', tuple([50.0] * 24), 'utility', 'residential'), Demand('farms', 'A', tuple([50.0] * 24), 'utility', 'agriculture'))
    dem = tuple(apply_priority(dem, [(None, 'residential'), (None, 'agriculture')], top_value=4_000.0, ratio=0.01))
    sc2 = replace(sc, extra_demand={}, demands=dem)
    r = solve(sc2, [], existing={'GAS': 60.0}, fixed=True)
    assert sum(r.flexibility['farms']['shortage']) > 39.0 * 24 and sum(r.flexibility['homes']['shortage']) < 1e-6


def test_non_electric_substance_chain():
    """River water is treated into potable water for a demand; no electricity anywhere."""
    T = 24
    d = {x.name: x for x in [
        Design('RIVER', 'renewable', annual_cost=0.0, loc='A', profile='flow', form_out='raw', max_cap=1e6),
        Design('TREAT', 'convert', annual_cost=5_000, var_cost=0.1, form_in='raw', form_out='potable', eff=0.95, loc='A', max_cap=1e6),
        Design('TANK', 'store', annual_cost=500, form='potable', loc='A', duration_h=12.0, eta_c=1.0, eta_d=1.0, max_cap=1e6)]}
    flow = [1.0] * 12 + [0.2] * 12
    sc = Scenario(periods=T, hours=1.0, demand_D=[0.0] * T, hub_energy=0.0, hub_max_rate=0.0, profiles={'flow': flow}, fuel_price_R=0.0,
                  voll=1_000.0, designs=d, extra_demand={}, demands=(Demand('city', 'A', tuple([40.0] * T), 'utility', 'municipal', form='potable'),),
                  locations=('A', 'D'), fuel_sites=())
    r = solve(sc, [], existing={'RIVER': 100.0, 'TREAT': 70.0, 'TANK': 600.0}, fixed=True)
    assert sum(r.unmet_extra[('potable', 'A')]) < 1e-6                       # night demand served from the tank
    assert max(r.activity['TANK']['level']) > 1.0
    rule = Requirement('reuse_share', '>=', lhs=((1.0, Measure('flow', ('TREAT',))),), rhs=((0.5, Measure('demand', form='potable')),))
    tr = Trajectory(K=1, fuel_price=[0.0], demand_mult=[1.0]); pm = Params(life={n: 10 for n in d}, fom_share=0.0, aging=0.0)
    w = solve_window(sc, tr, pm, 0, 0, [], institutions=[rule])
    assert w['institutions'][0]['violation'] <= 1e-6


def test_audit_holds_for_every_rule():
    sc, tr, pm = two_node()
    rules = [Requirement('share', '>=', lhs=((1.0, Measure('flow', ('PV',))),), rhs=((0.1, Measure('demand')),)),
             Requirement('min_gas', '>=', lhs=((1.0, Measure('flow', ('GAS',))),), bound=5.0, per_period=True),
             Requirement('imports', '<=', lhs=((1.0, Measure('boundary', locations=('A',))),), bound=24 * 60.0, escape_price=500.0),
             Charge('tax', terms=((2.0, Measure('flow', ('GAS', 'GAS_D'))),))]
    r = solve_window(sc, tr, pm, 0, 0, [], institutions=rules)
    assert all(x['violation'] <= 1e-6 for x in r['institutions'])


def test_lagged_process_rule():
    assert lagged({2030: 4000.0, 2045: 16000.0}, 3) == {2033: 4000.0, 2048: 16000.0}


def _water_store_world(**kw):
    T = 10
    d = {x.name: x for x in [
        Design('RIVER', 'renewable', annual_cost=0.0, loc='A', profile='flow', form_out='water', max_cap=1e6),
        Design('RES', 'store', annual_cost=0.0, form='water', loc='A', duration_h=1.0, eta_c=1.0, eta_d=1.0, max_cap=1e6)]}
    flow = [50.0] * 5 + [0.0] * 5
    return Scenario(periods=T, hours=1.0, demand_D=[0.0] * T, hub_energy=0.0, hub_max_rate=0.0, profiles={'flow': flow}, fuel_price_R=0.0,
                    voll=1_000.0, designs=d, extra_demand={}, demands=(Demand('town', 'A', tuple([20.0] * T), 'u', 'm', form='water'),),
                    locations=('A', 'D'), fuel_sites=(), **kw)


def test_non_cyclic_store_starts_at_initial_level_and_values_the_end():
    sc = _water_store_world(store_initial={'RES': 30.0}, store_terminal_value={'RES': 1.0})
    r = solve(sc, [], existing={'RIVER': 1.0, 'RES': 500.0}, fixed=True)
    lv = r.activity['RES']['level']
    assert abs(lv[0] - 30.0) < 1e-6 and sum(r.unmet_extra[('water', 'A')]) < 1e-6   # wet days fill, dry days draw
    sc0 = _water_store_world(store_initial={'RES': 30.0})                             # no terminal value: nothing kept beyond need
    sc1 = _water_store_world(store_initial={'RES': 30.0}, store_terminal_value={'RES': 1.0})
    e0 = solve(sc0, [], existing={'RIVER': 1.0, 'RES': 500.0}, fixed=True).activity['RES']['end'][0]
    e1 = solve(sc1, [], existing={'RIVER': 1.0, 'RES': 500.0}, fixed=True).activity['RES']['end'][0]
    assert e1 >= e0 - 1e-6 and e1 > 0


def test_fixed_activity_commitments_hold():
    sc = _water_store_world(store_initial={'RES': 100.0}, fixed_activity={('RES', 'discharge'): {7: 0.0, 8: 5.0}})
    r = solve(sc, [], existing={'RIVER': 1.0, 'RES': 500.0}, fixed=True)
    d = r.activity['RES']['discharge']
    assert abs(d[7]) < 1e-6 and abs(d[8] - 5.0) < 1e-6
