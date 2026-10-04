"""Stock feedback, conservation, temporal semantics, and interoperability."""
from copy import deepcopy
from dataclasses import replace
import pytest
from techgraph.stock_examples import residual_world, product_by_design
from techgraph.stocks import StockSpec, StockSystem, audit_stock_run
from techgraph.dynamic import run_policy, solve_window, solve_window_stochastic, path_cost
from techgraph.model import solve, check_balances
from techgraph.flows import (Port, FlowResource, FlowDemand, Destination, FlowSystem,
                              audit_flow_block, impact_ledger, validate_flow_system)
from techgraph.flow_audit import audit_operating_state
from techgraph.accounting import independent_path_ledger
from techgraph.catalog import Design


def run_check(sc, tr, p, h, stocks, horizon=99, **kw):
    run=run_policy(sc,tr,p,h,horizon=horizon,stocks=stocks,**kw)
    audit_stock_run(sc,stocks,run)
    ledger=independent_path_ledger(sc,tr,p,run)
    assert ledger['path_cost']==pytest.approx(path_cost(tr,run),rel=1e-8,abs=1e-7)
    if 'window_objective' in run:
        assert ledger['path_cost']==pytest.approx(run['window_objective'],rel=1e-8,abs=1e-7)
    for e in run['epochs']:
        for state in e['operating_states']:
            audit_flow_block(sc,state['flow'],state['physical']['capacities'])
            audit_operating_state(sc,state)
    return run


@pytest.mark.parametrize('horizon',[1,2,99])
def test_finite_stock_changes_choices_at_unchanged_prices(horizon):
    sc,tr,p,h,s=residual_world()
    r=run_check(sc,tr,p,h,s,horizon)
    assert product_by_design(sc,r,'OLD')==pytest.approx([10,10,0,0,0,0])
    assert [e['stocks']['pile']['stock_end'] for e in r['epochs']]==pytest.approx([2.5,5,5,5,5,5])


@pytest.mark.parametrize('horizon',[1,99])
def test_unbounded_active_stock_recovers_passive_case(horizon):
    sc,tr,p,h,s=residual_world(capacity=None)
    active=run_check(sc,tr,p,h,s,horizon)
    legacy=run_policy(sc,tr,p,h,horizon=horizon)
    assert path_cost(tr,active)==pytest.approx(path_cost(tr,legacy))
    passive=impact_ledger(sc,legacy,block_weights=[1]*tr.K)
    assert active['epochs'][-1]['stocks']['pile']['stock_end']==pytest.approx(passive['final_stocks']['pile'])


@pytest.mark.parametrize('periods',[1,2])
@pytest.mark.parametrize('route',['none','treatment','recovery'])
def test_static_dynamic_equivalence(periods,route):
    sc,tr,p,h,s=residual_world(K=1,periods=periods,initial=2,route=route,holding_charge=.3,terminal_charge=.2)
    a=solve(sc,sc.designs,stocks=s)
    b=solve_window(sc,tr,p,0,0,[],stocks=s)
    assert a.objective==pytest.approx(b['objective'],rel=1e-8,abs=1e-7)
    assert not check_balances(sc,a)
    assert a.stocks['pile']['stock_end']==pytest.approx(b['epochs'][0]['stocks']['pile']['stock_end'])


@pytest.mark.parametrize('horizon',[1,99])
def test_inherited_stock_can_supply_later_production(horizon):
    sc,tr,p,h,s=residual_world(capacity=10,route='recovery',initial=10,recovery_cost=.2,K=3)
    r=run_check(sc,tr,p,[],s,horizon,forbid=('OLD',))
    assert r['epochs'][0]['stocks']['pile']['withdrawals']==pytest.approx([10])
    assert product_by_design(sc,r,'RECOVER')[0]==pytest.approx(5)
    assert r['epochs'][0]['stocks']['pile']['stock_end']==pytest.approx(0)


@pytest.mark.parametrize('horizon',[1,99])
def test_terminal_obligation_and_noncycling_stock(horizon):
    sc,tr,p,h,s=residual_world(route='treatment',terminal_limit=0,treatment_cost=8)
    r=run_check(sc,tr,p,h,s,horizon)
    assert r['epochs'][-1]['stocks']['pile']['stock_end']==pytest.approx(0)
    if horizon==1:
        assert r['epochs'][0]['stocks']['pile']['stock_end']==pytest.approx(2.5)
        assert r['epochs'][-1]['stocks']['pile']['withdrawals']==pytest.approx([5])
    else:
        assert product_by_design(sc,r,'OLD')==pytest.approx([0]*tr.K)


