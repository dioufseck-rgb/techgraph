from dataclasses import replace
import pytest
from techgraph.catalog import Design, default_scenario
from techgraph.dynamic import Params, Trajectory, solve_window, run_policy, path_cost, solve_window_stochastic
from techgraph.accounting import independent_path_ledger, capital_charges_by_epoch, annual_to_block
from techgraph.analysis import operating_prices, screen
from test_accounting_regression import fuel_world, stationary


@pytest.mark.parametrize('days', [1,2])
@pytest.mark.parametrize('horizon', [1,2,99])
def test_independent_replay(days, horizon):
    sc=fuel_world(days); tr=stationary(sc, K=4); tr.discount=0.93
    prm=Params({'G':2}, aging=0.1)
    run=run_policy(sc,tr,prm,[],horizon=horizon)
    ledger=independent_path_ledger(sc,tr,prm,run)
    assert ledger['path_cost'] == pytest.approx(path_cost(tr,run),rel=1e-9)
    for a,b in zip(ledger['epochs'],run['epochs']):
        for key in ['capital','fom','ops_cost','unmet_MWh','emissions']:
            assert a[key] == pytest.approx(b[key],rel=1e-8,abs=1e-6)
    if horizon>=tr.K:
        assert ledger['path_cost'] == pytest.approx(run['window_objective'],rel=1e-9)


def test_replay_ignores_reported_cost_fields():
    sc=fuel_world(2); tr=stationary(sc, K=3); prm=Params({'G':2})
    run=run_policy(sc,tr,prm,[],horizon=1)
    correct=independent_path_ledger(sc,tr,prm,run)['path_cost']
    for e in run['epochs']:
        e['capital']=e['fom']=e['ops_cost']=-999
        for state in e['operating_states']: state['ops_cost']=-999
    assert independent_path_ledger(sc,tr,prm,run)['path_cost']==pytest.approx(correct)


def test_retirement_does_not_cancel_committed_capital():
    sc=fuel_world()
    solar=Design('S','renewable',3650,loc='D',profile='flat',max_cap=100)
    sc=replace(sc,designs=dict(sc.designs,S=solar))
    tr=stationary(sc,K=3);tr.avail_from={'S':1}
    prm=Params({'G':10,'S':10},aging=0)
    run=run_policy(sc,tr,prm,[],horizon=99)
    assert run['epochs'][0]['builds']['G']>9.9
    assert run['epochs'][1]['capacity']['G']<1e-6
    cap=capital_charges_by_epoch(sc,tr,prm,run)
    assert cap[1]>=cap[0]
    assert independent_path_ledger(sc,tr,prm,run)['path_cost']==pytest.approx(run['window_objective'])


def test_contingency_replay_and_saved_state_dispatch():
    sc=fuel_world(2);tr=stationary(sc,K=2);prm=Params({'G':10},aging=0)
    cont=[{'name':'generator_loss','p':0.05,'fail':['G']}]
    run=run_policy(sc,tr,prm,[],horizon=99,contingencies=cont)
    states=run['epochs'][0]['operating_states']
    assert len(states)==2 and states[1]['name']=='generator_loss'
    assert states[1]['unmet_MWh']==pytest.approx(480)
    assert 'G' not in states[1]['throughput']
    ledger=independent_path_ledger(sc,tr,prm,run)
    assert ledger['path_cost']==pytest.approx(run['window_objective'],rel=1e-9)
    assert run['epochs'][0]['unmet_MWh']==pytest.approx(24)


@pytest.mark.parametrize('probabilities', [[-0.1],[1.1],[0.7,0.6]])
def test_bad_contingency_weights_rejected(probabilities):
    sc=fuel_world();tr=stationary(sc);prm=Params({'G':10})
    with pytest.raises(ValueError):
        solve_window(sc,tr,prm,0,0,[],contingencies=[{'p':p} for p in probabilities])


@pytest.mark.parametrize('days',[0,-1,float('nan')])
def test_invalid_representative_days_rejected(days):
    sc=fuel_world();sc.days=days
    with pytest.raises(ValueError): annual_to_block(sc)


def test_identical_scenarios_stochastic_equals_deterministic():
    sc=fuel_world(2);tr=stationary(sc,K=3);prm=Params({'G':10})
    a=solve_window(sc,tr,prm,0,2,[],m_new=1)
    b=solve_window_stochastic(sc,[tr,tr],[0.4,0.6],prm,0,2,[],m_new=1)
    assert a['objective']==pytest.approx(b['objective'],rel=1e-8)


def test_full_horizon_not_costlier_than_feasible_rolling_path():
    sc=fuel_world(2);tr=stationary(sc,K=4);tr.fuel_price=[25,35,50,70]
    prm=Params({'G':3})
    full=run_policy(sc,tr,prm,[],horizon=99)
    for horizon in [1,2]:
        rolling=run_policy(sc,tr,prm,[],horizon=horizon)
        assert path_cost(tr,full)<=path_cost(tr,rolling)+1e-5
