"""Representation-explicit architecture distances."""
from __future__ import annotations


def share_composition(values,family_of=None):
    total=sum(values.values()) or 1.
    out={}
    for k,v in values.items():
        label=family_of.get(k,k) if family_of else k
        out[label]=out.get(label,0.)+v/total
    return out


def share_distance(a,b):
    """Half-L1 distance between share dictionaries."""
    keys=set(a)|set(b);return .5*sum(abs(a.get(k,0.)-b.get(k,0.)) for k in keys)


def topology_distance(edges_a,edges_b):
    a=set(edges_a);b=set(edges_b);u=a|b
    return 0. if not u else 1-len(a&b)/len(u)