def test_future_global_terminal_limit_does_not_apply_to_short_window():
    sc,tr,p,h,s=residual_world(route='treatment',terminal_limit=0,treatment_cost=8)
    r=solve_window(sc,tr,p,0,0,h,stocks=s)
    assert r['epochs'][0]['stocks']['pile']['stock_end']>2
    assert not r['epochs'][0]['stocks']['pile']['terminal_applies']


def test_terminal_cap_with_no_removal_can_make_myopic_continuation_infeasible():
    sc,tr,p,h,s=residual_world(terminal_limit=0,K=3)
    full=run_check(sc,tr,p,h,s)
    assert product_by_design(sc,full,'OLD')==pytest.approx([0,0,0])
    with pytest.raises(RuntimeError,match='Infeasible'):
        run_policy(sc,tr,p,h,horizon=1,stocks=s)


@pytest.mark.parametrize('weight',[.5,1,2])
def test_explicit_quantity_weights_and_initial_conditions(weight):
    sc,tr,p,h,s=residual_world(capacity=None,initial=2,weight=weight,K=3)
    r=run_check(sc,tr,p,h,s)
    assert [e['stocks']['pile']['stock_end'] for e in r['epochs']]==pytest.approx([2+weight*2.5*(k+1) for k in range(3)])


def test_retention_uses_named_outflow_account():
    sc,tr,p,h,s=residual_world(capacity=None,initial=4,retention=.5,K=3)
    r=run_check(sc,tr,p,h,s)
    assert [e['stocks']['pile']['stock_end'] for e in r['epochs']]==pytest.approx([4.5,4.75,4.875])
    assert [e['stocks']['pile']['natural_loss'] for e in r['epochs']]==pytest.approx([2,2.25,2.375])
    assert r['epochs'][0]['stocks']['pile']['removal_account']=='declared_loss_account'


def test_no_overdraft_and_no_same_period_deposit_borrowing():
    # Demand can be supplied only from a stock; no initial material means infeasibility.
    sc,tr,p,h,s=residual_world(route='recovery',K=1,initial=0)
    sc=replace(sc,flow_system=replace(sc.flow_system,resources=()))
    with pytest.raises(RuntimeError,match='Infeasible'):
        solve_window(sc,tr,p,0,0,[],stocks=s)


def test_zero_capacity_not_a_free_transit_inventory():
    sc,tr,p,h,s=residual_world(capacity=0,route='treatment',K=2)
    r=run_check(sc,tr,p,h,s)
    assert all(abs(x)<1e-7 for e in r['epochs'] for x in e['stocks']['pile']['deposits'])
    assert all(abs(x)<1e-7 for e in r['epochs'] for x in e['stocks']['pile']['withdrawals'])


def test_shared_withdrawal_modules_cannot_double_spend_stock():
    sc,tr,p,h,s=residual_world(capacity=4,route='recovery',initial=4,K=1,recovery_cost=.2)
    ds=dict(sc.designs);ds['EXTRACT2']=replace(ds['EXTRACT'],name='EXTRACT2');sc=replace(sc,designs=ds)
    p=replace(p,life={**p.life,'EXTRACT2':20})
    r=run_check(sc,tr,p,[],s,forbid=('OLD',))
    e=r['epochs'][0]
    assert e['throughput']['EXTRACT']+e['throughput']['EXTRACT2']==pytest.approx(4)
    assert e['stocks']['pile']['stock_end']==pytest.approx(0)


def test_early_retirement_does_not_erase_residual_history():
    sc,tr,p,h,s=residual_world(initial=5,capacity=5)
    r=run_check(sc,tr,p,h,s)
    assert product_by_design(sc,r,'OLD')==pytest.approx([0]*tr.K)
    assert all(e['capacity']['OLD']<1e-7 for e in r['epochs'])
    assert [e['stocks']['pile']['stock_end'] for e in r['epochs']]==pytest.approx([5]*tr.K)


def test_continuation_requires_and_uses_inherited_stock():
    sc,tr,p,h,s=residual_world()
    with pytest.raises(ValueError,match='inherited stock_state'):
        solve_window(sc,tr,p,2,2,h,stocks=s)
    a=solve_window(sc,tr,p,2,2,h,stocks=s,stock_state={'pile':5})
    assert a['epochs'][2]['throughput']['OLD']==pytest.approx(0)
    assert a['epochs'][2]['stocks']['pile']['stock_start']==pytest.approx(5)


