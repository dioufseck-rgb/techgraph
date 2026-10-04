"""Controlled T15 worlds; constant total service, inherited downstream reuse.

All parameter values are synthetic mechanism inputs, not empirical calibration.
"""
from dataclasses import replace
import random
from .catalog import Design, Scenario
from .flows import Port, FlowSystem, FlowDemand, FlowResource
from .interfaces import InterfaceSystem, InterfaceVersion, MigrationAction
from .dynamic import Trajectory, Params, Vintage


def interface_world(implementations=2,dependents=3,adapter_cost=1.,direct=False,
                    diversity=True,seed=0,migration_cost=4.,replicas=False):
    rng=random.Random(seed); q=12.; weights=[rng.uniform(.7,1.3) if diversity else 1. for _ in range(dependents)]
    rates=[q*x/sum(weights) for x in weights]; ds={}; forms={'ore':'tonne','carrier':'tonne'}
    def p(standard,form='carrier',accepts=()):
        return Port(form,'A',interface=standard,version='1',compatible_with=accepts)
    economic_scale=1+.15*seed  # matched alternative-capital sensitivity across three fixtures
    for i in range(implementations):
        name=f'I{i}'
        cost=4. if replicas else [4.,3.,1.5,.75][i]
        ds[name]=Design(name,'process',365*cost*economic_scale,var_cost=1,max_cap=q*2,activity_unit='tonne/h',
            input_ports=(Port('ore','A'),),output_ports=(p('A'),),conserve_mass=True)
    ds['B']=Design('B','process',365*.3*economic_scale,var_cost=1.1,max_cap=q*2,activity_unit='tonne/h',
        input_ports=(Port('ore','A'),),output_ports=(p('B'),),conserve_mass=True)
    if adapter_cost is not None:
        ds['AD']=Design('AD','process',365*adapter_cost,max_cap=q*2,activity_unit='tonne/h',
            input_ports=(p('B'),),output_ports=(p('A'),),conserve_mass=True,interface_role='adapter')
    demands=[];hist={'I0':q}; actions={}
    for j,rate in enumerate(rates):
        form=f'service{j}';forms[form]='tonne'
        # Output recipes differ only when the diversity treatment is enabled;
        # resource limits remain slack and total delivered service is held fixed.
        coefficient=(.8+.4*rng.random()) if diversity else 1.
        for standard in ('A','B'):
            name=f'C{standard}{j}'
            ds[name]=Design(name,'process',365*.5,max_cap=q*3,activity_unit='tonne/h',
                input_ports=(replace(p(standard,accepts=(('B','1'),) if direct and standard=='A' else ()),coefficient=coefficient),),
                output_ports=(Port(form,'A'),))
        hist[f'CA{j}']=rate
        if migration_cost>0:actions[f'consumer{j}']=MigrationAction((f'CB{j}',),migration_cost)
        demands.append(FlowDemand(form,form,'A',(rate,),hard=True))
    # Keep inherited provider capacity sufficient for every composition treatment.
    hist['I0']=sum(r*ds[f'CA{j}'].input_ports[0].coefficient for j,r in enumerate(rates))
    sc=Scenario(1,1,[0],0,0,{},0,3000,designs=ds,locations=('A',),fuel_sites=(),
        flow_system=FlowSystem(form_units=forms,resources=(FlowResource('ore','ore','A',(100,),1),),demands=tuple(demands)),
        interface_system=InterfaceSystem({('A','1'):InterfaceVersion(),('B','1'):InterfaceVersion()},migrations=actions))
    return sc,hist


def lifecycle_world(dependents=3,deprecate=None,adapter_cost=1.,direct=False):
    sc,hist=interface_world(2,dependents,adapter_cost,direct,False)
    ds=dict(sc.designs); ds['I2']=replace(ds['I1'],name='I2',annual_cost=365*.2,var_cost=.1,
        output_ports=(Port('carrier','A',interface='A',version='2'),))
    for j in range(dependents):
        d=ds[f'CA{j}'];ds[f'C2{j}']=replace(d,name=f'C2{j}',
            input_ports=(Port('carrier','A',interface='A',version='2'),))
    if adapter_cost is not None:
        ds['V21']=Design('V21','process',365*adapter_cost,max_cap=24,activity_unit='tonne/h',
            input_ports=(Port('carrier','A',interface='A',version='2'),),
            output_ports=(Port('carrier','A',interface='A',version='1'),),interface_role='adapter',conserve_mass=True)
    migrations=dict(sc.interface_system.migrations)
    for j in range(dependents): migrations[f'version{j}']=MigrationAction((f'C2{j}',),2.)
    versions={**sc.interface_system.versions,('A','1'):InterfaceVersion(build_until=deprecate,operate_until=deprecate),
              ('A','2'):InterfaceVersion(available_from=2)}
    sc=replace(sc,designs=ds,interface_system=replace(sc.interface_system,versions=versions,migrations=migrations))
    K=5;tr=Trajectory(K,[0]*K,[1]*K,discount=1,
        cost_mult={'I1':[1,.5,.2,.1,.05]},avail_from={'I2':2})
    prm=Params({n:8 for n in ds},fom_share=.2,aging=0)
    vintages=[Vintage(n,-1,c,c,ds[n].annual_cost,0,8) for n,c in hist.items()]
    return sc,tr,prm,vintages
