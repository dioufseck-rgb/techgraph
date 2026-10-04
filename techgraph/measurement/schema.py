"""Standard, JSON-safe measurement records for dynamic runs."""
from __future__ import annotations
from dataclasses import asdict,dataclass,field
from typing import Any
from .demand import demand_state
from .network import graph_metrics
from .reliability import reliability_metrics

@dataclass(frozen=True)
class EpochMeasurement:
    epoch:int
    forcing:dict[str,Any]
    service:dict[str,Any]
    technology:dict[str,Any]
    physical:dict[str,Any]
    architecture:dict[str,Any]
    network:dict[str,Any]
    history:dict[str,Any]
    transition:dict[str,Any]=field(default_factory=dict)

@dataclass(frozen=True)
class RunMeasurement:
    schema_version:str
    epochs:tuple[EpochMeasurement,...]
    solver:dict[str,Any]

    def manifest(self):return {'schema_version':self.schema_version,'epochs':[asdict(e) for e in self.epochs],'solver':self.solver}


def standard_run_measurement(world,run):
    """Minimum common schema. Rich domain-specific metrics can be layered on top."""
    out=[];prev=None
    for k,e in enumerate(run['epochs']):
        forcing={'demand':demand_state(world.scenario,world.trajectory,k)}
        # Required/delivered detail remains in the audited operating snapshot; keep forcing separate.
        rel=reliability_metrics(world,e)
        service={'required_total':forcing['demand']['total'],
                 'expected_unserved':rel['expected_unserved'],'worst_unserved':rel['worst_unserved'],
                 'contingency_service_survival':rel['service_survival']}
        technology={'new_capacity_total':sum(e.get('builds',{}).values()),
                    'installed_capacity_total':sum(e.get('capacity',{}).values())}
        stocks=e.get('stocks',{})
        physical={'closing_stock_total':sum(v.get('stock_end',0.) for v in stocks.values())}
        net,prev=graph_metrics(world,e,prev) if 'module_roles' in world.metadata else ({},prev)
        architecture={'active_edge_count':net.get('active_pairs'),
                      'installed_links':rel['installed_links'],'active_normal_links':rel['active_normal_links'],
                      'redundant_installed_links':rel['redundant_installed_links']}
        history={'known_integration_tasks':len(e.get('integration',{}).get('known_tasks',())),
                 'ready_capabilities':len(e.get('realizability',{}).get('ready',())),
                 'capabilities_acquired':len(e.get('realizability',{}).get('acquired',())),
                 'build_realizable_designs':len(e.get('realizability',{}).get('build_realizable',())),
                 'operate_realizable_designs':len(e.get('realizability',{}).get('operate_realizable',()))}
        if getattr(world.scenario,'interface_system',None) is not None:
            from .interfaces import operating_interfaces
            normal=next(s for s in e['operating_states'] if s['name']=='normal')
            technology['interfaces']=operating_interfaces(world.scenario,normal['flow'])
        transition={'ordered_capacity':sum(e.get('orders',e.get('builds',{})).values()),
                    'commissioned_capacity':sum(e.get('commissioned',{}).values()),
                    'wip_capacity':sum(x.get('capacity',0.)-x.get('canceled',0.) for x in e.get('wip',())),
                    'stranded_work':e.get('stranded_work',0.),
                    'reconstitution_cost':e.get('realizability',{}).get('reconstitution_cost',0.)}
        if 'interface_migration' in e:
            transition['interface_migration']=e['interface_migration']
        out.append(EpochMeasurement(k,forcing,service,technology,physical,architecture,net,history,transition))
    solver={'calls':len(run.get('solver_log',[])),'status':run.get('status'),
            'log':run.get('solver_log',[])}
    return RunMeasurement('1.0',tuple(out),solver)
