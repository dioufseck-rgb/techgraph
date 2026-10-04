"""Capacity-unit normalization and lossless catalogue views.

The operating engine remains in MW and MWh. This adapter changes only the
representation of *capacity* fields and their per-capacity annual prices;
energy prices, demand, dispatch, profiles and durations remain canonical.
It is not a full physical-units framework for arbitrary matter/information.
"""
from __future__ import annotations
from dataclasses import dataclass, replace
from math import isfinite
from typing import Mapping, Sequence

UNITS = {'MW': ('power', 1.0), 'kW': ('power', 1e-3), 'W': ('power', 1e-6),
         'MWh': ('energy', 1.0), 'kWh': ('energy', 1e-3), 'Wh': ('energy', 1e-6),
         'tonne/h': ('mass_rate',1.0), 'kg/h': ('mass_rate',1e-3)}


def dimension(design) -> str:
    if design.kind in {'process','sink','withdraw'} and design.activity_unit=='tonne/h':
        return 'mass_rate'
    return 'energy' if design.kind == 'store' else 'power'


def canonical_unit(design):
    return {'energy':'MWh','power':'MW','mass_rate':'tonne/h'}[dimension(design)]


def unit_factor(unit: str, expected: str) -> float:
    if unit not in UNITS:
        raise ValueError(f'Unsupported capacity unit {unit!r}')
    kind, factor = UNITS[unit]
    if kind != expected:
        raise ValueError(f'{unit} has dimension {kind}, not required {expected}')
    return factor


@dataclass(frozen=True)
class Capacity:
    value: float
    unit: str

    def canonical(self, expected: str) -> float:
        if not isfinite(self.value) or self.value <= 0:
            raise ValueError('Reference capacity must be finite and strictly positive')
        return self.value * unit_factor(self.unit, expected)


def capacity_inputs(sc, history, units: Mapping[str, str] | None = None, *, encode=False):
    """Decode declared input capacities to canonical units (or encode for export).

    Numeric fields transformed: design max_cap and annual_cost; vintage
    capacity, alive and annual_cost. Fixed charges are NOT per capacity.
    Returns new dataclasses; the supplied scenario and history are unchanged.
    """
    units = dict(units or {})
    unknown = set(units) - set(sc.designs)
    if unknown:
        raise ValueError(f'Units supplied for unknown designs: {sorted(unknown)}')
    factors = {n: unit_factor(units.get(n, canonical_unit(d)), dimension(d))
               for n, d in sc.designs.items()}
    ds = {}
    for n, d in sc.designs.items():
        f = 1.0 / factors[n] if encode else factors[n]
        if not isfinite(d.max_cap) or d.max_cap <= 0:
            raise ValueError(f'Nonpositive/nonfinite build limit for {n}')
        ds[n] = replace(d, max_cap=d.max_cap * f, annual_cost=d.annual_cost / f)
    hs = []
    for v in history:
        if v.design not in factors:
            raise ValueError(f'Inherited design {v.design} missing from catalogue')
        f = 1.0 / factors[v.design] if encode else factors[v.design]
        hs.append(replace(v, capacity=v.capacity*f, alive=v.alive*f, annual_cost=v.annual_cost/f))
    return replace(sc, designs=ds), hs


def expand_selection(selection: Sequence[str], designs, packages: Mapping[str, Sequence[str]] | None = None):
    """Resolve lossless nested package views to a deduplicated set of atomic designs.

    A package changes no costs, capacities, tasks, or composition constraints.
    It does not force all members to be built simultaneously or at all.
    """
    atoms = set(designs); packages = dict(packages or {})
    if atoms & set(packages):
        raise ValueError('Package and atomic design names must not collide')
    selected = set()
    def visit(name, path):
        if name in atoms:
            selected.add(name); return
        if name not in packages:
            raise ValueError(f'Unknown package/design {name!r}')
        if name in path:
            raise ValueError(f'Cyclic package definition: {path + (name,)}')
        members = packages[name]
        if isinstance(members, str) or not members:
            raise ValueError(f'Package {name} must have a nonempty sequence of members')
        for member in members:
            visit(member, path+(name,))
    for name in selection:
        visit(name, ())
    return tuple(sorted(selected))
