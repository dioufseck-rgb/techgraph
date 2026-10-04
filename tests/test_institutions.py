"""Tests for the opt-in institutions module."""
import os
os.environ.setdefault('TECHGRAPH_BACKEND', 'scipy')
from techgraph.catalog import Design, Scenario
from techgraph.dynamic import Trajectory, Params, Vintage, solve_window
from techgraph.institutions import EnergyShare, CapacityQuantity, AccreditedCapacity

SOL = [0, 0, 0, 0, 0, .1, .3, .5, .7, .8, .8, .8, .8, .8, .7, .5, .3, .1, 0, 0, 0, 0, 0, 0]


def world():
    d = {x.name: x for x in [
        Design('GAS', 'convert', annual_cost=100_000, var_cost=30.0, form_in='fuel', form_out='elec', loc='A', max_cap=1e6),
        Design('PV', 'renewable', annual_cost=150_000, loc='A', profile='pv', max_cap=1e6),
        Design('BAT', 'store', annual_cost=30_000, form='elec', loc='A', duration_h=4.0, eta_c=.9, eta_d=.9, max_cap=1e6)]}
    sc = Scenario(periods=24, hours=1.0, demand_D=[0.0] * 24, hub_energy=0.0, hub_max_rate=0.0, profiles={'pv': SOL},
                  fuel_price_R=0.0, voll=5_000.0, designs=d, extra_demand={'A': [100.0] * 24}, locations=('A', 'D'),
                  fuel_sites=('A',))
    return sc, Trajectory(K=1, fuel_price=[0.0], demand_mult=[1.0]), Params(life={n: 10 for n in d}, fom_share=0.0, aging=0.0)


def test_no_institutions_is_unchanged():
    sc, tr, pm = world()
    a = solve_window(sc, tr, pm, 0, 0, [])
    b = solve_window(sc, tr, pm, 0, 0, [], institutions=[])
    assert abs(a['objective'] - b['objective']) < 1e-6 and 'institutions' not in b


def test_share_is_met_and_priced():
    sc, tr, pm = world()
    base = solve_window(sc, tr, pm, 0, 0, [])
    assert base['epochs'][0]['builds'].get('PV', 0.0) < 1e-6          # PV is not economic on its own
    r = solve_window(sc, tr, pm, 0, 0, [], institutions=[EnergyShare('rps', ('PV',), 0.2)])
    pv = r['epochs'][0]['throughput']['PV']
    assert pv >= 0.2 * 2400 - 1e-6
    inst = r['institutions'][0]
    assert inst['implicit_price'] > 0 and inst['shortfall'] == 0.0


def test_escape_valve_caps_the_price():
    sc, tr, pm = world()
    r = solve_window(sc, tr, pm, 0, 0, [], institutions=[EnergyShare('rps', ('PV',), 0.2, escape_price=5.0)])
    inst = r['institutions'][0]
    assert inst['shortfall'] > 0 and abs(inst['implicit_price'] - 5.0) < 1e-6


def test_tiers_are_used_before_the_escape():
    sc, tr, pm = world()
    r = solve_window(sc, tr, pm, 0, 0, [], institutions=[EnergyShare('rps', ('PV',), 0.2, escape_price=50.0,
                                                                       escape_tiers=((5.0, 0.25),))])
    inst = r['institutions'][0]
    assert abs(inst['tier_use'][0] - 0.25 * 0.2 * 2400) < 1e-6


def test_quantity_and_accredited_capacity():
    sc, tr, pm = world()
    r = solve_window(sc, tr, pm, 0, 0, [], institutions=[CapacityQuantity('storage', ('BAT',), 50.0),
                                                          AccreditedCapacity('adequacy', {'GAS': 1.0, 'BAT': 0.125}, margin=0.15)])
    cap = r['epochs'][0]['capacity']
    assert cap['BAT'] >= 50.0 - 1e-6
    assert cap['GAS'] + 0.125 * cap['BAT'] >= 115.0 - 1e-6


def test_locational_requirement_uses_local_peak():
    sc, tr, pm = world()
    sc.extra_demand['B'] = [50.0] * 24
    sc = __import__('dataclasses').replace(sc, locations=('A', 'B', 'D'))
    sc.designs['LINE'] = Design('LINE', 'transport', annual_cost=10_000, form='elec', loc_from='A', loc_to='B', max_cap=1e6)
    pm = Params(life={n: 10 for n in sc.designs}, fom_share=0.0, aging=0.0)
    r = solve_window(sc, tr, pm, 0, 0, [], institutions=[AccreditedCapacity('deliver_B', {'LINE': 1.0}, margin=0.2, locations=('B',))])
    assert r['epochs'][0]['capacity']['LINE'] >= 60.0 - 1e-6


