from copy import deepcopy
from dataclasses import replace
import pytest
from techgraph.catalog import Design, Scenario
from techgraph.flows import Port, FlowSystem, FlowResource, FlowDemand, audit_flow_block
from techgraph.interfaces import (InterfaceSystem, InterfaceVersion, MigrationAction,
    exclude_interfaces, audit_interfaces)
from techgraph.model import solve, check_balances
from techgraph.dynamic import Trajectory, Params, Vintage, run_policy, path_cost
from techgraph.flow_audit import audit_operating_state
from techgraph.accounting import independent_path_ledger


def world(source='1', target='1', *, accepts=(), adapter=False, migrations=False):
    def port(v,compat=()): return Port('carrier','A',interface='S',version=v,compatible_with=compat)
    ds={
        'P':Design('P','process',365,var_cost=1,max_cap=20,activity_unit='tonne/h',
                   input_ports=(Port('ore','A'),), output_ports=(port(source),),conserve_mass=True),
        'C':Design('C','process',365,max_cap=20,activity_unit='tonne/h',
                   input_ports=(port(target,accepts),),output_ports=(Port('service','A'),),conserve_mass=True),
    }
    if adapter:
        ds['AD']=Design('AD','process',365,var_cost=2,max_cap=20,activity_unit='tonne/h',
                        input_ports=(port(source),),output_ports=(port(target),),conserve_mass=True,
                        interface_role='adapter')
    fs=FlowSystem(form_units={'ore':'tonne','carrier':'tonne','service':'tonne'},
        resources=(FlowResource('resource','ore','A',(20,),1),),
        demands=(FlowDemand('service','service','A',(10,),hard=True),))
    return Scenario(1,1,[0],0,0,{},0,3000,designs=ds,locations=('A',),fuel_sites=(),
        flow_system=fs,interface_system=InterfaceSystem({('S','1'):InterfaceVersion(),('S','2'):InterfaceVersion()},
        migrations={'upgrade':MigrationAction(('C',),7)} if migrations else {}))


def run(sc,K=1,horizon=None,hist=(),**kwargs):
    tr=Trajectory(K,[0]*K,[1]*K,discount=1)
    prm=Params({n:10 for n in sc.designs},fom_share=0,aging=0)
    rr=run_policy(sc,tr,prm,list(hist),horizon=K if horizon is None else horizon,**kwargs)
    assert independent_path_ledger(sc,tr,prm,rr)['path_cost']==pytest.approx(path_cost(tr,rr))
    for e in rr['epochs']:
        for state in e['operating_states']:
            audit_operating_state(sc,state)
            audit_flow_block(sc,state['flow'],state['physical']['capacities'])
    return rr


def test_direct_and_static_dynamic_equivalence():
    sc=world(); a=solve(sc,sc.designs); b=run(sc)
    assert a.objective==pytest.approx(40)
    assert b['window_objective']==pytest.approx(a.objective)
    assert not check_balances(sc,a)
    assert audit_interfaces(sc,a.flow)['passed']


def test_incompatible_cannot_compose_and_adapter_restores_feasibility():
    sc=world('1','2')
    with pytest.raises(RuntimeError): solve(sc,sc.designs)
    sc=world('1','2',adapter=True)
    a=solve(sc,sc.designs); b=run(sc)
    assert a.capacity['AD']==pytest.approx(10)
    assert a.objective==pytest.approx(70)
    assert b['window_objective']==pytest.approx(a.objective)


def test_directional_compatibility_is_not_transitive():
    sc=world('1','2',accepts=(('S','1'),))
    assert solve(sc,sc.designs).objective==pytest.approx(40)
    sc=world('2','1')
    with pytest.raises(RuntimeError):solve(sc,sc.designs)


def test_legacy_pool_cannot_feed_typed_consumer():
    sc=world(); ds=dict(sc.designs)
    ds['P']=replace(ds['P'],output_ports=(Port('carrier','A'),))
    sc=replace(sc,designs=ds)
    with pytest.raises(RuntimeError):solve(sc,sc.designs)