def test_holding_and_terminal_cost_replay_ignore_stored_totals():
    sc,tr,p,h,s=residual_world(capacity=None,holding_charge=.1,terminal_charge=.5)
    r=run_check(sc,tr,p,h,s)
    correct=independent_path_ledger(sc,tr,p,r)['path_cost']
    for e in r['epochs']:
        e['stock_cost']=-999
        e['stocks']['pile']['cost']=-999
        e['stocks']['pile']['levels']=[999,999]
    assert independent_path_ledger(sc,tr,p,r)['path_cost']==pytest.approx(correct)
    with pytest.raises(AssertionError):audit_stock_run(sc,s,r)


def test_nonmonetary_impacts_do_not_create_unstated_private_cost():
    sc,tr,p,h,s=residual_world()
    a=run_check(sc,tr,p,h,s)
    dest=dict(sc.flow_system.destinations);dest['pile']=replace(dest['pile'],impact_factors={'burden':12345},bearer='another bearer')
    alt=replace(sc,flow_system=replace(sc.flow_system,destinations=dest))
    b=run_check(alt,tr,p,h,s)
    assert path_cost(tr,a)==pytest.approx(path_cost(tr,b))


def test_high_holding_charge_changes_choices():
    sc,tr,p,h,s=residual_world(capacity=None,holding_charge=10)
    r=run_check(sc,tr,p,h,s)
    assert product_by_design(sc,r,'OLD')==pytest.approx([0]*tr.K)


def test_late_recovery_availability_and_stock_carryover():
    sc,tr,p,h,s=residual_world(capacity=5,route='recovery',access_at=3)
    r=run_check(sc,tr,p,h,s)
    assert r['epochs'][2]['throughput']['CLEAN']>9.9
    assert r['epochs'][3]['throughput']['RECOVER']>0
    assert r['epochs'][3]['stocks']['pile']['stock_start']==pytest.approx(5)


def test_withdrawals_require_active_context():
    sc,tr,p,h,s=residual_world(route='treatment')
    with pytest.raises(ValueError,match='Withdrawal modules'):
        run_policy(sc,tr,p,h)
    with pytest.raises(ValueError,match='Withdrawal modules'):
        solve(sc,sc.designs)


def test_active_stocks_are_pathwise_under_contingencies_and_stochastic_scenarios():
    sc,tr,p,h,s=residual_world()
    r=run_policy(sc,tr,p,h,stocks=s,contingencies=[{'name':'old_loss','p':.1,'fail':['OLD']}])
    assert audit_stock_run(sc,s,r)['passed']
    states=r['epochs'][0]['operating_states']
    assert len(states)==2 and all('pile' in x['stocks'] for x in states)
    assert states[0]['stocks']['pile']['stock_start']==pytest.approx(states[1]['stocks']['pile']['stock_start'])
    b=solve_window_stochastic(sc,[tr,tr],[.5,.5],p,0,2,h,stocks=s)
    assert len(b['scenarios'])==2
    assert all(path['epochs'][2]['stocks']['pile']['stock_end']>=0 for path in b['scenarios'])


def test_passive_ledger_cannot_silently_ignore_active_withdrawals():
    sc,tr,p,h,s=residual_world()
    r=run_check(sc,tr,p,h,s)
    with pytest.raises(ValueError,match='ignore withdrawals'):
        impact_ledger(sc,r,block_weights=[1]*tr.K)


@pytest.mark.parametrize('capacity',[-1,float('nan'),float('inf'),(1,2)])
def test_invalid_stock_caps_rejected(capacity):
    sc,tr,p,h,s=residual_world(capacity=capacity)
    with pytest.raises(ValueError):run_policy(sc,tr,p,h,stocks=s)


@pytest.mark.parametrize('weight',[0,-1,float('nan'),float('inf')])
def test_invalid_quantity_weight_rejected(weight):
    sc,tr,p,h,s=residual_world(weight=weight)
    with pytest.raises(ValueError):run_policy(sc,tr,p,h,stocks=s)


@pytest.mark.parametrize('field,value',[('holding_charge',-1),('terminal_charge',-1),('terminal_limit',-1),('terminal_limit',float('inf'))])
def test_invalid_limits_or_charges(field,value):
    sc,tr,p,h,s=residual_world()
    s=replace(s,stocks={'pile':replace(s.stocks['pile'],**{field:value})})
    with pytest.raises(ValueError):run_policy(sc,tr,p,h,stocks=s)


@pytest.mark.parametrize('state',[{}, {'pile':-1}, {'pile':float('nan')}, {'another':0}])
def test_invalid_initial_state_rejected(state):
    sc,tr,p,h,s=residual_world()
    with pytest.raises(ValueError):run_policy(sc,tr,p,h,stocks=s,stock_state0=state)


