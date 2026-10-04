import math
import pytest
from techgraph.demand_geometry import make_demand_geometry_world,gini
from techgraph.measurement.demand import gini as canonical_gini,demand_state
from techgraph.measurement.network import graph_metrics as canonical_graph_metrics
from techgraph.measurement.architecture import topology_distance
from techgraph.measurement.schema import standard_run_measurement
from techgraph.experiment_contract import ExperimentContract,validate_contract
from techgraph.network_experiments import execute
from run_demand_sensitivity import graph_metrics as legacy_entry_graph_metrics


def test_gini_canonicalized_without_behavior_change():
    x=[0,1,3,7,9]
    assert gini(x)==pytest.approx(canonical_gini(x),abs=0)


def test_demand_state_reproduces_generator_target_state():
    w=make_demand_geometry_world(6,0,'rich',K=8,scale=1.2,concentration=.3,placement='away',primary_share=.65,transition_start=2,transition_end=4)
    got=demand_state(w.scenario,w.trajectory,7)
    expected=w.metadata['demand_geometry']['target_state']
    assert got['total']==pytest.approx(expected['total'])
    assert got['gini']==pytest.approx(expected['gini'])
    assert list(got['centroid'])==pytest.approx(expected['centroid'])


def test_graph_metric_compatibility_entry_point():
    w=make_demand_geometry_world(6,0,'rich',K=3,scale=1.,concentration=0.,placement='toward',primary_share=.8,transition_start=0,transition_end=1)
    r=execute(w,1,time_limit=8.)
    a,ae=legacy_entry_graph_metrics(w,r['epochs'][0],None)
    b,be=canonical_graph_metrics(w,r['epochs'][0],None)
    assert ae==be
    assert a.keys()==b.keys()
    for k in a:
        if isinstance(a[k],float):assert a[k]==pytest.approx(b[k],abs=1e-12)
        else:assert a[k]==b[k]


def test_standard_schema_preserves_time_series_and_solver_state():
    w=make_demand_geometry_world(6,1,'rich',K=3,scale=.8,concentration=.15,placement='toward',primary_share=.9,transition_start=0,transition_end=1)
    r=execute(w,1,time_limit=8.)
    m=standard_run_measurement(w,r).manifest()
    assert m['schema_version']=='1.0'
    assert len(m['epochs'])==3
    assert m['solver']['calls']==len(r['solver_log'])
    assert all('forcing' in e and 'network' in e for e in m['epochs'])


def test_experiment_contract_requires_falsifier_and_metrics():
    good=ExperimentContract('T8','h','t','c',('network.edge_turnover',),'f','site graph')
    assert validate_contract(good) is good
    with pytest.raises(ValueError):
        validate_contract(ExperimentContract('T8','h','t','c',(),'', 'site graph'))


def test_topology_distance_is_explicit_jaccard():
    assert topology_distance({('A','B')},{('A','B')})==0
    assert topology_distance({('A','B')},{('B','C')})==1
    assert topology_distance({('A','B'),('B','C')},{('B','C'),('C','D')})==pytest.approx(2/3)


def test_historical_architecture_metric_entry_points_use_canonical_math():
    from techgraph.metrics import composition,distance
    from techgraph.measurement.architecture import share_composition,share_distance
    values={'SOLAR_R':2.,'SOLAR_R_G2':1.,'GEN_D':3.}
    assert composition(values,'design')==share_composition(values)
    assert composition(values,'family')==share_composition(values,{'SOLAR_R':'solar_remote','SOLAR_R_G2':'solar_remote','GEN_D':'fuel_local'})
    a={'x':.4,'y':.6};b={'x':.1,'z':.9}
    assert distance(a,b)==share_distance(a,b)
