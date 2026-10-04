"""Explicit port compatibility, interface lifecycle and deployment migration.

Typed flows never mix with the legacy untyped pool. An input accepts its own
interface version and a declared, directional compatibility set. Adapters are
ordinary capacity-constrained recipes; compatibility is not transitively closed.
Migration actions are one-off deployment preparation, not in-place asset retrofits.
"""
from dataclasses import asdict, dataclass, field, replace
from math import isfinite
from typing import Mapping

Key = tuple[str, str]


@dataclass(frozen=True)
class InterfaceVersion:
    available_from: int = 0
    build_until: int | None = None
    operate_until: int | None = None

    def active(self, epoch, mode='operate'):
        end = self.build_until if mode == 'build' else self.operate_until
        return epoch >= self.available_from and (end is None or epoch <= end)


@dataclass(frozen=True)
class MigrationAction:
    """First deployment of any target requires this retained preparation task.

    Costs are one-off representative-block units. Physical target investment is
    charged separately. Source capacity is neither recycled nor renewed for free.
    """
    targets: tuple[str, ...]
    completion_cost: float
    effort: float = 1.0
    pilot_capacity: float = 1e-3


@dataclass(frozen=True)
class InterfaceSystem:
    versions: Mapping[Key, InterfaceVersion]
    excluded: tuple[Key, ...] = ()
    migrations: Mapping[str, MigrationAction] = field(default_factory=dict)

    def manifest(self):
        return {'versions':[{'standard':k[0],'version':k[1],**asdict(v)} for k,v in self.versions.items()],
                'excluded':[list(k) for k in self.excluded],
                'migrations':{k:asdict(v) for k,v in self.migrations.items()},
                'migration_scope':'retained first-deployment preparation; no in-place retrofit',
                'lifecycle_clock':'actual decision epoch; inclusive endpoints; announced schedule'}


def key(port):
    return None if port.interface is None else (port.interface, port.version)


def accepted(port):
    return () if key(port) is None else tuple(dict.fromkeys((key(port), *port.compatible_with)))


def active(sc, identity, epoch, mode='operate'):
    system = sc.interface_system
    return identity not in system.excluded and system.versions[identity].active(epoch, mode)


def compatible(sc, output, input_, epoch):
    return (key(output) is not None and key(input_) is not None
            and (output.form, output.location) == (input_.form, input_.location)
            and key(output) in accepted(input_)
            and active(sc, key(output), epoch))


def buildable(sc, design, epoch):
    if sc.interface_system is None:
        return True
    return (all(active(sc, key(p), epoch, 'build') for p in design.output_ports if key(p))
            and all(any(active(sc, k, epoch, 'build') for k in accepted(p))
                    for p in design.input_ports if key(p)))