def test_demands_equal_legacy_extra_demand():
    from dataclasses import replace
    from techgraph.demands import Demand
    sc, tr, pm = world()
    a = solve_window(sc, tr, pm, 0, 0, [])
    sc2 = replace(sc, extra_demand={}, demands=(Demand('res', 'A', tuple([60.0] * 24), 'util', 'residential'),
                                                Demand('dc', 'A', tuple([40.0] * 24), 'coop', 'data_center')))
    b = solve_window(sc2, tr, pm, 0, 0, [])
    assert abs(a['objective'] - b['objective']) < 1e-6


def test_share_base_by_owner():
    from dataclasses import replace
    from techgraph.demands import Demand, shares
    sc, tr, pm = world()
    sc2 = replace(sc, extra_demand={}, demands=(Demand('res', 'A', tuple([60.0] * 24), 'util', 'residential'),
                                                Demand('dc', 'A', tuple([40.0] * 24), 'coop', 'data_center')))
    assert abs(shares(sc2, 'owner', 'energy')['util'] - 0.6) < 1e-12
    r = solve_window(sc2, tr, pm, 0, 0, [], institutions=[EnergyShare('rps', ('PV',), 0.2, base_owners=('util',))])
    assert abs(r['epochs'][0]['throughput']['PV'] - 0.2 * 60 * 24) < 1e-6
    r2 = solve_window(sc2, tr, pm, 0, 0, [], institutions=[AccreditedCapacity('obl', {'GAS': 1.0}, owners=('coop',))])
    assert r2['epochs'][0]['capacity']['GAS'] >= 40.0 - 1e-6


def _flex_world(**flex):
    from dataclasses import replace
    from techgraph.demands import Demand
    sc, tr, pm = world()
    peaky = tuple([60.0] * 18 + [120.0] * 2 + [60.0] * 4)
    sc2 = replace(sc, extra_demand={}, demands=(Demand('base', 'A', peaky, 'util', 'residential'),
                                                Demand('dc', 'A', tuple([40.0] * 24), 'util', 'data_center', **flex)))
    return sc2, tr, pm


def test_flexibility_off_changes_nothing():
    sc, tr, pm = _flex_world()
    sc2, _, _ = _flex_world(curtail_max_frac=0.5, curtail_budget=0.0)
    a = solve_window(sc, tr, pm, 0, 0, []); b = solve_window(sc2, tr, pm, 0, 0, [])
    assert abs(a['objective'] - b['objective']) < 1e-6


def test_curtailment_respects_budget_and_cuts_capacity():
    from techgraph.model import solve
    sc0, tr, pm = _flex_world()
    sc1, _, _ = _flex_world(curtail_max_frac=0.5, curtail_budget=0.05, curtail_cost=50.0)
    a = solve_window(sc0, tr, pm, 0, 0, []); b = solve_window(sc1, tr, pm, 0, 0, [])
    assert b['epochs'][0]['capacity']['GAS'] < a['epochs'][0]['capacity']['GAS'] - 1.0
    r = solve(sc1, [], existing={'GAS': b['epochs'][0]['capacity']['GAS']}, fixed=True)
    c = r.flexibility['dc']['curtail']
    assert sum(c) <= 0.05 * 40 * 24 + 1e-6 and max(c) <= 20.0 + 1e-6


def test_shifting_is_energy_neutral_within_the_day():
    from techgraph.model import solve
    sc1, tr, pm = _flex_world(shift_frac=0.25, shift_cost=1.0)
    b = solve_window(sc1, tr, pm, 0, 0, [])
    r = solve(sc1, [], existing={'GAS': b['epochs'][0]['capacity']['GAS']}, fixed=True)
    f = r.flexibility['dc']
    assert abs(sum(f['shift_up']) - sum(f['shift_down'])) < 1e-6 and max(f['shift_down']) > 0


def test_adequacy_can_credit_flexible_load():
    sc1, tr, pm = _flex_world(curtail_max_frac=0.5, curtail_budget=0.05, curtail_cost=50.0)
    strict = solve_window(sc1, tr, pm, 0, 0, [], institutions=[AccreditedCapacity('a', {'GAS': 1.0})])
    credit = solve_window(sc1, tr, pm, 0, 0, [], institutions=[AccreditedCapacity('a', {'GAS': 1.0}, credit_flexibility=True)])
    assert strict['epochs'][0]['capacity']['GAS'] >= 160.0 - 1e-6
    assert credit['epochs'][0]['capacity']['GAS'] >= 140.0 - 1e-6 and credit['epochs'][0]['capacity']['GAS'] < 160.0 - 1.0