def test_stock_form_units_location_and_spill_checked():
    sc,tr,p,h,s=residual_world()
    for spec in [replace(s.stocks['pile'],form='fuel'), replace(s.stocks['pile'],location='elsewhere')]:
        with pytest.raises(ValueError):run_policy(sc,tr,p,h,stocks=replace(s,stocks={'pile':spec}))
    spilled=replace(sc,flow_system=replace(sc.flow_system,spill_forms=('residue',)))
    with pytest.raises(ValueError,match='must be closed'):run_policy(spilled,tr,p,h,stocks=s)


def test_active_stock_must_name_a_stock_destination():
    sc,tr,p,h,s=residual_world()
    s=replace(s,stocks={'landfill':StockSpec('inert','D',5)})
    with pytest.raises(ValueError):run_policy(sc,tr,p,h,stocks=s)


def test_forecast_state_uses_only_applied_first_epoch():
    sc,tr,p,h,s=residual_world(capacity=5)
    r=run_check(sc,tr,p,h,s,horizon=3)
    assert r['epochs'][1]['stocks']['pile']['stock_start']==pytest.approx(2.5)
    assert r['epochs'][2]['stocks']['pile']['stock_start']==pytest.approx(5)


def test_stock_capacity_sequence_binds():
    sc,tr,p,h,s=residual_world(capacity=(0,0,2.5,2.5,5,5))
    r=run_check(sc,tr,p,h,s)
    for k,e in enumerate(r['epochs']):
        assert max(e['stocks']['pile']['levels'])<=s.stocks['pile'].limit(k)+1e-6
    assert product_by_design(sc,r,'OLD')[:2]==pytest.approx([0,0])


def storage_only_world(unit='tonne', reverse=False):
    from techgraph.catalog import Scenario
    from techgraph.dynamic import Trajectory,Params
    form='product' if unit=='tonne' else 'elec'
    activity='tonne/h' if unit=='tonne' else 'MW'
    demands=(10.,0.) if reverse else (0.,10.)
    supply=(0.,10.) if reverse else (10.,0.)
    ds=[Design('IN','sink',8.76,form=form,loc='D',destination='inventory',activity_unit=activity,max_cap=100),
        Design('OUT','withdraw',8.76,form=form,loc='D',destination='inventory',activity_unit=activity,max_cap=100)]
    fs=FlowSystem(form_units={'fuel':'MWh','elec':'MWh','h2':'MWh',**({form:unit})},
                  demands=(FlowDemand('service',form,'D',demands,hard=True),),
                  resources=(FlowResource('supply',form,'D',supply,unit_cost=1.),),
                  destinations={'inventory':Destination(unit,kind='stock')},hard_legacy_service=True)
    sc=Scenario(2,1.,[0.,0.],0.,0.,{},0.,3000.,{d.name:d for d in ds},days=2/24,
                locations=('D',),fuel_sites=(),flow_system=fs)
    tr=Trajectory(1,[0.],[1.],discount=1.);p=Params({d.name:10 for d in ds},aging=0)
    st=StockSystem({'inventory':StockSpec(form,'D',10)},(1.,))
    return sc,tr,p,[],st


@pytest.mark.parametrize('unit',['tonne','MWh'])
def test_chronological_inventory_distinct_from_cyclic_storage(unit):
    sc,tr,p,h,s=storage_only_world(unit)
    r=run_check(sc,tr,p,h,s)
    assert r['epochs'][0]['stocks']['inventory']['levels']==pytest.approx([0,10,0])
    a=solve(sc,sc.designs,stocks=s)
    assert a.objective==pytest.approx(path_cost(tr,r))
    assert not check_balances(sc,a)
    sc,tr,p,h,s=storage_only_world(unit,reverse=True)
    with pytest.raises(RuntimeError,match='Infeasible'):
        run_policy(sc,tr,p,h,stocks=s)


@pytest.mark.parametrize('unit',['tonne','MWh'])
def test_inventory_source_capacity_units_and_integration(unit):
    from techgraph.integration import run_integrated_policy,audit_integration_run
    from techgraph.coproduct_examples import explicit_integration
    from techgraph.representation import capacity_inputs
    sc,tr,p,h,s=storage_only_world(unit)
    spec=explicit_integration(sc,capacity=2)
    a=run_integrated_policy(sc,tr,p,h,spec,horizon=99,stocks=s)
    units={n:('kg/h' if unit=='tonne' else 'kW') for n in sc.designs}
    enc,hh=capacity_inputs(sc,h,units,encode=True)
    b=run_integrated_policy(enc,tr,p,hh,spec,horizon=99,stocks=s,capacity_units=units)
    assert path_cost(tr,a)==pytest.approx(path_cost(tr,b))
    assert a['epochs'][0]['stocks']==b['epochs'][0]['stocks']
    audit_integration_run(sc,h,spec,b);audit_stock_run(sc,s,b)