def test_no_quantity_duplication_across_compatible_consumers():
    sc=world(); ds=dict(sc.designs)
    ds['C2']=replace(ds['C'],name='C2',output_ports=(Port('service2','A'),))
    fs=replace(sc.flow_system,form_units={**sc.flow_system.form_units,'service2':'tonne'},
               demands=(*sc.flow_system.demands,FlowDemand('service2','service2','A',(10,))))
    sc=replace(sc,designs=ds,flow_system=fs)
    a=solve(sc,ds)
    assert a.activity['P']['activity']==pytest.approx([20])
    bad=deepcopy(a.flow);bad['interfaces']['links'][0]['rates'][0]+=1
    with pytest.raises(AssertionError):audit_interfaces(sc,bad)


def test_adapter_capacity_limits_and_lifecycle():
    sc=world('1','2',adapter=True)
    sc=replace(sc,designs={**sc.designs,'AD':replace(sc.designs['AD'],max_cap=9)})
    with pytest.raises(RuntimeError):solve(sc,sc.designs)
    sc=world(); system=replace(sc.interface_system,versions={('S','1'):InterfaceVersion(build_until=0,operate_until=1),('S','2'):InterfaceVersion()})
    sc=replace(sc,interface_system=system)
    with pytest.raises(RuntimeError):solve(sc,sc.designs,attribute_epoch=1)
    assert solve(sc,(),existing={'P':10,'C':10},fixed=True,attribute_epoch=1).status=='Optimal'
    with pytest.raises(RuntimeError):solve(sc,(),existing={'P':10,'C':10},fixed=True,attribute_epoch=2)


def test_exclusion_allows_real_alternatives_and_blocks_adapter_endpoints():
    sc=world('1','2',adapter=True)
    with pytest.raises(RuntimeError):solve(exclude_interfaces(sc,versions=(('S','1'),)),sc.designs)
    sc=world('2','1',accepts=(('S','2'),))
    cf=exclude_interfaces(sc,versions=(('S','1'),))
    assert solve(cf,cf.designs).status=='Optimal'
    with pytest.raises(RuntimeError):solve(exclude_interfaces(sc,standards=('S',)),sc.designs)


def test_migration_charged_once_static_dynamic_and_rolling():
    sc=world(migrations=True)
    a=solve(sc,sc.designs)
    assert a.costs['migration']==pytest.approx(7)
    assert run(sc)['window_objective']==pytest.approx(a.objective)
    for horizon in (1,3):
        r=run(sc,K=3,horizon=horizon)
        assert sum(e['integration_cost'] for e in r['epochs'])==pytest.approx(7)
        assert sum('interface_migration:upgrade' in e['integration']['completed_tasks'] for e in r['epochs'])==1


def test_deprecation_forces_actual_successor_deployment():
    sc=world();ds=dict(sc.designs)
    ds['P2']=replace(ds['P'],name='P2',output_ports=(Port('carrier','A',interface='S',version='2'),))
    ds['C2']=replace(ds['C'],name='C2',input_ports=(Port('carrier','A',interface='S',version='2'),))
    sc=replace(sc,designs=ds,interface_system=InterfaceSystem(
        {('S','1'):InterfaceVersion(build_until=0,operate_until=1),('S','2'):InterfaceVersion(available_from=1)},
        migrations={'upgrade':MigrationAction(('P2','C2'),7)}))
    hist=[Vintage(n,-1,10,10,365,0,10) for n in ('P','C')]
    r=run(sc,K=3,hist=hist)
    assert r['epochs'][0]['throughput'].get('P2',0)==pytest.approx(0)
    assert r['epochs'][2]['throughput']['P']==pytest.approx(0)
    assert r['epochs'][2]['throughput']['P2']==pytest.approx(10)
    assert sum(e['integration_cost'] for e in r['epochs'])==pytest.approx(7)


@pytest.mark.parametrize('mutation',[
    lambda sc:replace(sc,interface_system=None),
    lambda sc:replace(sc,interface_system=replace(sc.interface_system,excluded=(('bad','1'),))),
    lambda sc:replace(sc,interface_system=InterfaceSystem({('S','1'):InterfaceVersion(operate_until=-1)})),
    lambda sc:replace(sc,designs={**sc.designs,'P':replace(sc.designs['P'],output_ports=(Port('carrier','A',interface='S',version='1',compatible_with=(('S','2'),)),))}),
])
def test_invalid_metadata_rejected(mutation):
    sc=mutation(world())
    with pytest.raises(ValueError):solve(sc,sc.designs)


