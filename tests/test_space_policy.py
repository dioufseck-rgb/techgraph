"""Tests for the spatial layer and the generic policy primitives."""
from dataclasses import replace
import pytest
from techgraph.space import Atom, Partition, Location, Geography, trivial_geography
from techgraph.policy import Measure, Requirement, Adequacy
from techgraph.institutions import EnergyShare, CapacityQuantity, EmissionCap
from techgraph.dynamic import solve_window
from tests.test_institutions import world


def geo():
    atoms = {a: Atom(a, {'population': p, 'area': 1.0}) for a, p in (('c1', 100.0), ('c2', 300.0), ('c3', 200.0))}
    g = Geography(atoms=atoms, locations={'L1': Location('L1', ('c1', 'c2')), 'L2': Location('L2', ('c3',))})
    g.partitions['state'] = Partition('state', 'jurisdiction', {'c1': 1.0, 'c3': 0.5})
    return g


def test_location_weights_by_basis():
    g = geo()
    assert g.location_weights('state') == pytest.approx({'L1': 0.5, 'L2': 0.5})                  # equal weights
    assert g.location_weights('state', 'population') == pytest.approx({'L1': 0.25, 'L2': 0.5})   # 100/400 and 100/200


def test_partition_weights_and_report():
    g = geo()
    assert g.partition_weights('state', 'population') == pytest.approx({'L1': 0.5, 'L2': 0.5})   # 100 and 100 of 200
    assert g.report({'L1': 40.0, 'L2': 10.0}, 'state', 'population') == pytest.approx(0.25 * 40 + 0.5 * 10)


def test_crossing_links():
    g = geo(); g.partitions['east'] = Partition('east', 'physical', {'c3': 1.0})
    assert g.crossing({'tie': ('L1', 'L2'), 'back': ('L2', 'L1')}, 'east') == {'tie': 1, 'back': -1}


def test_geography_rejects_overlapping_locations():
    atoms = {'a': Atom('a')}
    with pytest.raises(ValueError):
        Geography(atoms=atoms, locations={'X': Location('X', ('a',)), 'Y': Location('Y', ('a',))})


def test_trivial_geography_is_identity():
    g = trivial_geography(['A', 'B']); g.partitions['p'] = Partition('p', 'data', {'A': 1.0})
    assert g.location_weights('p') == {'A': 1.0}


def test_generic_requirement_equals_legacy_share():
    sc, tr, pm = world()
    legacy = solve_window(sc, tr, pm, 0, 0, [], institutions=[EnergyShare('rps', ('PV',), 0.2)])
    prim = Requirement('rps', '>=', lhs=((1.0, Measure('flow', ('PV',))),), rhs=((0.2, Measure('demand')),), unit='MWh')
    generic = solve_window(sc, tr, pm, 0, 0, [], institutions=[prim])
    assert abs(legacy['objective'] - generic['objective']) < 1e-6


def test_partition_scoped_requirement():
    sc, tr, pm = world()
    half = Requirement('rps_half', '>=', lhs=((1.0, Measure('flow', ('PV',))),), rhs=((0.2, Measure('demand', locations={'A': 0.5})),))
    full = Requirement('rps_full', '>=', lhs=((1.0, Measure('flow', ('PV',))),), rhs=((0.1, Measure('demand')),))
    a = solve_window(sc, tr, pm, 0, 0, [], institutions=[half]); b = solve_window(sc, tr, pm, 0, 0, [], institutions=[full])
    assert abs(a['objective'] - b['objective']) < 1e-6           # 20% of half the demand = 10% of all of it


def test_adding_a_rule_never_lowers_cost():
    sc, tr, pm = world()
    base = solve_window(sc, tr, pm, 0, 0, [])['objective']
    for rule in (EnergyShare('rps', ('PV',), 0.2), CapacityQuantity('bat', ('BAT',), 50.0), EmissionCap('cap', 0.0, escape_price=100.0),
                 Adequacy('ad', {'GAS': 1.0}, margin=0.1)):
        assert solve_window(sc, tr, pm, 0, 0, [], institutions=[rule])['objective'] >= base - 1e-6


def test_escape_shortfall_is_reported():
    sc, tr, pm = world()
    r = solve_window(sc, tr, pm, 0, 0, [], institutions=[CapacityQuantity('huge', ('BAT',), 1e9, escape_price=1.0)])
    inst = r['institutions'][0]
    assert inst['shortfall'] > 0 and inst['kind'] == 'CapacityQuantity'


def test_from_coords_connects_point_worlds():
    from techgraph.space import from_coords
    g = from_coords({'A': (0.0, 0.0), 'B': (1.0, 0.0)})
    g.partitions['west'] = Partition('west', 'jurisdiction', {'A': 1.0})
    assert g.location_weights('west') == {'A': 1.0} and g.atoms['B'].geometry == (1.0, 0.0)
