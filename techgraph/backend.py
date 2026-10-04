"""Explicit solver selection; never label a SciPy run as PuLP or CBC.

TECHGRAPH_BACKEND=pulp preserves the original PuLP/HiGHS/CBC route.
TECHGRAPH_BACKEND=scipy selects the project's minimal expression adapter and
SciPy's bundled HiGHS. 'auto' prefers an importable PuLP installation.
"""
import os
import warnings

requested = os.environ.get('TECHGRAPH_BACKEND', 'auto').lower()
if requested not in {'auto', 'pulp', 'scipy'}:
    raise ValueError('TECHGRAPH_BACKEND must be auto, pulp, or scipy')
if requested in {'auto', 'pulp'}:
    try:
        import pulp as lp
        BACKEND = 'pulp'
    except ImportError:
        if requested == 'pulp':
            raise
        from . import _scipy_lp as lp
        BACKEND = 'scipy'
        warnings.warn('PuLP unavailable: using the explicit Techgraph SciPy/HiGHS backend.', RuntimeWarning)
else:
    from . import _scipy_lp as lp
    BACKEND = 'scipy'


# v4: relative MIP gap. 1e-8 is the frozen v3 value; lumpy-capacity runs set a
# declared looser gap (recorded in solver metadata) so each window terminates.
MIP_GAP = 1e-8


def mip_solver(msg=False, timeLimit=None, presolve=True):
    if BACKEND == 'pulp':
        return lp.HiGHS(msg=msg, timeLimit=timeLimit, gapRel=MIP_GAP, **({} if presolve else {"presolve":"off"}))
    return lp.Solver(msg=msg, timeLimit=timeLimit, gapRel=MIP_GAP, presolve=presolve)


def lp_solver(msg=False):
    if BACKEND == 'pulp':
        return lp.PULP_CBC_CMD(msg=msg)
    return lp.Solver(msg=msg)


def solver_metadata(prob):
    if BACKEND == 'scipy':
        return dict(prob.solve_metadata)
    out = {'backend': 'pulp', 'status': lp.LpStatus[prob.status], 'mip_gap': None}
    native = getattr(prob, 'solverModel', None)
    if native is not None and hasattr(native, 'getInfo'):
        info = native.getInfo()
        out.update(mip_gap=float(info.mip_gap), mip_node_count=int(info.mip_node_count),
                   mip_dual_bound=float(info.mip_dual_bound))
    return out


def require_optimal(prob):
    if lp.LpStatus[prob.status] != 'Optimal':
        raise RuntimeError(f'Optimization not proved optimal: {solver_metadata(prob)}')
