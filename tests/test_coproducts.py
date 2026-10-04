"""Tests of explicit-flow contracts; synthetic examples are not calibration data."""
from dataclasses import replace
from copy import deepcopy
import pytest
from techgraph.catalog import Design,Scenario
from techgraph.flows import (Port, FlowDemand,FlowSystem,Destination,FlowResource,
                             validate_flow_system,audit_flow_block,impact_ledger)
from techgraph.coproduct_examples import heat_dependency_world,explicit_integration,quantity_series
from techgraph.model import solve,check_balances
from techgraph.dynamic import solve_window,solve_window_stochastic,run_policy,path_cost,Trajectory,Params
from techgraph.accounting import independent_path_ledger
from techgraph.flow_audit import audit_operating_state
from techgraph.integration import run_integrated_policy,audit_integration_run
from techgraph.representation import capacity_inputs,Capacity
from techgraph.analysis import operating_prices,screen,value


def ready(heat=8,days=1):
    return heat_dependency_world(heat,days=days,K=1,new_at=0)


def replace_system(sc,**kw):return replace(sc,flow_system=replace(sc.flow_system,**kw))


@pytest.mark.parametrize('heat',[0,4,8,13])
@pytest.mark.parametrize('days',[1,2])
def test_static_dynamic_agreement(heat,days):
    sc,tr,prm,_=ready(heat,days)
    a=solve(sc,sc.designs);b=solve_window(sc,tr,prm,0,0,[])
    assert a.objective==pytest.approx(b['objective'],rel=1e-8)
    assert a.emissions==pytest.approx(b['epochs'][0]['emissions'],rel=1e-8)
    assert not check_balances(sc,a)
    assert audit_flow_block(sc,a.flow,a.capacity)['passed']
    assert audit_operating_state(sc,b['epochs'][0]['operating_states'][0])['passed']


@pytest.mark.parametrize('horizon',[1,3,99])
@pytest.mark.parametrize('days',[1,2])
def test_dynamic_replay_and_closure(days,horizon):
    sc,tr,prm,h=heat_dependency_world(8,days=days)
    run=run_policy(sc,tr,prm,h,horizon=horizon)
    ledger=independent_path_ledger(sc,tr,prm,run)
    assert ledger['path_cost']==pytest.approx(path_cost(tr,run),rel=1e-9)
    for e,r in zip(run['epochs'],ledger['epochs']):
        for key in ['capital','fom','ops_cost','emissions','unmet_MWh']:
            assert e[key]==pytest.approx(r[key],abs=1e-7)
        for state in e['operating_states']:
            assert audit_operating_state(sc,state)['passed']
            assert audit_flow_block(sc,state['flow'],state['physical']['capacities'])['passed']
            assert state['physical']['spills']==[]
    if horizon>=tr.K:assert path_cost(tr,run)==pytest.approx(run['window_objective'])


def test_residual_cannot_disappear_without_a_sink():
    sc,tr,p,h=ready()
    # Remove both CO2 routes; every electric service provider produces closed CO2.
    ds={n:d for n,d in sc.designs.items() if not (d.kind=='sink' and d.form=='co2')}
    sc=replace(sc,designs=ds)
    with pytest.raises(RuntimeError,match='Infeasible'):solve(sc,sc.designs)
    with pytest.raises(RuntimeError,match='Infeasible'):solve_window(sc,tr,p,0,0,[])


def test_explicit_spill_permission_changes_the_physical_problem():
    sc,_,_,_=ready()
    ds={n:d for n,d in sc.designs.items() if not (d.kind=='sink' and d.form=='co2')}
    sc=replace_system(replace(sc,designs=ds),spill_forms=('co2',))
    res=solve(sc,sc.designs)
    assert sum(v for (f,l,t),v in res.spill.items() if f=='co2')>0
    assert res.flow['destinations']['atmosphere']['quantity']==0
    assert check_balances(sc,res)=={}


def test_joint_outputs_cannot_be_selected_independently():
    sc,_,_,_=ready(heat=0)
    res=solve(sc,[n for n in sc.designs if n!='NEW'])
    act=res.activity['OLD']['activity'][0]
    assert act==pytest.approx(25)
    record=res.flow['activity']['OLD']['outputs']
    q={p['form']:sum(p['quantities']) for p in record}
    assert q==pytest.approx({'elec':240.,'heat':300.,'waste_heat':60.,'co2':120.})
    assert res.flow['destinations']['ambient']['quantity']==pytest.approx(360.)
    assert res.flow['destinations']['atmosphere']['quantity']==pytest.approx(120.)


