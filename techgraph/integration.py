"""Explicit reusable integration tasks, opt-in alongside legacy m_new.

Tasks are indivisible one-epoch acquisitions tied to qualifying deployments.
Completed capability is retained through retirement; there is no forgetting.
"""
from __future__ import annotations
from dataclasses import asdict, dataclass, field
from math import isfinite
from numbers import Real
from typing import Mapping
from .representation import Capacity, capacity_inputs, dimension, expand_selection


@dataclass(frozen=True)
class IntegrationTask:
    effort: float = 1.0
    completion_cost: float = 0.0
    description: str = ''


@dataclass(frozen=True)
class DeploymentRequirement:
    tasks: tuple[str, ...]
    reference_capacity: Capacity
    pilot_fraction: float = 0.1

    def pilot_capacity(self, design) -> float:
        if not isfinite(self.pilot_fraction) or not 0 < self.pilot_fraction <= 1:
            raise ValueError('pilot_fraction must be in (0, 1]')
        return self.reference_capacity.canonical(dimension(design)) * self.pilot_fraction


@dataclass(frozen=True)
class IntegrationSpec:
    tasks: Mapping[str, IntegrationTask]
    deployments: Mapping[str, DeploymentRequirement]
    capacity: float | tuple[float, ...] | None = 1.0
    initially_known: tuple[str, ...] = ()
    infer_from_history: bool = True

    def limit(self, epoch: int):
        if self.capacity is None:
            return None
        return float(self.capacity if isinstance(self.capacity, Real) else self.capacity[epoch])

    def validate(self, sc, K: int):
        if set(self.deployments) != set(sc.designs):
            raise ValueError('Explicit integration requires one deployment specification for every design')
        if set(self.initially_known) - set(self.tasks):
            raise ValueError('Unknown initially completed task')
        if len(self.initially_known) != len(set(self.initially_known)):
            raise ValueError('Duplicate initially completed task')
        if not isinstance(self.infer_from_history, bool):
            raise ValueError('infer_from_history must be Boolean')
        for t, spec in self.tasks.items():
            if not isinstance(t, str) or not t:
                raise ValueError('Task identifiers must be nonempty strings')
            if not isfinite(spec.effort) or spec.effort <= 0:
                raise ValueError('Task effort must be finite and positive')
            if not isfinite(spec.completion_cost) or spec.completion_cost < 0:
                raise ValueError('Task completion cost must be finite and nonnegative')
        if self.capacity is not None and not isinstance(self.capacity, Real):
            if len(self.capacity) != K:
                raise ValueError('Integration budget sequence must match the decision horizon')
        for k in range(K):
            cap = self.limit(k)
            if cap is not None and (not isfinite(cap) or cap < 0):
                raise ValueError('Integration budget must be finite and nonnegative')
        for n, dep in self.deployments.items():
            if isinstance(dep.tasks, str) or len(dep.tasks) != len(set(dep.tasks)):
                raise ValueError(f'Invalid or duplicate task requirements for {n}')
            if set(dep.tasks) - set(self.tasks):
                raise ValueError(f'Unknown task required by {n}')
            dep.pilot_capacity(sc.designs[n])
        return self

    def known(self, history, completed=None):
        ready = set(self.initially_known) | set(completed or ())
        if self.infer_from_history:
            ready.update(t for v in history if v.capacity > 0
                         for t in self.deployments[v.design].tasks)
        if ready - set(self.tasks):
            raise ValueError('Completed-task state contains an unknown task')
        if not self.infer_from_history:
            missing = {t for v in history if v.capacity > 0
                       for t in self.deployments[v.design].tasks} - ready
            if missing:
                raise ValueError('Inherited capabilities must be explicitly known when history inference is disabled')
        return ready

    def manifest(self, sc):
        result = asdict(self)
        result['canonical_pilot_capacity'] = {n: d.pilot_capacity(sc.designs[n])
                                              for n, d in self.deployments.items()}
        result['scope'] = 'one-epoch indivisible tasks; physical pilots; retained knowledge; lossless package expansion'
        result['completion_cost_units'] = 'one-off representative-block objective units, not annualized'
        return result


def add_integration_constraints(prob, sc, traj, k0, k1, history, build, alive,
                                spec: IntegrationSpec, completed, shared, tag):
    """Attach release and task variables to an already built physical window."""
    from .backend import lp
    spec.validate(sc, traj.K)
    epochs = range(k0, k1+1)
    known = spec.known(history, completed)
    introduced = {v.design for v in history if v.capacity > 0}
    release, done = {}, {}
    def binary(kind, key, k, serial):
        if k == k0 and (kind, key) in shared:
            return shared[(kind, key)]
        v = lp.LpVariable(f'{kind}{tag}_{serial}_{k}', cat='Binary')
        if k == k0:
            shared[(kind,key)] = v
        return v
    for i, name in enumerate(sorted(sc.designs)):
        if name in introduced:
            continue
        for k in epochs:
            release[name,k] = binary('release', name, k, i)
            r = release[name,k]
            if (name,k) not in build:
                prob += r == 0
                continue
            x = build[name,k]
            available = lp.lpSum(release[name,j] for j in epochs if j <= k)
            pilot = spec.deployments[name].pilot_capacity(sc.designs[name])
            prob += x <= sc.designs[name].max_cap * available
            prob += x >= pilot * r
            commission = k + traj.lead(name,k)
            if (name,k,commission) not in alive:
                # A first deployment cannot be released if its physical pilot would
                # commission beyond the current planning window.
                prob += r == 0
            else:
                prob += alive[name,k,commission] >= pilot * r
        prob += lp.lpSum(release[name,k] for k in epochs) <= 1
    for i, task in enumerate(sorted(spec.tasks)):
        if task in known:
            continue
        for k in epochs:
            done[task,k] = binary('task', task, k, i)
            witness = [release[n,k] for n,d in spec.deployments.items()
                       if task in d.tasks and (n,k) in release]
            prob += done[task,k] <= lp.lpSum(witness)
        prob += lp.lpSum(done[task,k] for k in epochs) <= 1
    for (name,k), r in release.items():
        for task in spec.deployments[name].tasks:
            if task not in known:
                prob += r <= lp.lpSum(done[task,j] for j in epochs if j <= k)
    for k in epochs:
        limit = spec.limit(k)
        if limit is not None:
            prob += lp.lpSum(spec.tasks[t].effort*v for (t,j),v in done.items() if j==k) <= limit
    return {'release':release, 'done':done, 'known':known, 'spec':spec}