def test_time_varying_variable_cost():
    from dataclasses import replace
    sc, tr, pm = world()
    shape = tuple([0.5] * 12 + [2.0] * 12)
    d = dict(sc.designs); d['IMP'] = Design('IMP', 'convert', annual_cost=0.0, var_cost=40.0, form_in='fuel', form_out='elec',
                                             loc='A', max_cap=1e6, var_cost_profile='px')
    sc2 = replace(sc, designs=d, profiles=dict(sc.profiles, px=shape))
    pm2 = Params(life={n: 10 for n in d}, fom_share=0.0, aging=0.0)
    from techgraph.model import solve
    r = solve(sc2, [], existing={'GAS': 100.0, 'IMP': 100.0}, fixed=True)
    out = r.activity['IMP']['output']
    assert min(out[:12]) > 99.0 and max(out[12:]) < 1.0      # imports at $20 beat gas at $30; at $80 they do not


def test_cycle_blocks_let_storage_cross_days():
    from dataclasses import replace
    from techgraph.model import solve
    # two days: cheap gas only in day 1, expensive in day 2 (via a priced import); storage helps only if it can carry energy across days
    sc, tr, pm = world()
    T = 48
    d = dict(sc.designs)
    d['IMP'] = Design('IMP', 'convert', annual_cost=0.0, var_cost=1.0, var_cost_profile='px', form_in='fuel', form_out='elec', loc='A', max_cap=1e6)
    d['LONG'] = Design('LONG', 'store', annual_cost=0.0, form='elec', loc='A', duration_h=48.0, eta_c=1.0, eta_d=1.0, max_cap=1e6)
    base = dict(periods=T, demand_D=[0.0] * T, extra_demand={'A': [100.0] * T}, designs=d,
                profiles={'pv': [0.0] * T, 'px': [10.0] * 24 + [500.0] * 24})
    daily = replace(sc, **base, cycle_length=24)
    joint = replace(sc, **base, cycle_blocks=((0, 48),))
    caps = {'IMP': 300.0, 'LONG': 4800.0}
    a = solve(daily, [], existing=caps, fixed=True); b = solve(joint, [], existing=caps, fixed=True)
    assert b.objective < a.objective - 1.0


def test_partial_flexibility_credit():
    sc1, tr, pm = _flex_world(curtail_max_frac=0.5, curtail_budget=0.05, curtail_cost=50.0)
    half = solve_window(sc1, tr, pm, 0, 0, [], institutions=[AccreditedCapacity('a', {'GAS': 1.0}, credit_flexibility=True, flexibility_credit=0.5)])
    g = half['epochs'][0]['capacity']['GAS']
    assert 150.0 - 1e-6 <= g < 160.0 - 1.0        # peak 160 with 20 MW flexible: half credit -> 150


def test_daily_interruption_limit():
    from techgraph.model import solve
    sc1, tr, pm = _flex_world(curtail_max_frac=0.5, curtail_budget=0.5, curtail_cost=1.0, curtail_daily_hours=1.0)
    r = solve(sc1, [], existing={'GAS': 100.0}, fixed=True)
    assert sum(r.flexibility['dc']['curtail']) <= 1.0 * 20.0 + 1e-6


def test_energy_ceiling_share_of_demand():
    from techgraph.institutions import EnergyCeiling
    sc, tr, pm = world()
    free = solve_window(sc, tr, pm, 0, 0, [])
    capped = solve_window(sc, tr, pm, 0, 0, [], institutions=[EnergyCeiling('pv_cap', ('PV',), share_of_demand=0.05)])
    tot = sum(sc.extra_demand['A']) if hasattr(sc, 'extra_demand') and sc.extra_demand else None
    assert capped['epochs'][0]['throughput'].get('PV', 0) <= free['epochs'][0]['throughput'].get('PV', 0) + 1e-6
    if tot: assert capped['epochs'][0]['throughput'].get('PV', 0) <= 0.05 * tot + 1e-3


def test_energy_ceiling_capacity_factor():
    from techgraph.institutions import EnergyCeiling
    sc, tr, pm = world()
    r = solve_window(sc, tr, pm, 0, 0, [], institutions=[EnergyCeiling('gas_cf', ('GAS',), capacity_factor=0.2)])
    cap = r['epochs'][0]['capacity']['GAS']; thr = r['epochs'][0]['throughput'].get('GAS', 0)
    assert thr <= 0.2 * 24 * cap + 1e-3
