"""Explicit adoption measurements. No single unlabeled adoption rate is canonical."""
from __future__ import annotations


def adoption_snapshot(world,epoch,*,families,process_roles=None,tol=1e-8):
    """Return operating-flow, installed-capacity and new-investment shares by declared family.

    `families` maps design name -> family label. The caller owns the family ontology.
    """
    roles=world.metadata.get('module_roles',{})
    act=epoch['operating_states'][0]['flow']['activity'];hours=world.scenario.hours
    names=[n for n in world.scenario.designs if n in families and (process_roles is None or roles.get(n,{}).get('role') in process_roles)]
    flow={};cap={};inv={}
    for n in names:
        f=families[n]
        flow[f]=flow.get(f,0.)+sum(act.get(n,{}).get('rates',[]))*hours
        cap[f]=cap.get(f,0.)+epoch['capacity'].get(n,0.)
        inv[f]=inv.get(f,0.)+epoch['builds'].get(n,0.)
    def shares(x):
        d=sum(x.values());return {k:(v/d if d else 0.) for k,v in x.items()}
    return {'operating_flow_share':shares(flow),'installed_capacity_share':shares(cap),
            'new_investment_share':shares(inv),'operating_flow':flow,'installed_capacity':cap,'new_investment':inv}


def role_group_snapshot(world,epoch,*,included_roles,alternative_roles):
    """Adoption shares for a declared role-level technology partition.

    Useful when the experiment's technology ontology is expressed as process roles
    rather than named design families. Returns raw denominators with each share.
    """
    roles=world.metadata['module_roles'];act=epoch['operating_states'][0]['flow']['activity'];hours=world.scenario.hours
    included=set(included_roles);alternative=set(alternative_roles)
    flow_total=flow_alt=cap_total=cap_alt=0.
    for n,rec in roles.items():
        role=rec['role']
        if role not in included:continue
        q=sum(act.get(n,{}).get('rates',[]))*hours;c=epoch['capacity'].get(n,0.)
        flow_total+=q;cap_total+=c
        if role in alternative:flow_alt+=q;cap_alt+=c
    return {'operating_flow_share':flow_alt/flow_total if flow_total else 0.,
            'installed_capacity_share':cap_alt/cap_total if cap_total else 0.,
            'operating_flow_denominator':flow_total,'installed_capacity_denominator':cap_total,
            'alternative_operating_flow':flow_alt,'alternative_installed_capacity':cap_alt}
