"""Falsifiable experiment metadata written into result manifests."""
from __future__ import annotations
from dataclasses import asdict,dataclass

@dataclass(frozen=True)
class ExperimentContract:
    proposition:str
    hypothesis:str
    treatment:str
    control:str
    primary_metrics:tuple[str,...]
    falsifier:str
    aggregation_level:str
    solver_gate:str='Only resolved/optimal comparisons are evidence-eligible.'
    evidence_ceiling:str='experimental finding'

    def manifest(self):return asdict(self)


def validate_contract(c:ExperimentContract):
    if not c.proposition.strip() or not c.hypothesis.strip() or not c.falsifier.strip():
        raise ValueError('Experiment contract requires proposition, hypothesis and falsifier')
    if not c.primary_metrics or any(not x.strip() for x in c.primary_metrics):
        raise ValueError('At least one named primary metric is required')
    if not c.aggregation_level.strip():raise ValueError('Aggregation level is required')
    return c


@dataclass(frozen=True)
class DiscoveryContract:
    """Exploration scope without inventing a directional hypothesis."""
    campaign: str
    dimensions: tuple[str, ...]
    sampling: str
    measurements: tuple[str, ...]
    aggregation_level: str
    validation_plan: str
    solver_gate: str
    evidence_ceiling: str = 'exploratory synthetic patterns; no empirical law'
    mode: str = 'discovery'

    def manifest(self):
        return asdict(self)


def validate_discovery_contract(c: DiscoveryContract):
    if c.mode != 'discovery':
        raise ValueError('Discovery contract requires discovery mode')
    for name in ('campaign', 'sampling', 'aggregation_level', 'validation_plan', 'solver_gate', 'evidence_ceiling'):
        if not getattr(c, name).strip():
            raise ValueError(f'Discovery contract requires {name}')
    for name in ('dimensions', 'measurements'):
        if not getattr(c, name) or any(not x.strip() for x in getattr(c, name)):
            raise ValueError(f'Discovery contract requires {name}')
    return c
