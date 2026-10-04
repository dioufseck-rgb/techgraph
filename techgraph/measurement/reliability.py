"""Reliability measurements kept distinct from ordinary topology and flow metrics."""
from __future__ import annotations


def reliability_metrics(world, epoch, tol=1e-7):
    states=epoch.get('operating_states',())
    if not states:
        return {'contingency_states':0,'expected_unserved':0.,'worst_unserved':0.,'service_survival':1.,
                'installed_links':0,'active_normal_links':0,'redundant_installed_links':0}
    expected=sum(float(s.get('probability',0.))*float(s.get('unmet_MWh',0.)) for s in states)
    contingencies=[s for s in states if s.get('name')!='normal']
    survival=(sum(float(s.get('unmet_MWh',0.))<=tol for s in contingencies)/len(contingencies)) if contingencies else 1.
    roles=getattr(world,'metadata',{}).get('module_roles',{})
    installed={n for n,c in epoch.get('capacity',{}).items() if c>tol and roles.get(n,{}).get('role')=='LINK'}
    normal=next((s for s in states if s.get('name')=='normal'),states[0])
    activity=normal.get('flow',{}).get('activity',{})
    active={n for n in installed if sum(activity.get(n,{}).get('rates',()))*world.scenario.hours>tol}
    return {'contingency_states':len(contingencies),'expected_unserved':expected,
            'worst_unserved':max((float(s.get('unmet_MWh',0.)) for s in states),default=0.),
            'service_survival':survival,'installed_links':len(installed),'active_normal_links':len(active),
            'redundant_installed_links':len(installed-active)}
