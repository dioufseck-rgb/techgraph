"""Verification tests: hand-solved cases, dual prices, storage accounting, balances."""
from dataclasses import replace
import pytest

from techgraph.catalog import default_scenario, default_designs, Design, Scenario
from techgraph.model import solve, check_balances
from techgraph.analysis import (incumbent, operating_prices, screen, value,
                                INCUMBENT_LANDSCAPE, CANDIDATES)

D365 = 365.0


def tiny(designs, periods=1, hours=1.0, demand=(100.0,)):
    return Scenario(periods=periods, hours=hours, demand_D=list(demand),
                    hub_energy=0.0, hub_max_rate=0.0,
                    profiles={"solar_D": [0.5] * periods}, fuel_price_R=25.0,
                    voll=3000.0, designs={d.name: d for d in designs})


def fuel_chain():
    base = default_designs()
    return [replace(base["GEN_D"]), replace(base["FUEL_TRANS"], fixed_cost=0.0)]


def test_hand_solved_single_period():
    sc = tiny(fuel_chain())
    r = solve(sc, sc.designs.keys())
    assert r.status == "Optimal"
    g, ft = sc.designs["GEN_D"], sc.designs["FUEL_TRANS"]
    flow = 100.0 / g.eff / (1 - ft.loss)          # MW_th sent from R
    expected = (100.0 * g.annual_cost / D365 + flow * ft.annual_cost / D365
                + 25.0 * flow + g.var_cost * 100.0 + ft.var_cost * flow)
    assert r.objective == pytest.approx(expected, rel=1e-6)
    assert not check_balances(sc, r)


def test_dual_equals_chain_marginal_cost():
    sc = tiny(fuel_chain())
    r = solve(sc, [], existing={"GEN_D": 150.0, "FUEL_TRANS": 500.0}, fixed=True)
    g, ft = sc.designs["GEN_D"], sc.designs["FUEL_TRANS"]
    expected = g.var_cost + (25.0 + ft.var_cost) / (1 - ft.loss) / g.eff
    assert r.prices[("elec", "D", 0)] == pytest.approx(expected, rel=1e-6)
    assert r.prices[("fuel", "R", 0)] == pytest.approx(25.0, rel=1e-6)


def test_storage_is_cyclic_and_lossy():
    store = Design("STORE_D", "store", annual_cost=10_000, form="elec", loc="D",
                   duration_h=2.0, eta_c=0.9, eta_d=0.9)
    solar = Design("SOLAR_D", "renewable", annual_cost=50_000, loc="D", profile="solar_D")
    sc = tiny([store, solar], periods=2, hours=4.0, demand=(0.0, 50.0))
    sc.profiles["solar_D"] = [0.8, 0.0]
    r = solve(sc, sc.designs.keys())
    assert r.status == "Optimal" and sum(r.unmet_D) == pytest.approx(0.0, abs=1e-6)
    ser = r.activity["STORE_D"]
    charged = sum(ser["charge"]) * sc.hours
    discharged = sum(ser["discharge"]) * sc.hours
    assert discharged == pytest.approx(0.81 * charged, rel=1e-6)
    assert not check_balances(sc, r)


def test_balances_hold_for_reference_systems():
    sc = default_scenario()
    for land in (sc.designs.keys(), INCUMBENT_LANDSCAPE):
        r = solve(sc, land)
        assert r.status == "Optimal"
        assert not check_balances(sc, r)


def test_values_are_nonnegative_and_empty_bundle_is_zero():
    sc = replace(default_scenario(), fuel_price_R=60.0)
    existing = incumbent(default_scenario()).capacity
    v0, _ = value(sc, existing, INCUMBENT_LANDSCAPE, [])
    assert v0 == pytest.approx(0.0, abs=1e-3)
    for c in CANDIDATES:
        v, _ = value(sc, existing, INCUMBENT_LANDSCAPE, [c])
        assert v >= -1e-3


def test_screen_treats_unreachable_states_as_worthless():
    sc = default_scenario()
    priced = operating_prices(sc, incumbent(sc).capacity)
    assert ("elec", "R", 0) not in priced.prices
    s = screen(sc, priced, ["LINE_RH", "WIND_R"])
    for name in ("LINE_RH", "WIND_R"):
        assert s[name] == pytest.approx(-sc.designs[name].annual_cost / D365, rel=1e-9)


def test_link_templates_match_stage1_lines():
    from techgraph.spatial import link_designs
    L = link_designs({"R": (0, 0), "H": (200, 0), "D": (250, 0)}, pipes=False)
    assert L["LINE_H_R"].annual_cost == pytest.approx(40_000, rel=0.01)
    assert L["LINE_D_H"].annual_cost == pytest.approx(15_000, rel=0.01)
    assert L["LINE_H_R"].fixed_cost == pytest.approx(4_000_000, rel=0.01)


def test_spatial_world_balances():
    from techgraph.spatial import s2_world
    sc = s2_world(1.0, 1.0, 25.0)
    r = solve(sc, sc.designs.keys())
    assert r.status == "Optimal"
    assert not check_balances(sc, r, tol=1e-3)


def test_stage2_one_epoch_matches_stage1():
    from techgraph.dynamic import Trajectory, Params, solve_window
    sc = default_scenario()
    traj = Trajectory(K=1, fuel_price=[25.0], demand_mult=[1.0], discount=1.0)
    prm = Params(life={n: 10 for n in sc.designs}, aging=0.0)
    s = solve_window(sc, traj, prm, 0, 0, [])
    assert s["objective"] == pytest.approx(solve(sc, sc.designs.keys()).objective, rel=1e-6)


def test_introduction_requires_a_build():
    """A new design type cannot be 'introduced' without building at least one unit,
    and at most m new types can be introduced per epoch (closes the staging loophole)."""
    from techgraph.dynamic import Trajectory, Params, solve_window
    from techgraph.stage2 import LIFE, base_trajectory, incumbent_history
    sc = default_scenario()
    traj = base_trajectory()
    prm = Params(life=LIFE)
    sol = solve_window(sc, traj, prm, 0, traj.K - 1, incumbent_history(sc), m_new=1)
    installed = {v.design for v in incumbent_history(sc)}
    for k in range(traj.K):
        new_types = [n for (n, v), x in sol["build"].items() if v == k and x > 1e-4 and n not in installed]
        assert len(new_types) <= 1
        installed |= set(new_types)


def test_renaming_a_design_changes_nothing():
    """Representation invariance: the label of a design must not affect the optimum."""
    from dataclasses import replace
    sc = default_scenario()
    r1 = solve(sc, sc.designs.keys())
    d = {("X_" + k if k == "LINE_HD" else k): (replace(v, name="X_" + k) if k == "LINE_HD" else v)
         for k, v in sc.designs.items()}
    sc2 = replace(sc, designs=d)
    r2 = solve(sc2, sc2.designs.keys())
    assert r1.objective == pytest.approx(r2.objective, rel=1e-6)


def test_architecture_distance():
    from techgraph.metrics import composition, distance
    a = {"SOLAR_R": 50, "SOLAR_R_G2": 50}; b = {"SOLAR_R_G2": 100}
    assert distance(composition(a, "design"), composition(b, "design")) == pytest.approx(0.5)
    assert distance(composition(a), composition(b)) == pytest.approx(0.0)
