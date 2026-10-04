"""Declared synthetic fixtures for coupled-output verification and exploration."""
from dataclasses import replace
from .catalog import Scenario, Design
from .flows import Port, FlowSystem, FlowDemand, FlowResource, Destination
from .dynamic import Trajectory, Params, Vintage


def heat_dependency_world(heat=8.0, *, days=1, K=6, new_at=2, alternative_at=None,
                          carbon_charge=0.0, heat_link_efficiency=0.9):
    """10 MW electricity plus configurable heat; all energy outputs are explicit.

    Activities of OLD, NEW and BOILER are MW fuel input. Heat connection capacity
    is MW thermal input. Emitted CO2 is a declared engineering coefficient, not a
    complete stoichiometric chemistry model. Both service requirements are hard.
    A single joint planner meets both; there are no trades or strategic actors.
    """
    defs=[
        Design('OLD','process',3650.,max_cap=100.,
               input_ports=(Port('fuel','D',1.),),
               output_ports=(Port('elec','D',.4),Port('heat','D',.5),Port('waste_heat','D',.1),Port('co2','D',.2)),
               conserve_energy=True),
        Design('NEW','process',3650.,max_cap=100.,
               input_ports=(Port('fuel','D',1.),),
               output_ports=(Port('elec','D',.6),Port('waste_heat','D',.4),Port('co2','D',.2)),
               conserve_energy=True),
        Design('HEAT_LINK','process',730.,max_cap=100.,
               input_ports=(Port('heat','D',1.),),
               output_ports=(Port('heat','H',heat_link_efficiency),Port('waste_heat','H',1-heat_link_efficiency)),
               conserve_energy=True),
        Design('BOILER','process',1825.,max_cap=100.,
               input_ports=(Port('fuel','H',1.),),
               output_ports=(Port('heat','H',.9),Port('waste_heat','H',.1),Port('co2','H',.2)),
               conserve_energy=True),
    ]
    # Zero-priced, capacity-bounded discharge still has an explicit receiver.
    for loc in ['D','H']:
        for form in ['heat','waste_heat','co2']:
            defs.append(Design(f'SINK_{form}_{loc}','sink',0.,form=form,loc=loc,max_cap=1000.,
                               destination='atmosphere' if form=='co2' else 'ambient',
                               activity_unit='tonne/h' if form=='co2' else 'MW'))
    resources=()
    if alternative_at is not None:
        defs.append(Design('ALT_HEAT','process',365.,max_cap=100.,
                           input_ports=(Port('external_heat','H'),),output_ports=(Port('heat','H'),),
                           conserve_energy=True))
        resources=(FlowResource('external_heat_supply','external_heat','H',(100.,)*days,unit_cost=1.0),)
    units={'fuel':'MWh','elec':'MWh','h2':'MWh','heat':'MWh','waste_heat':'MWh','co2':'tonne'}
    if resources:units['external_heat']='MWh'
    fs=FlowSystem(form_units=units,
        demands=(FlowDemand('heat_service','heat','H',(float(heat),)*days,hard=True),),
        destinations={'ambient':Destination('MWh',bearer='receiving environment',impact_factors={'heat_released_MWh':1.0}),
                      'atmosphere':Destination('tonne',kind='stock',bearer='shared atmosphere',private_charge=carbon_charge,
                                                impact_factors={'CO2_tonnes':1.0})},
        hard_legacy_service=True,resources=resources,emissions_impact='CO2_tonnes')
    ds={d.name:d for d in defs}
    sc=Scenario(periods=days,hours=24.,days=float(days),demand_D=[10.]*days,
                hub_energy=0.,hub_max_rate=0.,profiles={},fuel_price_R=10.,voll=3000.,designs=ds,
                locations=('D','H'),fuel_sites=('D','H'),flow_system=fs)
    tr=Trajectory(K,[10.]*K,[1.]*K,avail_from={'NEW':new_at},discount=.93)
    if alternative_at is not None:tr.avail_from['ALT_HEAT']=alternative_at
    prm=Params({n:12 for n in ds},fom_share=.2,aging=0.)
    hist=[Vintage('OLD',-2,25.,25.,ds['OLD'].annual_cost,0.,12),
          Vintage('HEAT_LINK',-2,12.5,12.5,ds['HEAT_LINK'].annual_cost,0.,12)]
    hist.extend(Vintage(n,-2,1000.,1000.,0.,0.,12) for n,d in ds.items() if d.kind=='sink')
    return sc,tr,prm,hist


def explicit_integration(sc, *, capacity=None):
    """Task definitions for smoke verification, not calibrated integration effort."""
    from .integration import IntegrationTask,DeploymentRequirement,IntegrationSpec
    from .representation import Capacity,canonical_unit
    tasks={n:IntegrationTask(description=f'introduce {n}') for n in sc.designs}
    deps={n:DeploymentRequirement((n,),Capacity(10.,canonical_unit(d)),.1) for n,d in sc.designs.items()}
    return IntegrationSpec(tasks,deps,capacity=capacity)


def quantity_series(sc,run,design,form,location=None):
    """Normal-state quantities per representative block for a named output port."""
    d=sc.designs[design]
    coefficient=sum(p.coefficient for p in d.output_ports if p.form==form and (location is None or p.location==location))
    return [coefficient*e['throughput'].get(design,0.) for e in run['epochs']]


def mass_recovery_world(*, disposal_limit=None):
    """Closed mass-flow fixture: feedstock -> product + waste -> recovered product + sludge."""
    units={'fuel':'MWh','elec':'MWh','h2':'MWh','feedstock':'tonne','product':'tonne','waste':'tonne','sludge':'tonne'}
    ds=[
        Design('MAKE','process',365.,var_cost=1.,activity_unit='tonne/h',max_cap=20.,
               input_ports=(Port('feedstock','D'),),output_ports=(Port('product','D',.8),Port('waste','D',.2)),conserve_mass=True),
        Design('RECOVER','process',365.,var_cost=2.,activity_unit='tonne/h',max_cap=20.,
               input_ports=(Port('waste','D'),),output_ports=(Port('product','D',.5),Port('sludge','D',.5)),conserve_mass=True),
        Design('DISPOSE','sink',0.,activity_unit='tonne/h',max_cap=20.,form='waste',loc='D',destination='landfill'),
        Design('DEPOSIT','sink',0.,activity_unit='tonne/h',max_cap=20.,form='sludge',loc='D',destination='sludge_store'),
    ]
    fs=FlowSystem(units,demands=(FlowDemand('product_need','product','D',(8.,)),),
           destinations={'landfill':Destination('tonne',kind='disposal',private_charge=.5,block_limit=disposal_limit),
                         'sludge_store':Destination('tonne',kind='stock',private_charge=.1)},
           resources=(FlowResource('feedstock_supply','feedstock','D',(20.,),unit_cost=1.),),
           hard_legacy_service=True)
    sc=Scenario(1,24.,[0.],0.,0.,{},0.,3000.,designs={d.name:d for d in ds},
                locations=('D',),fuel_sites=(),flow_system=fs)
    tr=Trajectory(2,[0.]*2,[1.]*2,discount=.93);prm=Params({d.name:10 for d in ds},aging=0)
    return sc,tr,prm,[]