def validate_interfaces(sc):
    system = sc.interface_system
    ports = [(n, side, p) for n,d in sc.designs.items()
             for side, ps in [('input',d.input_ports),('output',d.output_ports)] for p in ps]
    if system is None:
        if any(p.interface is not None or p.version is not None or p.compatible_with for _,_,p in ports):
            raise ValueError('Typed ports require an InterfaceSystem')
        if any(d.interface_role != 'implementation' for d in sc.designs.values()):
            raise ValueError('Interface roles require an InterfaceSystem')
        return
    if not isinstance(system, InterfaceSystem) or sc.flow_system is None:
        raise ValueError('InterfaceSystem requires an explicit FlowSystem')
    for identity, spec in system.versions.items():
        if not isinstance(identity, tuple) or len(identity)!=2 or any(not isinstance(s,str) or not s for s in identity):
            raise ValueError('Interface identities are (nonempty standard, version) tuples')
        if not isinstance(spec, InterfaceVersion):
            raise ValueError('Invalid interface version specification')
        for v in (spec.available_from, spec.build_until, spec.operate_until):
            if v is not None and (type(v) is not int or v < 0):
                raise ValueError('Interface lifecycle uses nonnegative integer epochs')
        for v in (spec.build_until, spec.operate_until):
            if v is not None and v < spec.available_from:
                raise ValueError('Interface lifecycle ends before availability')
        if spec.build_until is not None and spec.operate_until is not None and spec.build_until>spec.operate_until:
            raise ValueError('Build support cannot outlast operating support')
    if set(system.excluded)-set(system.versions):
        raise ValueError('Unknown excluded interface version')
    for n,side,p in ports:
        if p.interface is None:
            if p.version is not None or p.compatible_with:
                raise ValueError('Untyped port cannot have version or compatibility metadata')
            continue
        if key(p) not in system.versions:
            raise ValueError('Unknown port interface version')
        if side=='output' and p.compatible_with:
            raise ValueError('Compatibility sets belong to consuming ports')
        if len(set(p.compatible_with))!=len(p.compatible_with) or set(p.compatible_with)-set(system.versions):
            raise ValueError('Unknown or duplicate compatible interface version')
    for n,d in sc.designs.items():
        if d.interface_role not in {'implementation','adapter'}:
            raise ValueError('Unknown interface role')
        if d.interface_role=='adapter':
            if d.kind!='process' or not any(key(p) for p in d.input_ports) or not any(key(p) for p in d.output_ports):
                raise ValueError('Adapter must have explicit typed inputs and outputs')
    for name, action in system.migrations.items():
        if not isinstance(name,str) or not name or not action.targets or set(action.targets)-set(sc.designs):
            raise ValueError('Migration actions require named existing target designs')
        if len(set(action.targets))!=len(action.targets):
            raise ValueError('Duplicate migration targets')
        for value,zero in ((action.completion_cost,True),(action.effort,False),(action.pilot_capacity,False)):
            if not isfinite(value) or value<0 or (not zero and value==0):
                raise ValueError('Invalid migration cost, effort or pilot capacity')
        if any(action.pilot_capacity>sc.designs[n].max_cap for n in action.targets):
            raise ValueError('Migration pilot exceeds build limit')


def add_interface_block(prob, sc, activities, epoch, tag):
    """Allocate actual quantities between compatible endpoints with no free mixing."""
    from .backend import lp
    typed = {'input':[], 'output':[]}
    for name,xs in activities.items():
        d=sc.designs[name]
        for side,ps in [('input',d.input_ports),('output',d.output_ports)]:
            for index,p in enumerate(ps):
                if key(p): typed[side].append((name,index,p,xs))
    links=[]; ins={}; outs={}
    for oi,(on,op,output,ox) in enumerate(typed['output']):
        for ii,(inn,ip,input_,ix) in enumerate(typed['input']):
            if not compatible(sc, output, input_, epoch): continue
            xs=[lp.LpVariable(f'interface_{tag}_{oi}_{ii}_{t}',0) for t in range(sc.periods)]
            links.append(dict(producer=on,output_port=op,consumer=inn,input_port=ip,
                              interface=key(output),rates=xs))
            for t,x in enumerate(xs):
                outs.setdefault((oi,t),[]).append(x);ins.setdefault((ii,t),[]).append(x)
    for side, sums in [('input',ins),('output',outs)]:
        for i,(name,index,p,xs) in enumerate(typed[side]):
            for t,a in enumerate(xs):
                prob += lp.lpSum(sums.get((i,t),[])) == p.coefficient*a, f'interface_{side}_{tag}_{i}_{t}'
    return {'epoch':epoch,'links':links}


def extract_interfaces(sc, block):
    from .backend import lp
    return {'epoch':block['epoch'], 'links':[
        {**link,'interface':list(link['interface']),
         'rates':[float(lp.value(x) or 0) for x in link['rates']]}
        for link in block['links']]}


