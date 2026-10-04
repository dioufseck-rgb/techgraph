"""Inspectable runs, exact-history intervention branches, and structural metrics."""
from __future__ import annotations
from dataclasses import replace
from copy import deepcopy
import math
import numpy as np
from .dynamic import solve_window, Vintage, path_cost, path_objective
from .accounting import reconcile_run, independent_path_ledger
from .stocks import audit_stock_run
from .integration import audit_integration_run
from .flows import audit_flow_block
from .flow_audit import audit_operating_state
from .attributes import audit_attribute_run


def carry_inventory(previous, tolerance=1e-8):
    """Clip only numerical undershoots; never hide a physically negative stock."""
    raw={n:float(x['stock_end']) for n,x in previous.items()}
    if any(v < -tolerance for v in raw.values()):
        raise ValueError('Negative inventory exceeds numerical tolerance')
    return {n:max(0.,v) for n,v in raw.items()}


def execute(world, horizon=1, *, start=0, prefix=None, remove=(), exclude=(), time_limit=30.):
    """Continue an exact saved history. An excluded design is unavailable thereafter.

    The prefix is a run from the identical pre-intervention world. All sunk new
    capital in that prefix remains in the replay even when an asset is destroyed.
    Call audit_execution with prefix_world when the physical constraints changed.
    """
    sc,tr,p=world.scenario,world.trajectory,world.params
    if not 0<=start<tr.K or horizon<1:raise ValueError('Invalid horizon/start')
    if start and (prefix is None or len(prefix['epochs'])<start):raise ValueError('Prefix missing')
    if not start and prefix is not None:raise ValueError('Do not supply a prefix at epoch zero')
    if (set(remove)|set(exclude))-set(sc.designs):raise ValueError('Unknown removed design')
    if start:
        record=deepcopy(prefix['epochs'][:start])
        previous=record[-1]
        h=[]
        for v in previous['vintages']:
            if v['alive']<=1e-8:continue
            n=v['design'];d=sc.designs[n]
            h.append(Vintage(n,v['built'],v['alive'],v['alive'],v['annual_cost'],
                             d.fixed_cost*(tr.mult(n,v['built']) if v['built']>=0 else 1.),v['life']))
        stock_state=carry_inventory(previous.get('stocks',{}))
        completed=set(previous.get('integration',{}).get('known_tasks',())) if world.integration else None
    else:
        record=[];h=[replace(v) for v in world.history]
        stock_state=world.stocks.initial(sc)
        completed=world.integration.known(h) if world.integration else None
    for v in h:
        if v.design in set(remove)|set(exclude):v.alive=0.
    logs=[]
    forbid=tuple(sorted(set(world.forbid)|set(exclude)))
    initial=world.stocks.initial(sc)
    if horizon>=tr.K-start:
        sol=solve_window(sc,tr,p,start,tr.K-1,h,forbid=forbid,time_limit=time_limit,
                         integration=world.integration,completed_tasks=completed,
                         stocks=world.stocks,stock_state=stock_state)
        logs.append(sol['solver']);record.extend(sol['epochs'][k] for k in range(start,tr.K))
    else:
        for k in range(start,tr.K):
            sol=solve_window(sc,tr,p,k,min(tr.K-1,k+horizon-1),h,forbid=forbid,time_limit=time_limit,
                         integration=world.integration,completed_tasks=completed,
                         stocks=world.stocks,stock_state=stock_state)
            logs.append(sol['solver']);e=sol['epochs'][k];record.append(e)
            stock_state=carry_inventory(e['stocks'])
            if completed is not None:completed.update(e['integration']['completed_tasks'])
            for i,v in enumerate(h):v.alive=sol['hist_alive'][i,k]
            for n,cap in e['builds'].items():
                d=sc.designs[n]
                h.append(Vintage(n,k,cap,sol['new_alive'].get((n,k,k),cap),
                                 d.annual_cost*tr.mult(n,k),d.fixed_cost*tr.mult(n,k),p.life[n]))
    result={'epochs':record,'solver_log':logs,'status':'Optimal' if horizon>=tr.K-start else 'Rolling',
        'stock_config':world.stocks.manifest(sc),'initial_stocks':initial,
        'integration_config':None if world.integration is None else world.integration.manifest(sc),
        'execution':{'start':start,'horizon':horizon,'remove':list(remove),'exclude':list(exclude),
                     'scope':'identical saved prefix; no anticipation of branch event',
                     'prefix_in_solver_count':False},
    }
    if not start and horizon>=tr.K:result['window_objective']=sol['objective']
    return reconcile_run(sc,tr,p,result)


