"""Accounting gates. Tests compare independently formulated static/dynamic models."""
from dataclasses import replace
import pytest
from techgraph.catalog import Design, Scenario, default_scenario
from techgraph.dynamic import Trajectory, Params, Vintage, solve_window, run_policy, path_cost
from techgraph.model import solve
from techgraph.stage2 import capital_by_epoch
from techgraph.robustness import two_day_lull


def stationary(sc, K=1):
    return Trajectory(K, [sc.fuel_price_R] * K, [1.0] * K, discount=1.0)


def fuel_world(days=1, renewable=False):
    d = Design('G', 'convert', 36500.0, fixed_cost=3650.0, var_cost=3.0,
               form_in='fuel', form_out='elec', loc='D', eff=0.5, max_cap=200.0)
    if renewable:
        d = Design('G', 'renewable', 36500.0, fixed_cost=3650.0, var_cost=7.0,
                   loc='D', profile='flat', max_cap=200.0)
    return Scenario(periods=days, hours=24.0, days=days, demand_D=[10.0] * days,
                    hub_energy=0.0, hub_max_rate=0.0, profiles={'flat': [1.0] * days},
                    fuel_price_R=25.0, voll=3000.0, designs={'G': d},
                    locations=('D',), fuel_sites=('D',))


@pytest.mark.parametrize('factory', [default_scenario, two_day_lull], ids=['one-day','two-day-lull'])
def test_matched_static_dynamic(factory):
    sc = factory(); tr = stationary(sc); prm = Params({n: 10 for n in sc.designs}, aging=0)
    stat = solve(sc, sc.designs)
    dyn = solve_window(sc, tr, prm, 0, 0, [])
    assert dyn['status'] == stat.status == 'Optimal'
    assert dyn['objective'] == pytest.approx(stat.objective, rel=1e-7)


@pytest.mark.parametrize('days', [1, 2, 3])
def test_capital_ledger_arithmetic(days):
    sc = fuel_world(days); tr = stationary(sc); prm = Params({'G': 10}, fom_share=0.2)
    run = {'epochs': [{'builds': {'G': 1.0}}]}
    assert capital_by_epoch(sc, tr, prm, run)[0] == pytest.approx(days * (80 + 10))


def test_duplicate_block_doubles_dynamic_cost_without_interday_storage():
    one, two = fuel_world(1), fuel_world(2)
    def get(sc):
        return solve_window(sc, stationary(sc), Params({'G': 10}, aging=0), 0, 0, [])
    a, b = get(one), get(two)
    assert b['objective'] == pytest.approx(2 * a['objective'], rel=1e-8)
    assert b['epochs'][0]['capacity']['G'] == pytest.approx(a['epochs'][0]['capacity']['G'])


@pytest.mark.parametrize('days', [1, 2])
def test_inherited_maintenance_days_and_age(days):
    sc = fuel_world(days); tr = stationary(sc)
    prm = Params({'G': 10}, fom_share=0.2, aging=0.1)
    hist = [Vintage('G', -2, 10, 10, 36500, 3650, 10)]
    sol = solve_window(sc, tr, prm, 0, 0, hist, forbid=('G',))
    e = sol['epochs'][0]
    assert e['capacity']['G'] == pytest.approx(10)
    assert e['capital'] == pytest.approx(0)
    assert e['fom'] == pytest.approx(days * 0.2 * 36500 / 365 * 10 * 1.2)


@pytest.mark.parametrize('days', [1, 2])
def test_renewable_variable_cost_matches_static(days):
    sc = fuel_world(days, renewable=True); tr = stationary(sc)
    prm = Params({'G': 10}, aging=0)
    a = solve(sc, sc.designs); b = solve_window(sc, tr, prm, 0, 0, [])
    assert b['objective'] == pytest.approx(a.objective, rel=1e-8)


def test_raw_rolling_policy_counts_prior_capital_without_summarize():
    sc = fuel_world(); tr = stationary(sc, K=3); prm = Params({'G': 10}, aging=0)
    run = run_policy(sc, tr, prm, [], horizon=1)
    expected = capital_by_epoch(sc, tr, prm, run)
    assert [e['capital'] for e in run['epochs']] == pytest.approx(expected)
