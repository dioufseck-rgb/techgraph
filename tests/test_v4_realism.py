"""Tests for the v4 opt-in realism mechanisms."""
import warnings, math
from dataclasses import replace
import numpy as np
import pytest
warnings.filterwarnings('ignore')
from techgraph.realism import (RealismConfig, forecast_trajectory, _forecast_series, apply_bins,
                               apply_lumps, add_corridors, bin_profile)
from techgraph.dynamic import Trajectory, solve_window
from techgraph.stateful import StatefulCandidates, StateConfig
from techgraph.variation import Candidate
from techgraph.accounting import _realism_replay


def test_default_config_is_default():
    assert RealismConfig().validate().is_default()
    with pytest.raises(ValueError): RealismConfig(bins=0).validate()
    with pytest.raises(ValueError): RealismConfig(forecast='magic').validate()


def test_forecasts_only_replace_future_epochs():
    tr = Trajectory(10, [0.]*10, [1.]*10, demand_scale={'d': [1, 1.2, 1.1, 1.3, 1.25, .9, .8, 1, 1, 1]})
    f = forecast_trajectory(tr, 4, 7, 'ar1')
    assert f.demand_scale['d'][:5] == tr.demand_scale['d'][:5]
    assert f.demand_scale['d'][8:] == tr.demand_scale['d'][8:]
    assert forecast_trajectory(tr, 4, 7, 'oracle') is tr
    assert _forecast_series([2., 2., 2., 2.], 3, 'ar1') == pytest.approx([2., 2., 2.])
    assert _forecast_series([1., 2., 3., 4., 5.], 2, 'holt')[1] > 5


def test_bins_preserve_mean_demand_and_hours():
    from demand_sweep import make_base
    w = make_base(300, 72)
    sc = apply_bins(w.scenario, 4, .3)
    assert sc.periods == 4 and sc.hours == pytest.approx(.25)
    for a, b in zip(w.scenario.flow_system.demands, sc.flow_system.demands):
        assert sc.hours * sum(b.rates) == pytest.approx(w.scenario.hours * sum(a.rates))
    assert np.mean(bin_profile(4, .3)) == pytest.approx(1.)


def test_lumps_keep_cost_at_reference_capacity():
    from demand_sweep import make_base
    sc = make_base(300, 72).scenario
    lumped = apply_lumps(sc, .3, 2.)
    for n, d in sc.designs.items():
        if d.kind == 'process':
            e = lumped.designs[n]
            assert e.annual_cost * 2. + e.fixed_cost == pytest.approx(d.annual_cost * 2. + d.fixed_cost)


def test_corridor_caps_joint_transport_flow():
    from demand_sweep import make_base
    w = make_base(301, 72, RealismConfig(corridors=True))
    members = w.realism_runtime['corridors']
    assert members and all(c.startswith('C_') for c in members)
    sol = solve_window(w.scenario, w.trajectory, w.params, 0, 0, w.history, stocks=w.stocks,
                       realizability=w.realizability, expectations='static', time_limit=30.,
                       extras={'corridors': {'members': members, 'congestion': (1., 0.)}})
    e = sol['epochs'][0]
    for c, ms in members.items():
        used = sum(e['throughput'].get(m, 0.) for m in ms)
        assert used <= e['capacity'].get(c, 0.) + 1e-6


def test_relocation_fix_moves_readiness_to_destination():
    from demand_sweep import make_base
    w = make_base(300, 72)
    parent = next(n for n, d in w.scenario.designs.items() if n.startswith('X') and len({p.location for p in d.input_ports+d.output_ports}) == 1)
    d = w.scenario.designs[parent]; origin = d.input_ports[0].location
    dest = next(l for l in w.scenario.locations if l != origin)
    moved = replace(d, name='G_TEST', input_ports=tuple(replace(p, location=dest) for p in d.input_ports),
                    output_ports=tuple(replace(p, location=dest) for p in d.output_ports))
    c = Candidate(moved, 'generic', (parent,), 'relocation', 1, 0, 5, {'destination': dest})
    sc = replace(w.scenario, designs={**w.scenario.designs, 'G_TEST': moved})
    for fix, site in ((False, origin), (True, dest)):
        ctx = StatefulCandidates(StateConfig(relocation_fix=fix))
        _, rs = ctx.extend(sc, w.trajectory, w.params, w.realizability, [c], 1)
        assert all(cap.split('_')[1] == site for cap in rs.requirements['G_TEST'].operate)


def test_switching_replay_matches_definition():
    class D:  # minimal design stand-ins
        def __init__(s, kind): s.kind = kind
    class S:
        hours = 1.
        designs = {'a': D('process'), 'b': D('process'), 'IN': D('sink')}
    run = {'realism_config': {'switching_cost': .5, 'congestion': [1., 0.]},
           'epochs': [{'throughput': {'a': 2., 'IN': 1.}, 'capacity': {}},
                      {'throughput': {'a': 1., 'b': 1., 'IN': 5.}, 'capacity': {}}]}
    assert _realism_replay(S, run, 0) == (0., 0.)
    assert _realism_replay(S, run, 1)[0] == pytest.approx(.5 * (1 + 1))


def test_defaults_reproduce_frozen_v3_history():
    from run_demand_sweep import execute
    p = execute(dict(seed=300, treatment='constant', epochs=72, horizon=4))
    assert p['result']['audit']['all_in_objective'] == pytest.approx(1874.7074729822084, rel=1e-12)