def test_terminal_bottleneck_can_force_different_generation():
    sc,_,_,_=ready(heat=0)
    dest=dict(sc.flow_system.destinations)
    dest['atmosphere']=replace(dest['atmosphere'],block_limit=90.)
    sc=replace_system(sc,destinations=dest)
    # Old-only requires 120 tonnes; the new route needs 80 tonnes.
    with pytest.raises(RuntimeError,match='Infeasible'):solve(sc,[n for n in sc.designs if n!='NEW'])
    res=solve(sc,sc.designs)
    assert res.flow['destinations']['atmosphere']['quantity']<=90+1e-6


def test_terminal_limit_is_shared_by_all_its_sinks():
    sc,_,_,_=ready()
    dest=dict(sc.flow_system.destinations)
    dest['atmosphere']=replace(dest['atmosphere'],block_limit=90.)
    sc=replace_system(sc,destinations=dest)
    with pytest.raises(RuntimeError,match='Infeasible'):solve(sc,sc.designs)


def test_nonmonetary_impact_labels_do_not_change_choices():
    sc,_,_,_=ready()
    a=solve(sc,sc.designs)
    dest=dict(sc.flow_system.destinations)
    dest['ambient']=replace(dest['ambient'],bearer='downstream receiver',impact_factors={'indicator':1000.})
    b=solve(replace_system(sc,destinations=dest),sc.designs)
    assert a.objective==pytest.approx(b.objective)
    assert a.new_capacity==pytest.approx(b.new_capacity)


@pytest.mark.parametrize('days',[1,2])
def test_private_release_charge_enters_static_dynamic_and_replay(days):
    sc,tr,p,h=heat_dependency_world(0,days=days,K=1,new_at=0,carbon_charge=3.)
    base=replace_system(sc,destinations={**sc.flow_system.destinations,
        'atmosphere':replace(sc.flow_system.destinations['atmosphere'],private_charge=0.)})
    a=solve(base,base.designs);b=solve(sc,sc.designs)
    assert b.objective-a.objective==pytest.approx(3*80*days)
    run=run_policy(sc,tr,p,[],horizon=99)
    assert independent_path_ledger(sc,tr,p,run)['path_cost']==pytest.approx(run['window_objective'])


def test_replay_does_not_trust_reported_impacts_or_costs():
    sc,tr,p,h=heat_dependency_world(8,carbon_charge=2.)
    run=run_policy(sc,tr,p,h,horizon=99)
    gold=independent_path_ledger(sc,tr,p,run)
    stock=impact_ledger(sc,run,block_weights=[1]*tr.K)
    copy=deepcopy(run)
    for e in copy['epochs']:
        e['ops_cost']=-1
        for state in e['operating_states']:
            state['ops_cost']=state['emissions']=-1
            for d in state['flow']['destinations'].values():
                d['quantity']=999999.;d['private_charge']=-1;d['impacts']={}
    assert independent_path_ledger(sc,tr,p,copy)==gold
    assert impact_ledger(sc,copy,block_weights=[1]*tr.K)==stock


def test_audit_detects_fabricated_coproduct_quantity():
    sc,_,_,_=ready();r=solve(sc,sc.designs);f=deepcopy(r.flow)
    f['activity']['OLD']['outputs'][0]['quantities'][0]+=1
    with pytest.raises(AssertionError,match='coupling'):audit_flow_block(sc,f,r.capacity)


def test_audit_detects_fabricated_destination():
    sc,_,_,_=ready();r=solve(sc,sc.designs);f=deepcopy(r.flow)
    f['destinations']['atmosphere']['quantity']+=1
    with pytest.raises(AssertionError,match='destination'):audit_flow_block(sc,f,r.capacity)


def test_new_process_can_be_entrenched_by_its_coproduct():
    sc,tr,p,h=heat_dependency_world(8)
    a=run_policy(sc,tr,p,h,horizon=99)
    noheat,_,_,_=heat_dependency_world(0)
    b=run_policy(noheat,tr,p,h,horizon=99)
    assert quantity_series(sc,a,'OLD','elec')[-1]/24==pytest.approx(64/9)
    assert quantity_series(noheat,b,'OLD','elec')[-1]==pytest.approx(0)
    assert sum(e['unmet_MWh'] for e in a['epochs'])==pytest.approx(0)


