"""Declared, hand-inspectable material-flow fixtures for Step 2B.

Ten tonnes of product per one-hour representative block. Numeric choices are
verification parameters, not a calibration of waste-industry economics.
"""
from dataclasses import replace
from .catalog import Design, Scenario
from .flows import FlowSystem, FlowDemand, FlowResource, Destination, Port
from .dynamic import Trajectory, Params, Vintage
from .stocks import StockSystem, StockSpec


def residual_world(*, capacity=5.0, route='none', K=6, periods=1, initial=0.0,
                   retention=1.0, terminal_limit=None, holding_charge=0.0,
                   terminal_charge=0.0, treatment_cost=0.4, recovery_cost=1.0,
                   withdrawal_cost=0.1, access_at=0, cleaner_at=0, weight=1.0):
    if route not in {'none','treatment','recovery'}: raise ValueError('Unknown recovery route')
    port=lambda f,c=1.0:Port(f,'D',c)
    annual=8.76  # 0.001 per rate-unit for the one-hour block
    ds=[
        Design('OLD','process',annual, input_ports=(port('feed'),),
               output_ports=(port('product',.8),port('residue',.2)),activity_unit='tonne/h',
               conserve_mass=True,max_cap=100),
        Design('CLEAN','process',annual,var_cost=1.0,input_ports=(port('feed'),),
               output_ports=(port('product'),),activity_unit='tonne/h',conserve_mass=True,max_cap=100),
        Design('DEPOSIT','sink',annual,form='residue',loc='D',destination='pile',activity_unit='tonne/h',max_cap=100),
    ]
    if route!='none':
        ds += [Design('EXTRACT','withdraw',annual,var_cost=withdrawal_cost,form='residue',loc='D',
                      destination='pile',activity_unit='tonne/h',max_cap=100),
               Design('DISPOSE','sink',annual,form='inert',loc='D',destination='landfill',
                      activity_unit='tonne/h',max_cap=100)]
        if route=='treatment':
            ds += [Design('TREAT','process',annual,var_cost=treatment_cost,input_ports=(port('residue'),),
                          output_ports=(port('inert'),),activity_unit='tonne/h',conserve_mass=True,max_cap=100)]
        else:
            ds += [Design('RECOVER','process',annual,var_cost=recovery_cost,input_ports=(port('residue'),),
                          output_ports=(port('product',.5),port('inert',.5)),activity_unit='tonne/h',
                          conserve_mass=True,max_cap=100)]
    fs=FlowSystem(form_units={'fuel':'MWh','elec':'MWh','h2':'MWh',
                              'feed':'tonne','product':'tonne','residue':'tonne','inert':'tonne'},
        demands=(FlowDemand('required_product','product','D',(10.,)*periods,hard=True),),
        resources=(FlowResource('virgin_feed','feed','D',(100.,)*periods,unit_cost=1.0),),
        destinations={'pile':Destination('tonne',kind='stock',initial_stock=initial,retention=retention,
                                          removal_account='declared_loss_account' if retention<1 else None),
                      'landfill':Destination('tonne',kind='disposal',private_charge=.1)},
        hard_legacy_service=True)
    sc=Scenario(periods=periods,hours=1.0,days=periods/24.,demand_D=[0.]*periods,hub_energy=0.,
                hub_max_rate=0.,profiles={},fuel_price_R=0.,voll=3000.,designs={d.name:d for d in ds},
                locations=('D',),fuel_sites=(),flow_system=fs)
    tr=Trajectory(K,[0.]*K,[1.]*K,avail_from={'CLEAN':cleaner_at},discount=.93)
    if route!='none':
        for d in ['EXTRACT','DISPOSE','TREAT' if route=='treatment' else 'RECOVER']:
            tr.avail_from[d]=access_at
    prm=Params({d.name:20 for d in ds},aging=0.)
    old=sc.designs['OLD']
    history=[Vintage('OLD',-1,12.5,12.5,old.annual_cost,0,20)]
    stocks=StockSystem({'pile':StockSpec('residue','D',capacity,holding_charge,terminal_limit,terminal_charge)},
                       tuple([weight]*K) if isinstance(weight,(float,int)) else tuple(weight))
    return sc,tr,prm,history,stocks


def product_by_design(sc, run, design):
    d=sc.designs.get(design)
    if d is None:return [0.]*len(run['epochs'])
    coef=sum(p.coefficient for p in d.output_ports if p.form=='product')
    return [coef * e['throughput'].get(design,0.) for e in run['epochs']]
