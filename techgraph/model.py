"""Optimization core: configuration design (MILP) and fixed-configuration operation (LP).

The state space is the product of forms x locations x periods. Every module adds
terms to the balance constraint of the states it touches. Alternative orders of
processing, transport and storage appear as alternative feasible routes.
"""
from dataclasses import dataclass, field
from typing import Dict, Iterable, Optional, Tuple
from .backend import lp, mip_solver, lp_solver, solver_metadata, require_optimal

from .catalog import Scenario, FORMS
from .accounting import annual_to_block
from .attributes import validate_attributes
from .flows import (forms, permits_spill, hard_legacy_service, validate_flow_system,
                    add_flow_block, extract_flow_block, uses_legacy_contract)

from .stocks import validate_context, add_stock_epoch, extract_stock_epoch
from .needs import (add_need_block, validate_needs, has_discrete_needs, enabled)
from .operation import add_legacy_module_activity, period_weights
from .demands import location_demand, form_demand, add_flexibility
from .interfaces import buildable, add_static_migrations

DAYS_PER_YEAR = 365.0
Node = Tuple[str, str, int]  # (form, location, period)


@dataclass
class Result:
    status: str
    objective: float                         # $/day, total
    costs: Dict[str, float]                  # $/day breakdown
    capacity: Dict[str, float]               # total capacity by design
    new_capacity: Dict[str, float]
    activity: Dict[str, Dict[str, list]]     # per design: named series (MW) per period
    prices: Dict[Node, float] = field(default_factory=dict)  # $/MWh, LP only
    hub_price: Optional[float] = None
    unmet_D: list = field(default_factory=list)   # MW per period
    unmet_hub: float = 0.0                        # MWh
    unmet_extra: Dict[str, list] = field(default_factory=dict)  # MW per period at R or H
    flexibility: Dict[str, dict] = field(default_factory=dict)  # demand -> curtail / shift series (MW)
    emissions: float = 0.0                        # tCO2/day
    fuel_bought: list = field(default_factory=list)
    hub_served: list = field(default_factory=list)
    spill: Dict[Node, float] = field(default_factory=dict)  # MW disposed (curtailed) per state
    solver: dict = field(default_factory=dict)
    flow: dict = field(default_factory=dict)
    stocks: dict = field(default_factory=dict)
    migrations: dict = field(default_factory=dict)
    service_benefit: float = 0.0
    expenses: float = 0.0
    capacity_rent: Dict[str, float] = field(default_factory=dict)  # $/unit of capacity over the horizon, LP only