def test_heat_substitute_removes_incumbent_role():
    sc,tr,p,h=heat_dependency_world(8,alternative_at=4)
    a=run_policy(sc,tr,p,h,horizon=99)
    old=quantity_series(sc,a,'OLD','elec')
    assert old[2]>0 and old[3]>0 and old[4]==pytest.approx(0)
    assert quantity_series(sc,a,'ALT_HEAT','heat')[-1]/24==pytest.approx(8)


def test_heat_connection_removal_creates_substitution_cost():
    sc,tr,p,h=ready(8)
    initial={v.design:v.alive for v in h}
    a=solve(sc,sc.designs,existing=initial)
    cap={n:q for n,q in initial.items() if n!='HEAT_LINK'}
    b=solve(sc,[n for n in sc.designs if n!='HEAT_LINK'],existing=cap)
    assert b.objective>a.objective
    assert b.activity['BOILER']['activity'][0]>0
    assert not check_balances(sc,b)


def test_new_mode_recovers_legacy_default_when_spill_is_explicitly_allowed():
    from techgraph.catalog import default_scenario,FORMS
    sc=default_scenario();a=solve(sc,sc.designs)
    explicit=replace(sc,flow_system=FlowSystem(spill_forms=FORMS))
    b=solve(explicit,explicit.designs)
    assert b.objective==pytest.approx(a.objective)
    assert b.capacity==pytest.approx(a.capacity)
    assert b.emissions==pytest.approx(a.emissions)


def test_task_mode_and_mass_capacity_units_interoperate():
    sc,tr,p,h=heat_dependency_world(8,K=4)
    spec=explicit_integration(sc,capacity=2.)
    a=run_integrated_policy(sc,tr,p,h,spec,horizon=99)
    canonical_cost=path_cost(tr,a)
    units={n:('kg/h' if d.activity_unit=='tonne/h' else 'kW') for n,d in sc.designs.items()}
    encoded,h2=capacity_inputs(sc,h,units,encode=True)
    b=run_integrated_policy(encoded,tr,p,h2,spec,capacity_units=units,horizon=99)
    assert path_cost(tr,b)==pytest.approx(canonical_cost)
    assert a['epochs'][-1]['capacity']==pytest.approx(b['epochs'][-1]['capacity'])
    assert audit_integration_run(sc,h,spec,a)['passed']
    assert independent_path_ledger(sc,tr,p,a)['path_cost']==pytest.approx(canonical_cost)


def test_closed_residual_with_operational_storage_cannot_vanish_over_cycle():
    sc,tr,p,_=ready(0)
    ds={n:d for n,d in sc.designs.items() if not(d.kind=='sink' and d.form in {'heat','waste_heat'})}
    ds['HEAT_STORE']=Design('HEAT_STORE','store',0.,form='heat',loc='D',max_cap=1e6)
    sc=replace(sc,designs=ds)
    with pytest.raises(RuntimeError,match='Infeasible'):solve(sc,sc.designs)


def test_soft_mass_demand_has_its_own_penalty_not_energy_shortfall_units():
    sc,tr,p,h=ready(0)
    fs=replace(sc.flow_system,form_units={**sc.flow_system.form_units,'sorbent':'tonne'},
               demands=sc.flow_system.demands+(FlowDemand('sorbent_use','sorbent','H',(2.,),hard=False,penalty=7.),))
    extended=replace(sc,flow_system=fs)
    a=run_policy(sc,tr,p,h,horizon=99);b=run_policy(extended,tr,p,h,horizon=99)
    assert path_cost(tr,b)-path_cost(tr,a)==pytest.approx(24*2*7)
    assert b['epochs'][0]['unmet_MWh']==0
    assert independent_path_ledger(extended,tr,p,b)['path_cost']==pytest.approx(path_cost(tr,b))


def test_soft_heat_demand_is_counted_once_with_declared_penalty():
    sc,tr,p,h=ready()
    ds={n:d for n,d in sc.designs.items() if n not in {'HEAT_LINK','BOILER'}}
    fs=replace(sc.flow_system,demands=(replace(sc.flow_system.demands[0],hard=False,penalty=7.),))
    sc=replace(sc,designs=ds,flow_system=fs);h=[v for v in h if v.design in ds]
    a=run_policy(sc,tr,p,h,horizon=99)
    assert a['epochs'][0]['unmet_MWh']==pytest.approx(24*8)
    assert independent_path_ledger(sc,tr,p,a)['path_cost']==pytest.approx(path_cost(tr,a))