def test_migration_preparation_composes_with_capability_and_commissioning():
    from techgraph.realizability import Capability,DesignRequirement,RealizabilitySpec
    sc=world(migrations=True)
    spec=RealizabilitySpec({'skill':Capability(acquire_cost=3)}, {'C':DesignRequirement(build=('skill',),operate=('skill',))})
    r=run(sc,K=2,realizability=spec)
    assert sum(e['realizability_cost'] for e in r['epochs'])==pytest.approx(3)
    assert sum(e['interface_migration']['preparation_cost'] for e in r['epochs'])==pytest.approx(7)
    assert r['interface_config']['migration_scope'].startswith('retained')
    # A consumer may be prepared at ordering, but still cannot operate before commissioning.
    tr=Trajectory(2,[0,0],[0,1],construction_lead={'C':1},discount=1)
    prm=Params({n:10 for n in sc.designs},fom_share=0,aging=0)
    r=run_policy(sc,tr,prm,[],horizon=2)
    assert r['epochs'][0]['orders']['C']==pytest.approx(10)
    assert r['epochs'][0]['throughput'].get('C',0)==pytest.approx(0)
    assert r['epochs'][1]['throughput']['C']==pytest.approx(10)


def test_stochastic_windows_share_migration_preparation():
    from techgraph.dynamic import solve_window_stochastic
    sc=world(migrations=True)
    trajs=[Trajectory(2,[0,0],[1,x]) for x in (1,1.5)]
    prm=Params({n:10 for n in sc.designs},fom_share=0,aging=0)
    result=solve_window_stochastic(sc,trajs,[.5,.5],prm,0,1,[])
    assert result['status']=='Optimal'
    for rr in result['scenarios']:
        assert rr['epochs'][0]['interface_migration']['preparation_cost']==pytest.approx(7)
        assert rr['epochs'][1]['interface_migration']['preparation_cost']==0
        assert rr['epochs'][0]['builds']['C']==pytest.approx(10)


def test_consumer_compatibility_does_not_create_transitive_conversion():
    sc=world('1','2',accepts=(('S','1'),))
    ds=dict(sc.designs)
    # A consumer that accepts S1 does not grant unrelated consumers access to S2.
    ds['C']=replace(ds['C'],output_ports=(Port('other','A'),))
    ds['C2']=replace(ds['C'],name='C2',input_ports=(Port('carrier','A',interface='S',version='2'),),output_ports=(Port('service','A'),))
    sc=replace(sc,designs=ds,flow_system=replace(sc.flow_system,form_units={**sc.flow_system.form_units,'other':'tonne'},spill_forms=('other',)))
    with pytest.raises(RuntimeError):solve(sc,sc.designs)


def test_completed_static_preparation_survives_asset_removal():
    sc=world(migrations=True)
    r=solve(sc,sc.designs,completed_migrations=('upgrade',))
    assert r.migrations['preparation_cost']==0
    assert r.objective==pytest.approx(40)


def test_compatibility_replay_rejects_metadata_tampering():
    sc=world('1','2',accepts=(('S','1'),))
    r=solve(sc,sc.designs);bad=deepcopy(r.flow)
    bad['interfaces']['links'][0]['interface']=['S','2']
    with pytest.raises(AssertionError):audit_interfaces(sc,bad)


def test_more_optional_implementations_cannot_destroy_cheap_adapter_solution():
    # Bundled HiGHS presolve incorrectly reported 38.8/33 rather than 30 for
    # these nested 2/4-design MILPs. Interface MILPs explicitly disable presolve.
    from techgraph.interface_examples import interface_world
    for count in (1,2,4):
        sc,existing=interface_world(count,1,.1,False,False,0)
        existing.pop('I0')
        r=solve(sc,set(sc.designs)-{'I0'},existing=existing,existing_fom_share=0)
        witness=solve(sc,('B','AD','CA0'),existing=existing,existing_fom_share=0)
        assert r.objective==pytest.approx(30)
        assert r.objective<=witness.objective+1e-7
        if 'attempts' in r.solver:
            assert r.solver['attempts'][0]['presolve'] is False
