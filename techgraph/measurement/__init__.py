"""Canonical measurement API for Techgraph experiments.

Metrics here implement the measurement contract shared by experiment runners.
They must remain explicit about aggregation level and must not silently turn
forcing variables into outcome variables.
"""
from .demand import gini, demand_state, demand_series
from .network import graph_metrics
from .adoption import adoption_snapshot, role_group_snapshot
from .architecture import share_composition, share_distance, topology_distance
from .schema import EpochMeasurement, RunMeasurement, standard_run_measurement

__all__ = [
    'gini','demand_state','demand_series','graph_metrics','adoption_snapshot','role_group_snapshot',
    'share_composition','share_distance','topology_distance',
    'EpochMeasurement','RunMeasurement','standard_run_measurement',
]
