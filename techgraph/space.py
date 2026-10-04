"""Spatial layer (see TECHGRAPH_SPACE_AND_POLICY_DESIGN.md, section 4).

Atoms are the finest spatial units (counties, grid cells, or synthetic cells) with attributes. Partitions group atoms
into jurisdictions, service territories, physical systems or data units; they overlap freely, and membership can be
fractional with a stated weighting basis. Model locations are explicit clusters of atoms chosen for a study.

The geography resolves any partition into location weights, which policy measures accept as fractional location
filters, and aggregates any per-location result to any partition. Abstract worlds are the special case in which
each location is a single synthetic atom.
"""
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple


@dataclass(frozen=True)
class Atom:
    id: str
    attributes: Dict[str, float] = field(default_factory=dict)   # e.g. area, population, demand, resources
    geometry: Optional[object] = None                            # optional shape or centroid


@dataclass(frozen=True)
class Partition:
    name: str
    kind: str                                                    # jurisdiction | territory | physical | data
    members: Dict[str, float]                                    # atom id -> share of the atom inside the partition
    source: str = ''                                             # data provenance


@dataclass(frozen=True)
class Location:
    name: str
    atoms: Tuple[str, ...]


@dataclass
class Geography:
    atoms: Dict[str, Atom]
    locations: Dict[str, Location]
    partitions: Dict[str, Partition] = field(default_factory=dict)

    def __post_init__(self):
        seen = {}
        for loc in self.locations.values():
            for a in loc.atoms:
                if a not in self.atoms:
                    raise ValueError(f'Location {loc.name} uses unknown atom {a}')
                if a in seen:
                    raise ValueError(f'Atom {a} belongs to both {seen[a]} and {loc.name}')
                seen[a] = loc.name

    def _basis(self, atom_id, basis):
        return 1.0 if basis is None else float(self.atoms[atom_id].attributes.get(basis, 0.0))

    def location_weights(self, partition: str, basis: Optional[str] = None) -> Dict[str, float]:
        """Share of each location that lies inside the partition, weighted by an atom attribute (None = equal)."""
        p = self.partitions[partition]; out = {}
        for loc in self.locations.values():
            tot = sum(self._basis(a, basis) for a in loc.atoms)
            if tot <= 0:
                continue
            inside = sum(self._basis(a, basis) * p.members.get(a, 0.0) for a in loc.atoms)
            if inside > 0:
                out[loc.name] = inside / tot
        return out

    def partition_weights(self, partition: str, basis: Optional[str] = None) -> Dict[str, float]:
        """Share of the partition that lies in each location."""
        p = self.partitions[partition]
        mass = {loc.name: sum(self._basis(a, basis) * p.members.get(a, 0.0) for a in loc.atoms) for loc in self.locations.values()}
        tot = sum(mass.values())
        return {k: v / tot for k, v in mass.items() if v > 0} if tot > 0 else {}

    def report(self, values_by_location: Dict[str, float], partition: str, basis: Optional[str] = None) -> float:
        """Aggregate an extensive per-location quantity (energy, cost, emissions) to a partition."""
        w = self.location_weights(partition, basis)
        return sum(v * w.get(loc, 0.0) for loc, v in values_by_location.items())

    def crossing(self, links: Dict[str, Tuple[str, str]], partition: str, basis: Optional[str] = None) -> Dict[str, int]:
        """Links whose endpoints lie on different sides of a partition: +1 entering, -1 leaving (whole-location test)."""
        w = self.location_weights(partition, basis); out = {}
        for name, (src, dst) in links.items():
            a, b = w.get(src, 0.0) >= 0.5, w.get(dst, 0.0) >= 0.5
            if a != b:
                out[name] = 1 if b else -1
        return out


def trivial_geography(location_names) -> Geography:
    """One synthetic atom per location: the abstract-world special case."""
    atoms = {n: Atom(n, {'area': 1.0}) for n in location_names}
    return Geography(atoms=atoms, locations={n: Location(n, (n,)) for n in location_names})


def from_coords(coords, attributes=None) -> Geography:
    """A geography from point locations (as produced by spatial.py and geography.py): one atom per location, with
    its coordinates as geometry. Partitions can then be added over these atoms."""
    attributes = attributes or {}
    atoms = {n: Atom(n, dict(attributes.get(n, {'area': 1.0})), geometry=tuple(xy)) for n, xy in coords.items()}
    return Geography(atoms=atoms, locations={n: Location(n, (n,)) for n in coords})