def solve(sc: Scenario,
          landscape: Iterable[str],
          existing: Optional[Dict[str, float]] = None,
          fixed: bool = False,
          existing_fom_share: float = 0.2,
          force_build: Iterable[str] = (), stocks=None, stock_state=None, stock_epoch=0, need_epoch=0, attribute_epoch=None, completed_migrations=()) -> Result:
    """Solve the design problem (fixed=False) or the operating problem (fixed=True).

    landscape   : designs that may receive new capacity.
    existing    : installed capacity (sunk). Existing capacity pays only a fixed O&M share.
    fixed       : if True, capacities equal `existing` and the problem is a pure LP
                  whose balance duals are returned as state prices when optional service is continuous.
                  Indivisible optional service remains a MILP; no LP prices are reported.
    force_build : designs that must receive some new capacity (for counterfactuals).
    """
    validate_flow_system(sc)
    validate_needs(sc, epoch=need_epoch)
    attribute_epoch = need_epoch if attribute_epoch is None else attribute_epoch
    if enabled(sc) and attribute_epoch != need_epoch:
        raise ValueError("Optional and attribute services must use one actual epoch")
    validate_attributes(sc, epoch=attribute_epoch)
    stock_previous = validate_context(sc, stocks, 1 if stocks is None else len(stocks.block_weights),
                                      stock_epoch, stock_state)
    period_weight = annual_to_block(sc)
    existing = dict(existing or {})
    landscape = set(landscape)
    T, H = sc.periods, sc.hours
    periods = range(T)
    W = period_weights(sc)
    prob = lp.LpProblem("techgraph", lp.LpMinimize)

    # balance[node] = list of (coef, expr) contributions in MWh; must equal demand
    balance: Dict[Node, list] = {(f, l, t): [] for f in forms(sc) for l in sc.locations for t in periods}
    cost_terms = {"new_capacity": [], "existing_fom": [], "fuel": [], "variable": [], "unmet": []}
    emis_terms = []
    cap, newcap, act = {}, {}, {}
    cap_links: Dict[str, list] = {}

    # ---- capacities -------------------------------------------------------
    for name, d in sc.designs.items():
        e = existing.get(name, 0.0)
        can_build = (not fixed) and (name in landscape) and buildable(sc,d,attribute_epoch)
        if e <= 0 and not can_build:
            continue
        if can_build:
            x = lp.LpVariable(f"x_{name}", lowBound=0, upBound=d.max_cap)
            newcap[name] = x
            cap[name] = e + x
            cost_terms["new_capacity"].append(period_weight * d.annual_cost * x)
            if d.fixed_cost > 0 and e <= 0:
                y = lp.LpVariable(f"y_{name}", cat="Binary")
                prob += x <= d.max_cap * y, f"build_{name}"
                cost_terms["new_capacity"].append(period_weight * d.fixed_cost * y)
            if name in force_build:
                prob += x >= 1e-3, f"force_{name}"
        else:
            cap[name] = e
        if e > 0:
            cost_terms["existing_fom"].append(period_weight * existing_fom_share * d.annual_cost * e)

    migration_costs, migration_actions = add_static_migrations(prob,sc,newcap,existing,completed_migrations)
    if migration_costs: cost_terms["migration"] = migration_costs

    # ---- module activity --------------------------------------------------
    legacy_cost, legacy_emis, legacy_act, _ = add_legacy_module_activity(
        prob, sc, cap, balance, cap_links=cap_links)
    cost_terms["variable"].extend(legacy_cost)
    emis_terms.extend(legacy_emis)
    act.update(legacy_act)

    flow_block = add_flow_block(prob, sc, cap, balance, tag="static", epoch=attribute_epoch)
    need_block = add_need_block(prob,sc,balance,epoch=need_epoch,tag="static")
    flow_block["need_block"] = need_block
    if enabled(sc): cost_terms["optional_benefit"] = [-v for v in need_block["benefits"]]
    if sc.flow_system is not None: cost_terms["flow_operations"] = list(flow_block["cost"])
    emis_terms.extend(flow_block["emissions"])
    for name, xs in flow_block["activities"].items():
        act[name] = {"activity": xs}
    cap_links.update(flow_block["cap_links"])

    # ---- resources and requirements ---------------------------------------
    legacy = uses_legacy_contract(sc)
    fuel = {site: [lp.LpVariable(f"fuel_{site}_{t}", lowBound=0) for t in periods]
            for site in sc.fuel_sites} if legacy else {}
    for site, xs in fuel.items():
        for t in periods:
            balance[("fuel", site, t)].append(H * xs[t])
            cost_terms["fuel"].append(W[t] * sc.fuel_price_R * H * xs[t])

    unmet = []
    if legacy:
        unmet = [lp.LpVariable(f"unmet_D_{t}", lowBound=0, upBound=0 if hard_legacy_service(sc) else sc.demand_D[t]) for t in periods]
        for t in periods:
            balance[("elec", "D", t)].append(H * unmet[t])
            cost_terms["unmet"].append(W[t] * sc.voll * H * unmet[t])

    unmet_x = {}
    for (f, loc), prof in (form_demand(sc).items() if legacy else []):        # demands for other substances
        unmet_x[(f, loc)] = [lp.LpVariable(f"unmet_{f}_{loc}_{t}", lowBound=0, upBound=prof[t]) for t in periods]
        for t in periods:
            balance[(f, loc, t)].append(H * unmet_x[(f, loc)][t])
            cost_terms["unmet"].append(W[t] * sc.voll * H * unmet_x[(f, loc)][t])
    for loc, prof in (location_demand(sc).items() if legacy else []):
        unmet_x[loc] = [lp.LpVariable(f"unmet_{loc}_{t}", lowBound=0, upBound=0 if hard_legacy_service(sc) else prof[t]) for t in periods]
        for t in periods:
            balance[("elec", loc, t)].append(H * unmet_x[loc][t])
            cost_terms["unmet"].append(W[t] * sc.voll * H * unmet_x[loc][t])

    flex_vars = add_flexibility(prob, sc, balance, cost_terms.setdefault("flexibility", []), H, W, "m", 1.0, lp) if legacy else {}

    has_hub = legacy and sc.hub_energy > 0
    hub = [lp.LpVariable(f"hub_{t}", lowBound=0, upBound=sc.hub_max_rate) for t in periods] if has_hub else []
    unmet_hub = lp.LpVariable("unmet_hub", lowBound=0, upBound=0 if hard_legacy_service(sc) else sc.hub_energy) if has_hub else None
    if has_hub:
        for t in periods:
            balance[("elec", sc.hub_loc, t)].append(-H * hub[t])
        prob += lp.lpSum(H * hub[t] for t in periods) + unmet_hub == sc.hub_energy, "hub_req"
        cost_terms["unmet"].append(sc.voll * unmet_hub)

    # ---- free disposal: a state may be left unused ----------------------------
    spills = {}
    for node, terms in balance.items():
        if terms and permits_spill(sc,node[0]):
            f, l, t = node
            spills[node] = lp.LpVariable(f"spill_{f}_{l}_{t}", lowBound=0)
            terms.append(-H * spills[node])

    # ---- balance constraints: net supply at each state = demand -----------
    loc_dem = location_demand(sc) if legacy else {}
    form_dem = form_demand(sc) if legacy else {}
    bal_cons = {}
    for (f, l, t), terms in balance.items():
        rhs = H * sc.demand_D[t] if legacy and (f, l) == ("elec", "D") else 0.0
        if legacy and f == "elec" and l in loc_dem:
            rhs += H * loc_dem[l][t]
        if legacy and f != "elec" and (f, l) in form_dem:
            rhs += H * form_dem[(f, l)][t]
        if not terms:
            continue
        cname = f"bal_{f}_{l}_{t}"
        prob += lp.lpSum(terms) == rhs, cname
        bal_cons[(f, l, t)] = cname

    stock_handle, _ = add_stock_epoch(prob, sc, stocks, stock_epoch, stock_previous, flow_block, tag="static")
    if stock_handle is not None:
        cost_terms["stock"] = [h["cost"] for h in stock_handle.values()]
    prob += lp.lpSum(lp.lpSum(v) for v in cost_terms.values())
    discrete_service = has_discrete_needs(sc)
    solver = lp_solver(msg=False) if fixed and not discrete_service else mip_solver(msg=False, presolve=sc.interface_system is None)
    prob.solve(solver)
    require_optimal(prob)
    status = lp.LpStatus[prob.status]

    val = lambda e: float(lp.value(e)) if e is not None else 0.0
    res = Result(
        status=status,
        migrations={"completed_actions":[n for n,y in migration_actions.items() if val(y)>.5],
                    "preparation_cost":sum(val(c) for c in migration_costs)},
        solver=solver_metadata(prob),
        flow=extract_flow_block(sc, flow_block),
        stocks=extract_stock_epoch(stock_handle),
        objective=val(prob.objective),
        service_benefit=val(lp.lpSum(need_block["benefits"])),
        expenses=val(prob.objective)+val(lp.lpSum(need_block["benefits"])),
        costs={k: float(sum(val(x) if not isinstance(x, (int, float)) else x for x in v))
               for k, v in cost_terms.items()},
        capacity={k: (val(v) if not isinstance(v, (int, float)) else v) for k, v in cap.items()},
        new_capacity={k: val(v) for k, v in newcap.items()},
        activity={k: {s: [val(x) for x in xs] for s, xs in ser.items()} for k, ser in act.items()},
        unmet_D=[val(u) for u in unmet],
        unmet_hub=val(unmet_hub) if has_hub else 0.0,
        unmet_extra={loc: [val(u) for u in us] for loc, us in unmet_x.items()},
        flexibility={n: {k: [val(x) for x in xs] for k, xs in r.items()} for n, r in flex_vars.items()},
        emissions=float(sum(val(e) for e in emis_terms)),
        fuel_bought={site: [val(x) for x in xs] for site, xs in fuel.items()},
        hub_served=[val(x) for x in hub] if has_hub else [0.0] * T,
        spill={k: val(v) for k, v in spills.items()},
    )
    if fixed and not discrete_service and status == "Optimal":
        for node, cname in bal_cons.items():
            pi = prob.constraints[cname].pi
            res.prices[node] = float(pi) / W[node[2]] if pi is not None else float("nan")  # $/MWh in period t
        res.hub_price = float(prob.constraints["hub_req"].pi) if has_hub else None
        for name, links in cap_links.items():
            # d(cost)/d(capacity) = sum of duals x RHS coefficient; rent is its negative
            res.capacity_rent[name] = -sum((prob.constraints[c].pi or 0.0) * k for c, k in links)
    return res


