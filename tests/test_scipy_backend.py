"""Direct verification of the optional adapter, independent of Techgraph models."""
import pytest
from techgraph import _scipy_lp as lp


def test_lp_greater_than_dual_and_constant():
    p=lp.LpProblem('lower'); x=lp.LpVariable('x', 0)
    p += x >= 2, 'floor'; p += 3*x + 5
    p.solve(); assert p.status == 1
    assert lp.value(p.objective) == pytest.approx(11)
    assert p.constraints['floor'].pi == pytest.approx(3)


def test_lp_less_than_dual():
    p=lp.LpProblem('upper'); x=lp.LpVariable('x', 0)
    p += x <= 2, 'ceiling'; p += -3*x
    p.solve(); assert p.status == 1
    assert lp.value(p.objective) == pytest.approx(-6)
    assert p.constraints['ceiling'].pi == pytest.approx(-3)


def test_lp_equality_and_free_variable():
    p=lp.LpProblem('equality'); x=lp.LpVariable('x')
    p += x == -2, 'equal'; p += 3*x
    p.solve(); assert lp.value(x) == pytest.approx(-2)
    assert p.constraints['equal'].pi == pytest.approx(3)


def test_maximization_dual_sign():
    p=lp.LpProblem('max', lp.LpMaximize); x=lp.LpVariable('x', 0)
    p += x <= 4, 'upper'; p += 2*x + 1
    p.solve(); assert lp.value(p.objective) == pytest.approx(9)
    assert p.constraints['upper'].pi == pytest.approx(2)


def test_binary_not_relaxed_and_bound_includes_constant():
    p=lp.LpProblem('binary'); x=lp.LpVariable('x', cat='Binary')
    p += x >= 0.6; p += 2*x+5
    p.solve(); assert p.status == 1
    assert lp.value(x) == pytest.approx(1)
    assert p.solve_metadata['mip_gap'] == pytest.approx(0)
    assert p.solve_metadata['mip_dual_bound'] == pytest.approx(7)


def test_infeasible_not_success():
    p=lp.LpProblem('infeasible'); x=lp.LpVariable('x', 0, 1)
    p += x >= 2; p += x
    p.solve(); assert p.status == -1
    assert lp.value(x) is None


def test_unbounded_not_success():
    p=lp.LpProblem('unbounded'); x=lp.LpVariable('x', 0)
    p += -x; p.solve(); assert p.status == -2


def test_nonlinearity_rejected():
    x=lp.LpVariable('x'); y=lp.LpVariable('y')
    with pytest.raises(TypeError): _ = x*y


def test_duplicate_variable_names_rejected():
    p=lp.LpProblem('dup'); x=lp.LpVariable('x', 0); y=lp.LpVariable('x', 0)
    p += x+y >= 1; p += x+y
    with pytest.raises(ValueError): p.solve()