def audit_execution(world,run,prefix_world=None,tolerance=1e-5):
    sc,tr,p=world.scenario,world.trajectory,world.params
    start=run.get('execution',{}).get('start',0)
    stock=audit_stock_run(sc,world.stocks,run,tolerance=tolerance)
    ledger=independent_path_ledger(sc,tr,p,run)
    err=abs(ledger['path_objective']-path_objective(tr,run))
    if err>tolerance*max(1,abs(ledger['path_objective'])):raise AssertionError('Ledger mismatch')
    max_balance=0.
    for k,e in enumerate(run['epochs']):
        checking=prefix_world.scenario if prefix_world is not None and k<start else sc
        for state in e['operating_states']:
            a=audit_operating_state(checking,state,tolerance=tolerance)
            audit_flow_block(checking,state['flow'],state['physical']['capacities'],tolerance=tolerance)
            max_balance=max(max_balance,a['max_absolute_balance_error'])
    # Attribute snapshots carry their actual epoch, but scenario requirements can
    # differ before a resource shock. Quality shocks only add a later stage.
    attr=audit_attribute_run(sc,run,tolerance=tolerance,trajectory=tr)
    tasks=None
    if world.integration:tasks=audit_integration_run(sc,world.history,world.integration,run,tolerance=tolerance)
    if 'window_objective' in run and abs(run['window_objective']-path_objective(tr,run))>tolerance*max(1,abs(run['window_objective'])):
        raise AssertionError('Horizon objective != path evaluation')
    return {'passed':True,'stock':stock,'attribute':attr,'tasks':tasks,'path_replay_error':err,
            'max_balance_error':max_balance}


def measures(world,run):
    sc=world.scenario;roles=world.metadata['module_roles'];epochs=[]
    for k,e in enumerate(run['epochs']):
        s=e['operating_states'][0];activity=s['flow']['activity']
        act={n:sc.hours*sum(x['rates']) for n,x in activity.items()}
        active=[n for n,q in act.items() if q>1e-6]
        links=[n for n in active if roles[n]['role']=='LINK']
        installed=[n for n,c in e['capacity'].items() if c>1e-6]
        site={l:{} for l in sc.locations}
        for n,q in act.items():
            role=roles[n]['role']
            if role!='LINK':site[roles[n]['site']][role]=q
        cross={f:sum(act[n] for n in links if roles[n]['form']==f) for f in ('intermediate','coproduct','residue')}
        resources=s['flow']['resources']
        feed={l:sum(sc.hours*sum(v['rates']) for v in resources.values() if v['location']==l) for l in sc.locations}
        production={role:sum(q.get(role,0) for q in site.values()) for role in ('REFINE','LEAN_REFINE','RECOVER','SUPPLEMENT','FINISH_LOW','FINISH_HIGH','UPGRADE','DIRECT_HIGH','TREAT')}
        epochs.append({'epoch':k,'activity':act,'site_activity':site,'resource_by_site':feed,
                       'total_virgin_feed':sum(feed.values()),'cross_activity':cross,
                       'operating_links':links,'installed_links':[n for n in installed if roles[n]['role']=='LINK'],
                       'production':production,'stock_by_site':{n:v['stock_end'] for n,v in e['stocks'].items()},
                       'total_stock':sum(v['stock_end'] for v in e['stocks'].values()),
                       'new_capacity':dict(e['builds'])})
    return {'path_cost':path_cost(world.trajectory,run),'path_objective':path_objective(world.trajectory,run),
            'total_feed':sum(e['total_virgin_feed'] for e in epochs),'epochs':epochs,
            'ever_operating_links':sorted({n for e in epochs for n in e['operating_links']}),
            'ever_installed_links':sorted({n for e in epochs for n in e['installed_links']})}


def footprint(world,base,branch,site='D',start=3):
    """Changes in non-transfer processing, not a claim of traced origin/cascades."""
    reference=measures(world,base);changed=measures(world,branch)
    frac={};abschange={};origin=world.scenario.coords[site]
    process_roles={'REFINE','LEAN_REFINE','FINISH_LOW','FINISH_HIGH','UPGRADE','SUPPLEMENT','RECOVER','TREAT','DIRECT_HIGH'}
    for l in world.scenario.locations:
        delta=0.;den=0.
        for a,b in zip(reference['epochs'][start:],changed['epochs'][start:]):
            for role in process_roles:
                x=a['site_activity'][l].get(role,0);y=b['site_activity'][l].get(role,0)
                delta+=abs(y-x);den+=abs(x)
        frac[l]=delta/max(den,1e-10);abschange[l]=delta
    outside=[l for l in frac if l!=site]
    changed_outside={str(t):[l for l in outside if frac[l]>t] for t in [.005,.02,.05,.10]}
    return {'cost_change':changed['path_cost']-reference['path_cost'],
        'relative_cost_change_pct':100*(changed['path_cost']/reference['path_cost']-1),
        'site_processing_change_fraction':frac,'site_absolute_activity_change':abschange,
        'other_sites_over_threshold':changed_outside,
        'other_sites_over_2pct':len(changed_outside['0.02']),
        'other_sites_fraction_over_2pct':len(changed_outside['0.02'])/len(outside),
        'outside_share_absolute_change':sum(abschange[l] for l in outside)/max(sum(abschange.values()),1e-10),
        'max_distance_changed_over_2pct':max((math.dist(origin,world.scenario.coords[l]) for l in changed_outside['0.02']),default=0),
        'definition':'sum of absolute change in non-transfer process activity, relative to baseline processing over remaining epochs; not net delivered output or causal cascade'}
