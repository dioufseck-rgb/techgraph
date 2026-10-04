"""Functional-route measurements.

A graph path is only a candidate route.  It becomes a functional substitute only
when the full technological model can satisfy the declared service while the
route is available under the stated counterfactual.  The solver-facing runner
produces route records; this module provides representation-stable path and
competitive-route summaries.
"""
from __future__ import annotations


def simple_paths(nodes, edges, source, target):
    """Enumerate simple undirected candidate paths deterministically."""
    adj={u:set() for u in nodes}
    for a,b in edges:
        adj[a].add(b);adj[b].add(a)
    out=[]
    def dfs(v,path):
        if v==target:
            out.append(tuple(path));return
        for u in sorted(adj[v]):
            if u not in path:dfs(u,path+[u])
    dfs(source,[source])
    return tuple(out)


def path_edges(path):
    return frozenset(tuple(sorted((a,b))) for a,b in zip(path,path[1:]))


def competitive_route_summary(records, baseline_objective, thresholds=(.01,.02,.05,.10)):
    """Summarize solver-verified functional route records.

    A record counts only when it is solved and all route edges are actually
    installed.  `premium_pct` is measured against the matched baseline world.
    """
    good=[r for r in records if r.get('status') in {'Optimal','Rolling'} and r.get('all_path_installed')]
    out={'functional_route_count':len(good)}
    for eps in thresholds:
        out[f'competitive_routes_{int(round(100*eps))}pct']=sum(r.get('premium_pct',float('inf'))<=eps+1e-12 for r in good)
    out['best_functional_route_premium_pct']=min((r.get('premium_pct',float('inf')) for r in good),default=None)
    return out
