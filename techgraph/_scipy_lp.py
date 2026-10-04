"""Small linear-expression adapter for Techgraph's optional SciPy backend.

Implements only the expression-building subset used by this project, not PuLP.
MILPs use scipy.optimize.milp; continuous problems use linprog(method='highs')
so state-balance duals remain available. No integer relaxation is performed.
"""
from __future__ import annotations
from dataclasses import dataclass
from numbers import Real
import itertools
import time

import numpy as np
from scipy.optimize import Bounds, LinearConstraint, linprog, milp
from scipy.sparse import csc_matrix, vstack

LpMinimize, LpMaximize = 1, -1
LpStatus = {0: 'Not Solved', 1: 'Optimal', -1: 'Infeasible', -2: 'Unbounded', -3: 'Undefined'}
_IDS = itertools.count()


class Expression:
    def __init__(self, terms=None, constant=0.0):
        self.terms = dict(terms or {})  # integer id -> (variable, coefficient)
        self.constant = float(constant)

    @staticmethod
    def coerce(other):
        if isinstance(other, Expression):
            return other
        if isinstance(other, Real):
            return Expression(constant=float(other))
        raise TypeError(f'Not a linear expression: {type(other).__name__}')

    def __add__(self, other):
        other = self.coerce(other)
        out = Expression(self.terms, self.constant + other.constant)
        for key, (var, coef) in other.terms.items():
            old = out.terms.get(key, (var, 0.0))[1]
            out.terms[key] = (var, old + coef)
        return out

    __radd__ = __add__

    def __neg__(self):
        return self * -1.0

    def __sub__(self, other):
        return self + (-self.coerce(other))

    def __rsub__(self, other):
        return self.coerce(other) - self

    def __mul__(self, scalar):
        if not isinstance(scalar, Real):
            raise TypeError('Nonlinear multiplication is not supported')
        return Expression({key: (var, coef * scalar) for key, (var, coef) in self.terms.items()},
                          self.constant * scalar)

    __rmul__ = __mul__

    def __truediv__(self, scalar):
        return self * (1.0 / scalar)

    def __le__(self, other):
        return Constraint(self - other, '<=')

    def __ge__(self, other):
        return Constraint(self - other, '>=')

    def __eq__(self, other):
        return Constraint(self - other, '==')

    def __bool__(self):
        raise TypeError('Use an explicit constraint, not a Boolean test of a linear expression')


class LpVariable(Expression):
    def __init__(self, name, lowBound=None, upBound=None, cat='Continuous'):
        self.name = str(name)
        self.lowBound = 0.0 if cat == 'Binary' else lowBound
        self.upBound = 1.0 if cat == 'Binary' else upBound
        if cat not in ('Continuous', 'Integer', 'Binary'):
            raise ValueError(f'Unsupported variable category {cat!r}')
        self.cat = cat
        self.varValue = None
        self.uid = next(_IDS)
        super().__init__({self.uid: (self, 1.0)})


class Constraint:
    def __init__(self, expression, sense):
        self.expression = expression
        self.sense = sense
        self.pi = None

    def __bool__(self):
        raise TypeError('A symbolic constraint has no truth value')


def lpSum(terms):
    if isinstance(terms, (Expression, Real)):
        return Expression.coerce(terms)
    out = Expression()
    for term in terms:
        expr = Expression.coerce(term)
        out.constant += expr.constant
        for key, (var, coef) in expr.terms.items():
            old = out.terms.get(key, (var, 0.0))[1]
            out.terms[key] = (var, old + coef)
    return out


def value(expr):
    if expr is None:
        return None
    expr = Expression.coerce(expr)
    total = expr.constant
    for var, coef in expr.terms.values():
        if coef:
            if var.varValue is None:
                return None
            total += coef * var.varValue
    return float(total)


@dataclass
class Solver:
    msg: bool = False
    timeLimit: float | None = None
    gapRel: float = 1e-8
    presolve: bool = True


