"""Graph-organization metrics for the operating flow network."""
from __future__ import annotations


def graph_metrics(world,epoch,prev_edges=None,tol=1e-7):
    """Operating site graph metrics, preserving the historical demand-sensitivity definitions.

    Multiple material forms on the same undirected site pair count once for
    topology. Flow concentration retains actual transfer activity.
    """
    roles=world.metadata['module_roles'];act=epoch['operating_states'][0]['flow']['activity'];locs=list(world.scenario.locations)
    pairs=set();weighted={};nodeflow={l:0. for l in locs}
    for n,rec in roles.items():
        if rec['role']!='LINK':continue
        q=sum(act.get(n,{}).get('rates',[]))*world.scenario.hours
        if q<=tol:continue
        a,b=rec['origin'],rec['destination'];key=tuple(sorted((a,b)));pairs.add(key);weighted[key]=weighted.get(key,0.)+q
        nodeflow[a]+=q;nodeflow[b]+=q
    adj={l:set() for l in locs}
    for a,b in pairs:adj[a].add(b);adj[b].add(a)
    deg={l:len(adj[l]) for l in locs};n=len(locs)
    density=2*len(pairs)/(n*(n-1)) if n>1 else 0.
    dmax=max(deg.values(),default=0);degcent=sum(dmax-d for d in deg.values())/((n-1)*(n-2)) if n>2 else 0.
    bc={v:0. for v in locs}
    for s in locs:
        stack=[];pred={u:[] for u in locs};sigma={u:0. for u in locs};sigma[s]=1.;dist={u:-1 for u in locs};dist[s]=0;q=[s]
        for v in q:
            stack.append(v)
            for u in adj[v]:
                if dist[u]<0:dist[u]=dist[v]+1;q.append(u)
                if dist[u]==dist[v]+1:sigma[u]+=sigma[v];pred[u].append(v)
        delta={u:0. for u in locs}
        while stack:
            u=stack.pop()
            for v in pred[u]:delta[v]+=(sigma[v]/sigma[u])*(1+delta[u])
            if u!=s:bc[u]+=delta[u]
    scale=1/((n-1)*(n-2)) if n>2 else 0.
    bc={v:x*scale for v,x in bc.items()};bmax=max(bc.values(),default=0.)
    bcent=sum(bmax-x for x in bc.values())/(n-1) if n>1 else 0.
    ds=[];seen=set();components=0
    for s in locs:
        if s not in seen:
            components+=1;stack=[s];seen.add(s)
            while stack:
                v=stack.pop()
                for u in adj[v]:
                    if u not in seen:seen.add(u);stack.append(u)
        dist={s:0};q=[s]
        for v in q:
            for u in adj[v]:
                if u not in dist:dist[u]=dist[v]+1;q.append(u)
        ds.extend(d for u,d in dist.items() if locs.index(u)>locs.index(s))
    total_incident=sum(nodeflow.values());hub=max(nodeflow,key=nodeflow.get) if total_incident else None
    hubshare=nodeflow[hub]/(total_incident/2) if hub else 0.
    turnover=None if prev_edges is None else (1-len(pairs&prev_edges)/len(pairs|prev_edges) if pairs|prev_edges else 0.)
    return {'active_pairs':len(pairs),'density':density,'degree_centralization':degcent,
            'betweenness_centralization':bcent,'mean_shortest_path':sum(ds)/len(ds) if ds else None,
            'components':components,'hub':hub,'hub_flow_share':hubshare,'edge_turnover':turnover},pairs