def test_contingency_has_its_own_residuals_and_flow_balances():
    sc,tr,p,h=heat_dependency_world(8,K=3,new_at=0)
    cont=[{'name':'no_heat_link','p':.1,'fail':['HEAT_LINK']}]
    run=run_policy(sc,tr,p,h,horizon=99,contingencies=cont)
    assert independent_path_ledger(sc,tr,p,run)['path_cost']==pytest.approx(path_cost(tr,run))
    for e in run['epochs']:
        for st in e['operating_states']:
            assert audit_operating_state(sc,st)['passed']
            assert audit_flow_block(sc,st['flow'],st['physical']['capacities'])['passed']
        assert e['operating_states'][1]['throughput'].get('HEAT_LINK',0)==pytest.approx(0)
        assert e['operating_states'][1]['throughput']['BOILER']>0
    ledger=impact_ledger(sc,run,block_weights=[1]*tr.K)
    assert ledger['destination_totals']['atmosphere']==pytest.approx(sum(e['emissions'] for e in run['epochs']))


def test_identical_stochastic_scenarios_preserve_flow_result():
    sc,tr,p,h=heat_dependency_world(8,K=3)
    a=solve_window(sc,tr,p,0,2,h)
    b=solve_window_stochastic(sc,[tr,tr],[.5,.5],p,0,2,h)
    assert a['objective']==pytest.approx(b['objective'])


def test_passive_stock_uses_explicit_weights_and_records_decay():
    sc,tr,p,h=heat_dependency_world(0,K=3,new_at=0)
    dest=dict(sc.flow_system.destinations)
    dest['atmosphere']=replace(dest['atmosphere'],initial_stock=100.,retention=.9,removal_account='removed_CO2')
    sc=replace_system(sc,destinations=dest);run=run_policy(sc,tr,p,h,horizon=99)
    ledger=impact_ledger(sc,run,block_weights=[1,2,3])
    stock=100.
    for k,row in enumerate(ledger['epochs']):
        e=row['destinations']['atmosphere']
        assert e['removed']==pytest.approx(.1*stock)
        stock=.9*stock+80.*(k+1)
        assert e['stock_end']==pytest.approx(stock)
    assert ledger['final_stocks']['atmosphere']==pytest.approx(stock)
    assert ledger['destination_units']['atmosphere']=='tonne'


@pytest.mark.parametrize('weights',[[],[1],[1,-1],[1,float('nan')]])
def test_invalid_stock_weights_rejected(weights):
    sc,tr,p,h=heat_dependency_world(0,K=2,new_at=0)
    run=run_policy(sc,tr,p,h,horizon=99)
    with pytest.raises(ValueError):impact_ledger(sc,run,block_weights=weights)


def test_declared_energy_balance_rejects_unaccounted_energy():
    sc,_,_,_=ready()
    ds=dict(sc.designs);ds['NEW']=replace(ds['NEW'],output_ports=(Port('elec','D',.6),))
    with pytest.raises(ValueError,match='does not balance'):validate_flow_system(replace(sc,designs=ds))


@pytest.mark.parametrize('bad',[-1,0,float('inf'),float('nan')])
def test_invalid_coefficients_rejected(bad):
    sc,_,_,_=ready();ds=dict(sc.designs)
    ds['NEW']=replace(ds['NEW'],input_ports=(Port('fuel','D',bad),))
    with pytest.raises(ValueError):validate_flow_system(replace(sc,designs=ds))


def test_process_cannot_terminate_without_a_named_destination():
    sc,_,_,_=ready();ds=dict(sc.designs);ds['NEW']=replace(ds['NEW'],output_ports=())
    with pytest.raises(ValueError,match='sink'):validate_flow_system(replace(sc,designs=ds))


def test_undeclared_form_rejected():
    sc,_,_,_=ready();ds=dict(sc.designs)
    ds['NEW']=replace(ds['NEW'],output_ports=(Port('magic','D',1.),))
    with pytest.raises(ValueError,match='Unknown form'):validate_flow_system(replace(sc,designs=ds))


def test_mass_sink_units_rejected_if_entered_as_energy():
    sc,_,_,_=ready();ds=dict(sc.designs);ds['SINK_co2_D']=replace(ds['SINK_co2_D'],activity_unit='MW')
    with pytest.raises(ValueError,match='units'):validate_flow_system(replace(sc,designs=ds))


