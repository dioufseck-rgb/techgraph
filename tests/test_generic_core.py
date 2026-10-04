from dataclasses import replace
from techgraph.catalog import Scenario, Design
from techgraph.flows import FlowSystem, FlowResource, FlowDemand, Port
from techgraph.model import solve, check_balances


def generic_mass_world():
    ds={
      'MAKE':Design('MAKE','process',annual_cost=10,max_cap=100,activity_unit='tonne/h',
                    input_ports=(Port('ore','A',1),),output_ports=(Port('product','A',1),),conserve_mass=True)
    }
    fs=FlowSystem(form_units={'ore':'tonne','product':'tonne'},
                  resources=(FlowResource('ore_supply','ore','A',(20,),unit_cost=1),),
                  demands=(FlowDemand('product_service','product','A',(10,),hard=True),))
    return Scenario(periods=1,hours=1,demand_D=[0],hub_energy=0,hub_max_rate=0,profiles={},
                    fuel_price_R=0,voll=3000,designs=ds,locations=('A',),fuel_sites=(),hub_loc='A',flow_system=fs)


def test_generic_mass_world_does_not_require_legacy_energy_carriers():
    sc=generic_mass_world()
    r=solve(sc,['MAKE'])
    assert r.status=='Optimal'
    assert set(sc.flow_system.form_units)=={'ore','product'}
    assert not check_balances(sc,r)

def test_generic_mass_world_runs_through_dynamic_compiler_without_legacy_carriers():
    from techgraph.dynamic import Trajectory, Params, run_policy
    sc=generic_mass_world()
    tr=Trajectory(K=1,fuel_price=[0],demand_mult=[1.0])
    prm=Params(life={'MAKE':4})
    r=run_policy(sc,tr,prm,[],horizon=1)
    assert r['status'] in {'Optimal','Rolling'}
    assert r['epochs'][0]['operating_states'][0]['flow']['demands']['product_service']['delivered_rates'][0] == 10.0