class LpProblem:
    def __init__(self, name, sense=LpMinimize):
        self.name, self.sense = name, sense
        self.constraints = {}
        self.objective = Expression()
        self.status = 0
        self.solve_metadata = {}

    def __iadd__(self, item):
        name = None
        if isinstance(item, tuple):
            item, name = item
        if isinstance(item, Constraint):
            name = name or f'_C{len(self.constraints)}'
            if name in self.constraints:
                raise ValueError(f'Duplicate constraint name {name}')
            self.constraints[name] = item
        else:
            self.objective = Expression.coerce(item)
        return self

    def solve(self, solver=None):
        solver = solver or Solver()
        exprs = [self.objective] + [c.expression for c in self.constraints.values()]
        vd = {key: var for expr in exprs for key, (var, _) in expr.terms.items()}
        variables = sorted(vd.values(), key=lambda v: (v.name, v.uid))
        names = [v.name for v in variables]
        if len(names) != len(set(names)):
            raise ValueError('Distinct variables have duplicate names')
        ix = {var.uid: j for j, var in enumerate(variables)}
        n, m = len(variables), len(self.constraints)
        if n == 0:
            raise ValueError('Empty-variable optimization is not supported by this adapter')
        c = np.zeros(n)
        for uid, (_, coef) in self.objective.terms.items():
            c[ix[uid]] = self.sense * coef
        lower = np.array([-np.inf if v.lowBound is None else v.lowBound for v in variables], dtype=float)
        upper = np.array([np.inf if v.upBound is None else v.upBound for v in variables], dtype=float)
        integer = np.array([v.cat != 'Continuous' for v in variables], dtype=np.uint8)
        rows, cols, data = [], [], []
        lb, ub = np.full(m, -np.inf), np.full(m, np.inf)
        constraints = list(self.constraints.values())
        for i, cons in enumerate(constraints):
            rhs = -cons.expression.constant
            if cons.sense in ('==', '>='):
                lb[i] = rhs
            if cons.sense in ('==', '<='):
                ub[i] = rhs
            for uid, (_, coef) in cons.expression.terms.items():
                if coef:
                    rows.append(i); cols.append(ix[uid]); data.append(coef)
        A = csc_matrix((data, (rows, cols)), shape=(m, n))
        options = {'disp': solver.msg, 'presolve': solver.presolve}
        if solver.timeLimit is not None:
            options['time_limit'] = solver.timeLimit
        start = time.perf_counter()
        attempts=[]
        if integer.any():
            options['mip_rel_gap'] = solver.gapRel
            res = milp(c, integrality=integer, bounds=Bounds(lower, upper),
                       constraints=LinearConstraint(A, lb, ub), options=options)
            attempts.append({'presolve':solver.presolve,'status_code':int(res.status),'message':str(res.message)})
            # A coupled-output integer fixture returned false infeasibility under
            # bundled HiGHS presolve. Retry the SAME integer model without it;
            # never relax integers or reinterpret a timeout as infeasibility.
            if res.status == 2 and solver.presolve:
                retry_options=dict(options,presolve=False)
                remaining=None if solver.timeLimit is None else solver.timeLimit-(time.perf_counter()-start)
                if remaining is None or remaining>0:
                    if remaining is not None:retry_options['time_limit']=remaining
                    res=milp(c,integrality=integer,bounds=Bounds(lower,upper),
                             constraints=LinearConstraint(A,lb,ub),options=retry_options)
                    attempts.append({'presolve':False,'status_code':int(res.status),'message':str(res.message)})
            method = 'scipy.optimize.milp / HiGHS' 
        else:
            eq = np.array([i for i, cons in enumerate(constraints) if cons.sense == '=='], dtype=int)
            ne = np.array([i for i, cons in enumerate(constraints) if cons.sense != '=='], dtype=int)
            signs = np.array([1.0 if constraints[i].sense == '<=' else -1.0 for i in ne])
            A_ub = A[ne].multiply(signs[:, None]).tocsc() if len(ne) else None
            b_ub = np.array([-constraints[i].expression.constant for i in ne]) * signs
            res = linprog(c, A_ub=A_ub, b_ub=b_ub if len(ne) else None,
                          A_eq=A[eq] if len(eq) else None, b_eq=lb[eq] if len(eq) else None,
                          bounds=np.column_stack([lower, upper]), method='highs', options=options)
            attempts.append({'presolve':solver.presolve,'status_code':int(res.status),'message':str(res.message)})
            method = 'scipy.optimize.linprog(highs)'
            if res.success:
                for i, dual in zip(eq, res.eqlin.marginals):
                    constraints[i].pi = float(self.sense * dual)
                for i, sign, dual in zip(ne, signs, res.ineqlin.marginals):
                    constraints[i].pi = float(self.sense * sign * dual)
        primal_error=None;integer_error=None
        if res.x is not None:
            residual=A@res.x
            primal_error=float(max(0.0,np.max(lower-res.x),np.max(res.x-upper),
                                   np.max(lb-residual) if m else 0.,np.max(residual-ub) if m else 0.))
            ix_integer=np.where(integer)[0]
            integer_error=float(np.max(np.abs(res.x[ix_integer]-np.rint(res.x[ix_integer])))) if len(ix_integer) else 0.0
            if res.status==0 and (primal_error>1e-5 or integer_error>1e-6):
                raise RuntimeError(f'Solver incumbent failed independent primal check: {primal_error=}, {integer_error=}')
        self.status = {0: 1, 1: 0, 2: -1, 3: -2, 4: -3}.get(res.status, -3)
        if res.x is not None:
            for var, x in zip(variables, res.x):
                var.varValue = float(x)
        bound = getattr(res, 'mip_dual_bound', None)
        self.solve_metadata = {
            'backend': method, 'status_code': int(res.status), 'status': LpStatus[self.status],
            'message': str(res.message), 'elapsed_seconds': time.perf_counter() - start,
            'mip_gap': None if getattr(res, 'mip_gap', None) is None else float(res.mip_gap),
            'mip_dual_bound': None if bound is None else float(self.sense * bound + self.objective.constant),
            'mip_node_count': None if getattr(res, 'mip_node_count', None) is None else int(res.mip_node_count),
            'variables': n, 'constraints': m, 'integer_variables': int(integer.sum()),
            'attempts':attempts,'max_absolute_primal_violation':primal_error,'max_integrality_violation':integer_error,
        }
        return self.status