def check_balances(sc: Scenario, res: Result, tol: float = 1e-3) -> Dict[Node, float]:
    """Recompute every state balance from the solution. Returns residuals above tol."""
    H, T = sc.hours, sc.periods
    net = {(f, l, t): 0.0 for f in forms(sc) for l in sc.locations for t in range(T)}
    for name, ser in res.activity.items():
        d = sc.designs[name]
        for t in range(T):
            if d.kind == "convert":
                a = ser["output"][t]
                net[(d.form_out, d.loc, t)] += H * a
                net[(d.form_in, d.loc, t)] -= H * a / d.eff
            elif d.kind == "renewable":
                net[(d.form_out or "elec", d.loc, t)] += H * ser["output"][t]
            elif d.kind == "transport":
                fw = ser["forward"][t]
                net[(d.form, d.loc_from, t)] -= H * fw
                net[(d.form, d.loc_to, t)] += H * (1 - d.loss) * fw
                if "backward" in ser:
                    bw = ser["backward"][t]
                    net[(d.form, d.loc_to, t)] -= H * bw
                    net[(d.form, d.loc_from, t)] += H * (1 - d.loss) * bw
            elif d.kind == "process":
                a = ser["activity"][t]
                for p in d.input_ports: net[p.form,p.location,t] -= H*p.coefficient*a
                for p in d.output_ports: net[p.form,p.location,t] += H*p.coefficient*a
            elif d.kind == "withdraw":
                net[d.form,d.loc,t] += H * ser["activity"][t]
            elif d.kind == "sink":
                net[d.form,d.loc,t] -= H*ser["activity"][t]
            elif d.kind == "store":
                net[(d.form, d.loc, t)] += H * (ser["discharge"][t] - ser["charge"][t])
    for t in range(T):
        for site, xs in res.fuel_bought.items():
            net[("fuel", site, t)] += H * xs[t]
        if uses_legacy_contract(sc):
            net[("elec", "D", t)] += H * res.unmet_D[t] - H * sc.demand_D[t]
        for loc, prof in (location_demand(sc).items() if uses_legacy_contract(sc) else []):
            net[("elec", loc, t)] += H * res.unmet_extra[loc][t] - H * prof[t]
        for (f, loc), prof in (form_demand(sc).items() if uses_legacy_contract(sc) else []):
            net[(f, loc, t)] += H * res.unmet_extra[(f, loc)][t] - H * prof[t]
        for dname, r in res.flexibility.items():
            dd = next(x for x in (sc.demands or ()) if x.name == dname)
            net[(dd.form, dd.location, t)] += H * (r.get("curtail", [0.0] * T)[t] + r.get("shift_down", [0.0] * T)[t]
                                                   - r.get("shift_up", [0.0] * T)[t] + r.get("shortage", [0.0] * T)[t])
        if sc.hub_energy > 0:
            net[("elec", sc.hub_loc, t)] -= H * res.hub_served[t]
    if sc.flow_system is not None:
        for resource in sc.flow_system.resources:
            record=res.flow["resources"][resource.name]
            for t in range(T):net[resource.form,resource.location,t] += H*record["rates"][t]
        from .attributes import audit_attribute_delivery
        def consume(record, family, location, requirement):
            rates=audit_attribute_delivery(sc,record.get("attributes"),family=family,location=location,
                 requirement=requirement,delivered_rates=record["delivered_rates"],tolerance=tol)["physical_rates"]
            for form,xs in rates.items():
                for t,rate in enumerate(xs):net[form,location,t]-=H*rate
        for demand in sc.flow_system.demands:
            consume(res.flow["demands"][demand.name],demand.form,demand.location,demand.attribute_requirement)
        if sc.need_system is not None:
            for need in sc.need_system.needs:
                service=res.flow["needs"]["services"][need.name]
                for profile,rec in zip(need.profiles,service["profiles"]):
                    consume(rec,profile.form,profile.location,profile.attribute_requirement)
    for node, sp in res.spill.items():
        net[node] -= H * sp
    return {k: v for k, v in net.items() if abs(v) > tol}