def run_integrated_policy(sc, traj, prm, history, spec: IntegrationSpec, *,
                          capacity_units=None, selection=None, packages=None, **policy):
    """Compile unit representations/package views, then run the common engine.

    Output capacities are always canonical MW or MWh, regardless of input units.
    The catalogue view selects what may be newly built; inherited assets remain
    available for operation even when absent from that view.
    """
    from .dynamic import run_policy
    if policy.get('m_new') is not None:
        raise ValueError('Select explicit tasks OR legacy m_new, not both')
    canonical, h = capacity_inputs(sc, history, capacity_units)
    chosen = expand_selection(tuple(sc.designs) if selection is None else selection,
                              sc.designs, packages)
    forbidden = set(policy.pop('forbid', ())) | (set(sc.designs)-set(chosen))
    run = run_policy(canonical, traj, prm, h, integration=spec,
                     forbid=tuple(sorted(forbidden)), **policy)
    run['representation'] = {'input_capacity_units':dict(capacity_units or {}),
                              'canonical_output_units':'MW for energy rates; MWh for stored energy; tonne/h for declared mass activities',
                              'expanded_selection':list(chosen),
                              'input_selection':list(sc.designs) if selection is None else list(selection)}
    return run


def audit_integration_run(sc, history, spec: IntegrationSpec, run, tolerance=1e-6, traj=None):
    """Independently check the saved task/deployment ledger against its contract.

    Uses physical build and living-capacity records. Does not call the solver or
    validate energy balances. Returns a structured check; raises on violation.
    """
    from .dynamic import path_cost
    spec.validate(sc, len(run['epochs']))
    known = spec.known(history)
    introduced = {v.design for v in history if v.capacity>0}
    completions = []
    charges = 0.0
    for k, epoch in enumerate(run['epochs']):
        evidence = epoch['integration']
        done = evidence['completed_tasks']; release = evidence['first_deployments']
        if len(done)!=len(set(done)) or len(release)!=len(set(release)):
            raise ValueError(f'Duplicate event in epoch {k}')
        if set(done)-set(spec.tasks) or set(done)&known:
            raise ValueError(f'Unknown or repeated task completion in epoch {k}')
        if set(release)-set(sc.designs) or set(release)&introduced:
            raise ValueError(f'Unknown or repeated first deployment in epoch {k}')
        effort=sum(spec.tasks[t].effort for t in done)
        if abs(effort-evidence['effort'])>tolerance:
            raise ValueError('Recorded effort does not match completed tasks')
        limit=spec.limit(k)
        if limit is not None and effort>limit+tolerance:
            raise ValueError('Integration effort exceeds capacity')
        available=known|set(done)
        for t in done:
            if not any(t in spec.deployments[n].tasks for n in release):
                raise ValueError('Task acquired without a qualifying deployment')
        for n in release:
            if set(spec.deployments[n].tasks)-available:
                raise ValueError('Deployment lacks required capabilities')
            pilot=spec.deployments[n].pilot_capacity(sc.designs[n])
            if epoch['builds'].get(n,0)+tolerance<pilot:
                raise ValueError('First deployment is smaller than its pilot requirement')
            lead=0 if traj is None else traj.lead(n,k)
            if lead==0:
                living=sum(v['alive'] for v in epoch['vintages'] if v['design']==n and v['built']==k)
                if living+tolerance<pilot:
                    raise ValueError('Pilot not retained in its installation epoch')
        if any(n not in introduced|set(release) for n,x in epoch['builds'].items() if x>tolerance):
            raise ValueError('Build recorded before design introduction')
        charge=sum(spec.tasks[t].completion_cost for t in done)
        if abs(charge-epoch.get('integration_cost',0.0))>tolerance:
            raise ValueError('Incorrect task charge')
        known.update(done);introduced.update(release)
        if set(evidence['known_tasks'])!=known:
            raise ValueError('Completed-task ledger lost or invented capability')
        completions.extend({'epoch':k,'task':t,'effort':spec.tasks[t].effort} for t in done)
        charges+=charge
    return {'passed':True,'completion_events':completions,
            'completion_charge_undiscounted':charges,'final_known_tasks':sorted(known)}