def audit_interfaces(sc, quantities, tolerance=1e-6):
    """Replay compatibility and endpoint conservation independently of the LP."""
    block=quantities.get('interfaces')
    typed=any(key(p) for d in sc.designs.values() for p in (*d.input_ports,*d.output_ports))
    if block is None:
        if typed: raise AssertionError('Missing interface allocation record')
        return {'passed':True,'scope':'legacy'}
    totals={}; seen=set()
    for link in block['links']:
        token=(link['producer'],link['output_port'],link['consumer'],link['input_port'])
        if token in seen: raise AssertionError('Duplicate interface link')
        seen.add(token)
        on,op,inn,ip=token
        if on not in quantities['activity'] or inn not in quantities['activity']:
            raise AssertionError('Link uses absent activity')
        output=sc.designs[on].output_ports[op]; input_=sc.designs[inn].input_ports[ip]
        if not compatible(sc,output,input_,block['epoch']) or tuple(link['interface'])!=key(output):
            raise AssertionError('Incompatible or unavailable interface link')
        if len(link['rates'])!=sc.periods or any(not isfinite(x) or x < -tolerance for x in link['rates']):
            raise AssertionError('Invalid interface rate')
        for t,x in enumerate(link['rates']):
            for endpoint in [('output',on,op,t),('input',inn,ip,t)]:
                totals[endpoint]=totals.get(endpoint,0)+x
    for name,a in quantities['activity'].items():
        d=sc.designs[name]
        for side,ps in [('input',d.input_ports),('output',d.output_ports)]:
            for i,p in enumerate(ps):
                if key(p):
                    for t,rate in enumerate(a['rates']):
                        if abs(totals.get((side,name,i,t),0)-p.coefficient*rate)>tolerance:
                            raise AssertionError('Interface endpoint balance violated')
    return {'passed':True,'link_count':len(seen)}


def exclude_interfaces(sc, standards=(), versions=()):
    """Prohibit selected contracts, including adapter endpoints, at all epochs.

    A multi-compatible consumer remains usable through non-excluded contracts.
    Physical catalog/knowledge is retained; this is a counterfactual restriction.
    """
    system=sc.interface_system
    if system is None: raise ValueError('No interfaces to exclude')
    if set(standards)-{k[0] for k in system.versions} or set(versions)-set(system.versions):
        raise ValueError('Unknown interface exclusion')
    excluded=set(system.excluded)|set(versions)|{k for k in system.versions if k[0] in standards}
    return replace(sc,interface_system=replace(system,excluded=tuple(sorted(excluded))))


def migration_integration(sc, base=None):
    """Reuse the task engine for retained migration preparation; merge idempotently."""
    from .integration import IntegrationSpec, IntegrationTask, DeploymentRequirement
    from .representation import Capacity, canonical_unit
    system=sc.interface_system
    if system is None or not system.migrations: return base
    tasks={} if base is None else dict(base.tasks)
    deps=({n:DeploymentRequirement((),Capacity(1,canonical_unit(d)),pilot_fraction=1e-3)
           for n,d in sc.designs.items()} if base is None else dict(base.deployments))
    for name,action in system.migrations.items():
        task='interface_migration:'+name
        desired=IntegrationTask(action.effort,action.completion_cost,'Interface migration preparation')
        if task in tasks and tasks[task]!=desired: raise ValueError('Migration task name collision')
        tasks[task]=desired
        for n in action.targets:
            dep=deps[n]
            deps[n]=DeploymentRequirement(tuple(dict.fromkeys((*dep.tasks,task))),
                     Capacity(max(dep.pilot_capacity(sc.designs[n]),action.pilot_capacity),canonical_unit(sc.designs[n])),1.0)
    if base is None: return IntegrationSpec(tasks,deps,capacity=None)
    return replace(base,tasks=tasks,deployments=deps)


def add_static_migrations(prob, sc, newcap, existing, completed=()):
    from .backend import lp
    system=sc.interface_system
    if system is None: return [],{}
    if set(completed)-set(system.migrations): raise ValueError('Unknown completed migration')
    charges=[]; actions={}
    for i,(name,a) in enumerate(system.migrations.items()):
        if name in completed or any(existing.get(n,0)>0 for n in a.targets): continue
        targets=[n for n in a.targets if n in newcap]
        if not targets: continue
        y=lp.LpVariable(f'migration_{i}',cat='Binary'); actions[name]=y
        for n in targets: prob += newcap[n] <= sc.designs[n].max_cap*y
        prob += lp.lpSum(newcap[n] for n in targets)>=a.pilot_capacity*y
        charges.append(a.completion_cost*y)
    return charges,actions