def test_mixing_legacy_emissions_and_explicit_emission_ports_rejected():
    sc,_,_,_=ready();ds=dict(sc.designs);ds['OLD']=replace(ds['OLD'],emis=.2)
    with pytest.raises(ValueError,match='legacy emis'):validate_flow_system(replace(sc,designs=ds))


def test_decay_requires_removal_destination():
    sc,_,_,_=ready();dest=dict(sc.flow_system.destinations)
    dest['atmosphere']=replace(dest['atmosphere'],retention=.5)
    with pytest.raises(ValueError,match='removal'):validate_flow_system(replace_system(sc,destinations=dest))


def test_dual_residual_price_can_be_negative_and_is_not_automatically_zero():
    sc,_,_,h=ready(0)
    dest=dict(sc.flow_system.destinations);dest['ambient']=replace(dest['ambient'],private_charge=2.)
    sc=replace_system(sc,destinations=dest)
    op=operating_prices(sc,{v.design:v.alive for v in h})
    assert op.prices['waste_heat','D',0]==pytest.approx(-2.)


def test_legacy_screening_does_not_silently_misprice_new_processes():
    sc,_,_,h=ready(0)
    op=operating_prices(sc,{v.design:v.alive for v in h})
    with pytest.raises(NotImplementedError):screen(sc,op,['NEW'])


def test_mass_recovery_is_coupled_and_closes_every_port():
    from techgraph.coproduct_examples import mass_recovery_world
    sc,tr,p,h=mass_recovery_world(disposal_limit=0.)
    res=solve(sc,sc.designs)
    assert res.activity['MAKE']['activity'][0]==pytest.approx(8/.9)
    assert res.activity['RECOVER']['activity'][0]==pytest.approx((8/.9)*.2)
    assert res.activity['DISPOSE']['activity'][0]==pytest.approx(0)
    assert res.flow['destinations']['sludge_store']['quantity']==pytest.approx(24*8/9)
    assert check_balances(sc,res)=={}
    assert audit_flow_block(sc,res.flow,res.capacity)['passed']
    r=run_policy(sc,tr,p,h,horizon=99)
    assert independent_path_ledger(sc,tr,p,r)['path_cost']==pytest.approx(path_cost(tr,r))
    for e in r['epochs']: assert audit_operating_state(sc,e['operating_states'][0])['passed']


def test_mass_recipe_can_be_checked_independently_of_energy():
    from techgraph.coproduct_examples import mass_recovery_world
    sc,tr,p,h=mass_recovery_world()
    ds=dict(sc.designs)
    ds['MAKE']=replace(ds['MAKE'],output_ports=(Port('product','D',.8),))
    with pytest.raises(ValueError,match='mass recipe'):validate_flow_system(replace(sc,designs=ds))


def test_mass_capacity_conversion_works_in_a_solved_material_system():
    from techgraph.coproduct_examples import mass_recovery_world
    sc,tr,p,h=mass_recovery_world(disposal_limit=0.)
    spec=explicit_integration(sc,capacity=None)
    a=run_integrated_policy(sc,tr,p,h,spec,horizon=99)
    units={n:'kg/h' for n in sc.designs}
    encoded,h2=capacity_inputs(sc,h,units,encode=True)
    b=run_integrated_policy(encoded,tr,p,h2,spec,capacity_units=units,horizon=99)
    assert path_cost(tr,a)==pytest.approx(path_cost(tr,b))
    assert a['epochs'][-1]['capacity']==pytest.approx(b['epochs'][-1]['capacity'])


def test_incomplete_port_record_is_not_accepted():
    sc,_,_,_=ready();r=solve(sc,sc.designs);f=deepcopy(r.flow)
    f['activity']['OLD']['outputs'][0]['quantities']=[]
    with pytest.raises(AssertionError,match='Incomplete'):audit_flow_block(sc,f,r.capacity)


@pytest.mark.parametrize('efficiency',[.3,.5])
def test_a_bad_heat_connection_does_not_automatically_entrench_the_producer(efficiency):
    sc,tr,p,h=heat_dependency_world(8,heat_link_efficiency=efficiency)
    run=run_policy(sc,tr,p,h,horizon=99)
    assert quantity_series(sc,run,'OLD','elec')[-1]==pytest.approx(0)
    assert run['epochs'][-1]['throughput']['BOILER']>0