def test_multiple_stocks_treatment_transfers_material_instead_of_erasing_it():
    sc,tr,p,h,s=residual_world(route='treatment',K=2,initial=2,terminal_limit=0)
    dest=dict(sc.flow_system.destinations);dest['landfill']=replace(dest['landfill'],kind='stock')
    sc=replace(sc,flow_system=replace(sc.flow_system,destinations=dest))
    s=replace(s,stocks={**s.stocks,'landfill':StockSpec('inert','D',2)})
    r=run_check(sc,tr,p,h,s)
    assert r['epochs'][-1]['stocks']['pile']['stock_end']==pytest.approx(0)
    assert r['epochs'][-1]['stocks']['landfill']['stock_end']==pytest.approx(2)
    blocked=replace(s,stocks={**s.stocks,'landfill':StockSpec('inert','D',0)})
    with pytest.raises(RuntimeError,match='Infeasible'):
        run_policy(sc,tr,p,h,stocks=blocked,horizon=99)


def test_relabel_and_package_view_preserve_stock_dynamics():
    from techgraph.integration import run_integrated_policy
    from techgraph.coproduct_examples import explicit_integration
    sc,tr,p,h,s=residual_world(route='recovery',K=4,initial=5,recovery_cost=.2)
    spec=explicit_integration(sc,capacity=4)
    a=run_integrated_policy(sc,tr,p,h,spec,horizon=99,stocks=s)
    b=run_integrated_policy(sc,tr,p,h,spec,horizon=99,stocks=s,selection=['all'],packages={'all':list(sc.designs)})
    assert path_cost(tr,a)==pytest.approx(path_cost(tr,b))
    assert [e['stocks'] for e in a['epochs']]==[e['stocks'] for e in b['epochs']]


def test_future_deposit_cannot_fund_an_earlier_withdrawal():
    sc,tr,p,h,s=storage_only_world(reverse=True)
    with pytest.raises(RuntimeError,match='Infeasible'):solve(sc,sc.designs,stocks=s)


def test_withdrawn_inventory_cannot_teleport_or_change_form():
    sc,tr,p,h,s=residual_world(route='recovery')
    for d in [replace(sc.designs['EXTRACT'],form='product'),replace(sc.designs['EXTRACT'],loc='R')]:
        ss=replace(sc,designs={**sc.designs,'EXTRACT':d},locations=('D','R'))
        with pytest.raises(ValueError,match='form and location'):run_policy(ss,tr,p,h,stocks=s)


def test_stock_cannot_be_drawn_from_ordinary_release_account():
    sc,tr,p,h,s=residual_world(route='recovery')
    sc=replace(sc,designs={**sc.designs,'EXTRACT':replace(sc.designs['EXTRACT'],destination='landfill')})
    with pytest.raises(ValueError,match='stock destination'):validate_flow_system(sc)


@pytest.mark.parametrize('field',['stock_end','stock_start','natural_loss','block_weight'])
def test_stock_audit_detects_fabricated_history(field):
    sc,tr,p,h,s=residual_world()
    r=run_check(sc,tr,p,h,s)
    r['epochs'][1]['stocks']['pile'][field]+=1
    with pytest.raises(AssertionError):audit_stock_run(sc,s,r)


def test_valid_initial_override_is_carried_across_windows():
    sc,tr,p,h,s=residual_world()
    r=run_check(sc,tr,p,h,s,horizon=1,stock_state0={'pile':5})
    assert product_by_design(sc,r,'OLD')==pytest.approx([0]*tr.K)
    assert r['epochs'][0]['stocks']['pile']['stock_start']==pytest.approx(5)


def test_stock_and_asset_bounds_have_different_histories():
    sc,tr,p,h,s=residual_world(initial=5)
    p=replace(p,life={**p.life,'OLD':1})
    h=[replace(v,life=1) for v in h]
    r=run_check(sc,tr,p,h,s)
    assert r['epochs'][0]['capacity']['OLD']==pytest.approx(0)
    assert r['epochs'][-1]['stocks']['pile']['stock_end']==pytest.approx(5)
