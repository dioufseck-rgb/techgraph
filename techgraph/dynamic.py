"""Stage 2: dynamic investment and migration.

Decision epochs k = 0..K-1 (each several years). Each epoch is operated as a
representative day, as in Stage 1. Installed capacity is tracked by vintage. A
vintage commits its capital charge for its whole life when built (it is sunk),
pays fixed O&M while alive (rising with age), and can be retired early to save
O&M. Costs of new designs, fuel prices and demand follow a trajectory. Designs
can arrive late or lose support.

One multi-epoch MILP serves every policy:
  - perfect foresight: one window over all epochs, true trajectory;
  - rolling horizon: windows of h epochs, re-solved every epoch, with either
    true or static expectations (today's values assumed to persist);
  - absorptive capacity m: at most m design types the actor does not yet
    operate can be introduced per epoch (m=None: unlimited).
"""
from dataclasses import dataclass, field, replace
from typing import Dict, List, Optional, Tuple
from .backend import lp, mip_solver, lp_solver, solver_metadata, require_optimal

from .catalog import Scenario, FORMS
from .accounting import annual_to_block, reconcile_run
from .integration import add_integration_constraints
from .interfaces import buildable, migration_integration
from .flows import (forms, permits_spill, hard_legacy_service, validate_flow_system,
                    add_flow_block, extract_flow_block, uses_legacy_contract)
from .flow_audit import extract_physical
from .stocks import validate_context, add_stock_epoch, extract_stock_epoch
from .operation import add_legacy_module_activity, period_weights
from .demands import location_demand, form_demand, all_demands, add_flexibility, firm_profile
from .needs import add_need_block, validate_needs, enabled
from .attributes import validate_attributes, enabled as attributes_enabled
from .realizability import add_realizability_constraints, extract_realizability, CapabilityGrant

DAYS = 365.0


@dataclass
class Trajectory:
    K: int
    fuel_price: List[float]
    demand_mult: List[float]
    cost_mult: Dict[str, List[float]] = field(default_factory=dict)  # new-build cost multipliers
    avail_from: Dict[str, int] = field(default_factory=dict)
    avail_until: Dict[str, int] = field(default_factory=dict)        # last epoch a design can be built
    discount: float = 0.93                                           # per epoch
    demand_scale: Dict[str, List[float]] = field(default_factory=dict) # optional named required-demand multipliers
    build_rate: Dict[str, List[float]] = field(default_factory=dict)    # optional per-epoch new-capacity limits
    construction_lead: Dict[str, object] = field(default_factory=dict)  # epochs from order to commissioning
    resource_scale: Dict[str, List[float]] = field(default_factory=dict)  # optional per-epoch raw-supply multipliers (v4)

    def resource(self, name: str, k: int) -> float:
        values = self.resource_scale.get(name)
        return 1.0 if values is None else values[k]

    def mult(self, d: str, k: int) -> float:
        return self.cost_mult.get(d, [1.0] * self.K)[k]

    def available(self, d: str, k: int) -> bool:
        return self.avail_from.get(d, 0) <= k <= self.avail_until.get(d, self.K)

    def demand(self, name: str, k: int) -> float:
        values = self.demand_scale.get(name)
        return self.demand_mult[k] if values is None else values[k]

    def build_cap(self, name: str, k: int, default: float) -> float:
        values = self.build_rate.get(name)
        return default if values is None else min(default, values[k])

    def lead(self, name: str, k: int) -> int:
        value = self.construction_lead.get(name, 0)
        if isinstance(value, (list, tuple)):
            value = value[k]
        value = int(value)
        if value < 0:
            raise ValueError("Construction lead time must be nonnegative")
        return value


@dataclass
class Vintage:
    design: str
    built: int            # epoch built (negative for inherited capacity)
    capacity: float       # capacity as built
    alive: float          # capacity still in service
    annual_cost: float    # $/unit-yr of this vintage (capital + O&M at age 0)
    fixed_cost: float     # $/yr lump paid for this build
    life: int             # epochs


@dataclass
class Project:
    design: str
    ordered: int
    capacity: float
    commission: int
    annual_cost: float
    fixed_cost: float
    life: int


@dataclass
class Params:
    life: Dict[str, int]
    fom_share: float = 0.2      # share of annual cost that is O&M (the rest is capital)
    aging: float = 0.05         # O&M rises by this fraction per epoch of age


# --------------------------------------------------------------------------
def _op_block(prob, sc: Scenario, caps: Dict[str, object], k: int, dm: float, fuel_price: float,
              tag: str, need_value_epoch=None, demand_scale=None, resource_scale=None):
    """Operating block with optional explicitly balanced co-products and destinations."""
    T,H=sc.periods,sc.hours; P=range(T); W=period_weights(sc)
    bal={(f,l,t):[] for f in forms(sc) for l in sc.locations for t in P}
    cost,emis=[],[]; rec={}; activities={}
    legacy_cost, legacy_emis, legacy_activities, legacy_records = add_legacy_module_activity(
        prob, sc, caps, bal, tag=tag)
    cost.extend(legacy_cost); emis.extend(legacy_emis)
    activities.update(legacy_activities); rec.update(legacy_records)
    block=add_flow_block(prob,sc,caps,bal,tag=tag,dm=dm,epoch=k,demand_scale=demand_scale,resource_scale=resource_scale)
    block["need_block"]=add_need_block(prob,sc,bal,epoch=k,valuation_epoch=need_value_epoch,tag=tag)
    cost.extend(block["cost"]);emis.extend(block["emissions"])
    for n,xs in block["activities"].items():rec[n]=xs;activities[n]={"activity":xs}
    legacy=uses_legacy_contract(sc)
    fuel=[]; fuel_sites={}
    for site in (sc.fuel_sites if legacy else []):
        fuel_sites[site]=[]
        for t in P:
            x=lp.LpVariable(f"fuel_{site}_{tag}_{t}",0)
            bal["fuel",site,t].append(H*x);cost.append(W[t]*fuel_price*H*x);fuel.append(x);fuel_sites[site].append(x)
    unmet=[];demand={("D",t):dm*sc.demand_D[t] for t in P} if legacy else {};shortfalls={}
    for loc,prof in (location_demand(sc).items() if legacy else []):
        for t in P:demand[loc,t]=demand.get((loc,t),0)+dm*prof[t]
    for (loc,t),q in demand.items():
        u=lp.LpVariable(f"u_{loc}_{tag}_{t}",0,0 if hard_legacy_service(sc) else q)
        bal["elec",loc,t].append(H*u);cost.append(W[t]*sc.voll*H*u);unmet.append(H*u);shortfalls[loc,t]=u
    demand_f={}
    for (f,loc),prof in (form_demand(sc).items() if legacy else []):
        for t in P:
            q=dm*prof[t];demand_f[f,loc,t]=q
            u=lp.LpVariable(f"u_{f}_{loc}_{tag}_{t}",0,q)
            bal[f,loc,t].append(H*u);cost.append(W[t]*sc.voll*H*u);unmet.append(H*u);shortfalls[(f,loc),t]=u
    flex=add_flexibility(prob,sc,bal,cost,H,W,tag,dm,lp) if legacy else {}
    hub=[];uh=0.0
    if legacy and sc.hub_energy>0:
        hub=[lp.LpVariable(f"hub_{tag}_{t}",0,sc.hub_max_rate*dm) for t in P]
        uh=lp.LpVariable(f"uh_{tag}",0,0 if hard_legacy_service(sc) else sc.hub_energy*dm)
        for t in P:bal["elec",sc.hub_loc,t].append(-H*hub[t])
        prob += lp.lpSum(H*x for x in hub)+uh==sc.hub_energy*dm
        cost.append(sc.voll*uh);unmet.append(uh)
    unmet.extend(block["energy_unmet"])
    spills={}
    for (f,l,t),terms in bal.items():
        if not terms:continue
        sp=lp.LpVariable(f"sp_{f}_{l}_{tag}_{t}",0) if permits_spill(sc,f) else 0.0
        if permits_spill(sc,f):spills[f,l,t]=sp
        rhs=H*demand.get((l,t),0.0) if f=="elec" else H*demand_f.get((f,l,t),0.0)
        prob += lp.lpSum(terms)-H*sp==rhs
    parts={x.name:(x.owner,x.segment,x.location,[dm*q for q in x.profile],[dm*q for q in firm_profile(x)],x.form) for x in (all_demands(sc) if legacy else [])}
    block["physical"]={"activities":activities,"capacities":caps,"fuel":fuel_sites,"demands":demand,"demand_parts":parts,"flexibility":flex,
                       "shortfalls":shortfalls,"hub":hub,"unmet_hub":uh,"hub_target":sc.hub_energy*dm,
                       "profiles":sc.profiles,"spills":spills}
    return cost,emis,unmet,fuel,rec,block


def _add_realism_terms(prob, sc, caps, rec, k, k0, extras, tag, ops):
    """v4 opt-in terms. With extras=None nothing is added (frozen v3 behaviour).

    switching: {'cost': c, 'previous': {design: throughput}, 'kinds': {...}}
        c per unit of absolute change in a process's per-epoch throughput,
        relative to the previous epoch in the window, or to the realized
        previous epoch at the window start. Operating frictions only; capital
        is unaffected.
    corridors: {'members': {corridor: [transport designs]}, 'congestion': (u0, c)}
        Joint capacity: in every operating bin, the summed activity of member
        transport processes cannot exceed the corridor design's capacity. Flow
        above share u0 of capacity pays c per unit (convex congestion proxy).
    """
    out = {'switching': [], 'congestion': [], 'corridor_use': {}}
    if not extras:
        return out
    H, T = sc.hours, sc.periods
    sw = extras.get('switching')
    if sw and sw.get('cost', 0) > 0:
        store = extras.setdefault('_through', {})
        for name, xs in rec.items():
            d = sc.designs.get(name)
            if d is None or d.kind != 'process':
                continue
            through = lp.lpSum(H * x for x in xs)
            store[name, k] = through
            if k > k0:
                prev = store.get((name, k - 1), 0.0)
            elif sw.get('previous') is None:
                continue  # no realized predecessor (first epoch of a history): no charge
            else:
                prev = sw['previous'].get(name, 0.0)
            dv = lp.LpVariable(f"sw{tag}_{k}_{len(out['switching'])}", 0)
            prob += dv >= through - prev
            prob += dv >= prev - through
            out['switching'].append(sw['cost'] * dv)
        # designs active last epoch but absent from rec this epoch are forced to zero
        # and have no variable; their drop is charged at the realized previous value.
        if k == k0:
            for name, x in (sw.get('previous') or {}).items():
                d = sc.designs.get(name)
                if d is not None and d.kind == 'process' and name not in rec and x > 0:
                    out['switching'].append(sw['cost'] * x)
        else:
            for (name, kk), expr in list(store.items()):
                if kk == k - 1 and name not in rec:
                    out['switching'].append(sw['cost'] * expr)
    cor = extras.get('corridors')
    if cor:
        u0, cc = cor.get('congestion', (1.0, 0.0))
        for ci, (cname, members) in enumerate(sorted(cor['members'].items())):
            cap = caps.get(cname, 0.0)
            use = []
            for t in range(T):
                flow = lp.lpSum(rec[m][t] for m in members if m in rec)
                prob += flow <= cap, f"corridor_{tag}_{k}_{ci}_{t}"
                if cc > 0 and u0 < 1:
                    ex = lp.LpVariable(f"cong{tag}_{k}_{ci}_{t}", 0)
                    prob += ex >= flow - u0 * cap
                    out['congestion'].append(H * cc * ex)
                use.append(flow)
            out['corridor_use'][cname] = use
    return out


def _build_window(prob, sc: Scenario, traj: "Trajectory", prm: "Params", k0: int, k1: int,
                  history: List["Vintage"], m_new: Optional[int], expectations: str,
                  budget, forbid, tag: str = "", shared: Optional[dict] = None,
                  contingencies: Optional[list] = None, integration=None, completed_tasks=None,
                  stocks=None, stock_state=None, projects=None, realizability=None, capability_grants=None,
                  extras=None):
    """Add one scenario's window to prob. If `shared` is given, decisions in epoch k0
    (builds, lumps, introductions, retirements) are taken from it, so several
    scenarios can share their first-epoch decisions (non-anticipativity)."""
    validate_flow_system(sc)
    if extras:
        extras = dict(extras); extras['_through'] = {}
    integration = migration_integration(sc,integration)
    validate_needs(sc, K=traj.K, epoch=k0, contingencies=contingencies)
    validate_attributes(sc, K=traj.K, epoch=k0, contingencies=contingencies)
    stock_previous = validate_context(sc, stocks, traj.K, k0, stock_state, contingencies)
    projects = [] if projects is None else list(projects)
    if integration is not None and m_new is not None:
        raise ValueError("Explicit integration tasks and legacy m_new cannot be combined")
    period_weight = annual_to_block(sc)
    if not 0 <= prm.fom_share <= 1:
        raise ValueError("fom_share must lie in [0, 1]")
    if contingencies:
        from math import isfinite
        weights = [float(c['p']) for c in contingencies]
        if any(not isfinite(p) or p < 0 for p in weights) or sum(weights) > 1.0:
            raise ValueError("Contingency probabilities must be nonnegative and sum to at most one")
    K = range(k0, k1 + 1)
    pk = (lambda k: k) if expectations == "true" else (lambda k: k0)
    own = shared is None
    shared = {} if own else shared
    obj = []
    ah = {}
    for i, v in enumerate(history):
        for k in K:
            ub = v.alive if k < v.built + v.life else 0.0
            if k == k0 and ("ah", i) in shared:
                ah[i, k] = shared[("ah", i)]
            else:
                ah[i, k] = lp.LpVariable(f"ah{tag}_{i}_{k}", 0, ub)
                if k == k0:
                    shared[("ah", i)] = ah[i, k]
            if k > k0:
                prob += ah[i, k] <= ah[i, k - 1]
    # Previously ordered but not-yet-commissioned projects are sunk commitments.
    # A rolling policy may cancel remaining WIP before commissioning; canceled
    # capacity is stranded and cannot reappear.
    project_alive, project_cancel = {}, {}
    for pi, project in enumerate(projects):
        if project.commission <= k0:
            continue
        if ('project_cancel', pi) in shared:
            cancel = shared[('project_cancel', pi)]
        else:
            cancel = lp.LpVariable(f"cancel{tag}_{pi}_{k0}", 0, project.capacity)
            shared[('project_cancel', pi)] = cancel
        project_cancel[pi] = cancel
        remaining = project.capacity - cancel
        for k in K:
            if project.commission <= k < project.commission + project.life:
                project_alive[pi, k] = lp.LpVariable(f"pa{tag}_{pi}_{k}", 0, project.capacity)
                if k == project.commission:
                    prob += project_alive[pi, k] == remaining
                else:
                    prob += project_alive[pi, k] <= project_alive[pi, k - 1]
    build, z, an = {}, {}, {}
    installed = {v.design for v in history if v.alive > 1e-6}
    for name, d in sc.designs.items():
        for v in K:
            if not traj.available(name, pk(v)) or name in forbid or not buildable(sc,d,v):
                continue
            if v == k0 and ("x", name) in shared:
                build[name, v] = shared[("x", name)]
                if ("z", name) in shared:
                    z[name, v] = shared[("z", name)]
            else:
                build[name, v] = lp.LpVariable(f"x{tag}_{name}_{v}", 0, traj.build_cap(name, pk(v), d.max_cap))
                if d.fixed_cost > 0:
                    z[name, v] = lp.LpVariable(f"z{tag}_{name}_{v}", cat="Binary")
                    prob += build[name, v] <= d.max_cap * z[name, v]
                if v == k0:
                    shared[("x", name)] = build[name, v]
                    if (name, v) in z:
                        shared[("z", name)] = z[name, v]
            commission = v + traj.lead(name, pk(v))
            for k in K:
                if commission <= k < commission + prm.life[name]:
                    if v == k0 and k == commission and ("an", name) in shared:
                        an[name, v, k] = shared[("an", name)]
                        continue
                    an[name, v, k] = lp.LpVariable(f"an{tag}_{name}_{v}_{k}", 0)
                    prev = an.get((name, v, k - 1))
                    if k == commission:
                        prob += an[name, v, k] == build[name, v]
                    else:
                        prob += an[name, v, k] <= prev
                    if v == k0 and k == commission:
                        shared[("an", name)] = an[name, v, k]
    if m_new is not None:
        intro = {}
        for name in sc.designs:
            if name in installed:
                continue
            for v in K:
                if v == k0 and ("i", name) in shared:
                    intro[name, v] = shared[("i", name)]
                else:
                    intro[name, v] = lp.LpVariable(f"i{tag}_{name}_{v}", cat="Binary")
                    if v == k0:
                        shared[("i", name)] = intro[name, v]
            for v in K:
                if (name, v) in build:
                    prob += build[name, v] <= sc.designs[name].max_cap * lp.lpSum(
                        intro[name, j] for j in K if j <= v)
                    # an introduction is an actual first build (at least 1 unit), not a free option
                    prob += build[name, v] >= 1.0 * intro[name, v]
                else:
                    prob += intro[name, v] == 0
        for v in K:
            if v == k0 and not own:
                continue
            prob += lp.lpSum(intro[n, v] for n in sc.designs if (n, v) in intro) <= m_new
    ih = None
    if integration is not None:
        ih = add_integration_constraints(prob, sc, traj, k0, k1, history, build, an,
                                         integration, completed_tasks, shared, tag)
    raw_alive = {}
    for k in K:
        for name in sc.designs:
            terms = [ah[i,k] for i,vv in enumerate(history) if vv.design == name]
            terms += [an[name,v,k] for v in K if (name,v,k) in an]
            terms += [project_alive[pi,k] for pi,project in enumerate(projects) if project.design == name and (pi,k) in project_alive]
            if terms: raw_alive[name,k] = terms
    rh = None
    if realizability is not None:
        rh = add_realizability_constraints(prob, sc, traj, K, build, raw_alive, realizability, capability_grants, shared, tag)
    ops = {}
    for k in K:
        p = pk(k)
        w = traj.discount ** k
        caps = {}
        for name in sc.designs:
            terms = raw_alive.get((name,k), [])
            if terms:
                caps[name] = rh['usable'][name,k] if rh is not None else lp.lpSum(terms)
        cap_cost, fom = [], []
        for (name, v), x in build.items():
            commission = v + traj.lead(name, pk(v))
            if v <= k < commission + prm.life[name]:
                d = sc.designs[name]
                ann = d.annual_cost * traj.mult(name, pk(v))
                cap_cost.append((1 - prm.fom_share) * ann * period_weight * x)
                if (name, v) in z:
                    cap_cost.append(d.fixed_cost * traj.mult(name, pk(v)) * period_weight * z[name, v])
        for (name, v, kk), a in an.items():
            if kk == k:
                ann = sc.designs[name].annual_cost * traj.mult(name, pk(v))
                commission = v + traj.lead(name, pk(v))
                fom.append(prm.fom_share * ann * (1 + prm.aging * (k - commission)) * period_weight * a)
        for i, v in enumerate(history):
            fom.append(prm.fom_share * v.annual_cost * (1 + prm.aging * (k - v.built)) * period_weight * ah[i, k])
        for pi, project in enumerate(projects):
            if (pi, k) in project_alive:
                fom.append(prm.fom_share * project.annual_cost *
                           (1 + prm.aging * (k - project.commission)) * period_weight * project_alive[pi, k])
        named_demand = {q.name: traj.demand(q.name, p) for q in sc.flow_system.demands} if sc.flow_system is not None else None
        named_resource = ({q.name: traj.resource(q.name, p) for q in sc.flow_system.resources}
                          if sc.flow_system is not None and traj.resource_scale else None)
        cost, emis, unmet, fuel, rec, fb = _op_block(prob, sc, caps, k, traj.demand_mult[p],
                                                 traj.fuel_price[p], f"{tag}k{k}", need_value_epoch=p,
                                                 demand_scale=named_demand, resource_scale=named_resource)
        extra_costs = _add_realism_terms(prob, sc, caps, rec, k, k0, extras, tag, ops)
        stock_opening = stock_previous
        stock_handle, stock_previous = add_stock_epoch(prob, sc, stocks, k, stock_opening, fb, tag=f'{tag}normal')
        stock_charges = [] if stock_handle is None else [v["cost"] for v in stock_handle.values()]
        # contingency states: the same operating problem with some designs lost (and/or
        # renewable profiles scaled), each weighted by its probability; unserved demand
        # in a contingency is priced at VOLL like any other shortfall.
        cont = contingencies or []
        pn = 1.0 - sum(c["p"] for c in cont)
        ebenefit = [pn * v for v in fb["need_block"]["benefits"]]
        ecost = [pn * x for x in cost]; eemis = [pn * x for x in emis]; eunmet = [pn * x for x in unmet]
        states = [dict(name="normal", probability=pn, fuel=fuel, rec=rec,
                       unmet=unmet, emis=emis, cost=cost, flow=fb, stocks=stock_handle)]
        for ci, c in enumerate(cont):
            caps_c = {n: e for n, e in caps.items() if n not in c.get("fail", ())}
            sc_c = sc
            if c.get("profile_scale") is not None:
                sc_c = replace(sc, profiles={kk: [x * c["profile_scale"] for x in v] for kk, v in sc.profiles.items()})
            cc, ee, uu, ff, rr, fbc = _op_block(prob, sc_c, caps_c, k, traj.demand_mult[p], traj.fuel_price[p], f"{tag}k{k}c{ci}", demand_scale=named_demand)
            cstock, _ = add_stock_epoch(prob, sc_c, stocks, k, stock_opening, fbc, tag=f'{tag}c{ci}')
            states.append(dict(name=c.get("name", f"contingency_{ci}"), probability=c["p"],
                               fuel=ff, rec=rr, unmet=uu, emis=ee, cost=cc, flow=fbc, stocks=cstock,
                               fail=list(c.get("fail", ())), profile_scale=c.get("profile_scale")))
            ecost += [c["p"] * x for x in cc]; eemis += [c["p"] * x for x in ee]; eunmet += [c["p"] * x for x in uu]
            ebenefit += [c["p"] * v for v in fbc["need_block"]["benefits"]]
        vintages = [dict(design=v.design, built=v.built, alive=ah[i, k],
                         annual_cost=v.annual_cost, life=v.life)
                    for i, v in enumerate(history)]
        vintages += [dict(design=name, built=v + traj.lead(name, pk(v)), alive=a,
                          annual_cost=sc.designs[name].annual_cost * traj.mult(name, pk(v)),
                          life=prm.life[name])
                     for (name, v, kk), a in an.items() if kk == k]
        vintages += [dict(design=project.design, built=project.commission, alive=project_alive[pi, k],
                          annual_cost=project.annual_cost, life=project.life)
                     for pi, project in enumerate(projects) if (pi, k) in project_alive]
        integration_charges = [] if ih is None else [
            ih["spec"].tasks[t].completion_cost * q for (t,j),q in ih["done"].items() if j==k]
        realizability_charges = [] if rh is None else [
            realizability.capabilities[c].acquire_cost*q for (c,j),q in rh['acquire'].items() if j==k]
        ops[k] = dict(extra_costs=extra_costs, service_benefit=ebenefit, stocks=stock_handle, stock_charges=stock_charges, integration_charges=integration_charges, realizability_charges=realizability_charges, states=states, vintages=vintages, cost=ecost, emis=eemis, unmet=eunmet, fuel=fuel, rec=rec, cap=caps,
                      capital=cap_cost, fom=fom, project_alive=project_alive, project_cancel=project_cancel)
        obj.append(w * (lp.lpSum(cap_cost) + lp.lpSum(fom) + lp.lpSum(ecost) + lp.lpSum(integration_charges) + lp.lpSum(realizability_charges) + lp.lpSum(stock_charges) - lp.lpSum(ebenefit)
                        + lp.lpSum(extra_costs['switching']) + lp.lpSum(extra_costs['congestion'])))
        if budget is not None and (k > k0 or own):
            prob += lp.lpSum(
                sc.designs[n].annual_cost * traj.mult(n, pk(v)) * x
                + (sc.designs[n].fixed_cost * traj.mult(n, pk(v)) * z[n, v] if (n, v) in z else 0)
                for (n, v), x in build.items() if v == k) <= budget[k]
    return obj, ops, dict(ah=ah, an=an, build=build, lump=z, integration=ih, realizability=rh,
                               project_alive=project_alive, project_cancel=project_cancel,
                               projects=projects,
                               commission={(n,v): v + traj.lead(n, pk(v)) for (n,v) in build}), shared


def _extract(sc, K, ops, h):
    _Wt = period_weights(sc)
    V = lambda e: float(lp.value(e) or 0.0)
    out = {"epochs": {}}
    integration_handle = h.get("integration")
    def keep_build(name, epoch, x):
        if integration_handle is None:
            return V(x) > (1e-10 if sc.flow_system is not None or enabled(sc) or attributes_enabled(sc) else 1e-4)  # Retain physically small optional-service builds.
        r = integration_handle["release"].get((name, epoch))
        return V(x) > 1e-8 or (r is not None and V(r) > 0.5)
    for k in K:
        o = ops[k]
        out["epochs"][k] = {
            "capacity": {n: V(e) for n, e in o["cap"].items()},
            "ops_cost": V(lp.lpSum(o["cost"])),
            "capital": V(lp.lpSum(o["capital"])),
            "fom": V(lp.lpSum(o["fom"])),
            "integration_cost": V(lp.lpSum(o["integration_charges"])),
            "realizability_cost": V(lp.lpSum(o.get("realizability_charges",[]))),
            "stock_cost": V(lp.lpSum(o["stock_charges"])),
            "switching_cost": V(lp.lpSum(o["extra_costs"]["switching"])),
            "congestion_cost": V(lp.lpSum(o["extra_costs"]["congestion"])),
            "corridor_use": {c: [V(x) for x in xs] for c, xs in o["extra_costs"]["corridor_use"].items()},
            "service_benefit": V(lp.lpSum(o["service_benefit"])),
            "stocks": extract_stock_epoch(o["stocks"]),
            "emissions": V(lp.lpSum(o["emis"])),
            "unmet_MWh": V(lp.lpSum(o["unmet"])),
            "throughput": {n: sc.hours * sum(V(x) for x in xs) for n, xs in o["rec"].items()},
            # weighted annual energy by design (period weights applied) and hourly activity, for energy balances
            "energy": {n: sc.hours * sum(_Wt[t % len(_Wt)] * V(x) for t, x in enumerate(xs)) for n, xs in o["rec"].items()},
            "hourly": {n: [V(x) for x in xs] for n, xs in o["rec"].items()},
            "vintages": [{**v, "alive": V(v["alive"])} for v in o["vintages"]],
            "operating_states": [
                {"name": state["name"], "probability": state["probability"],
                 "fuel_purchased_MWh": sc.hours * sum(V(x) for x in state["fuel"]),
                 "throughput": {n: sc.hours * sum(V(x) for x in xs) for n, xs in state["rec"].items()},
                 "unmet_MWh": V(lp.lpSum(state["unmet"])),
                 "emissions": V(lp.lpSum(state["emis"])),
                 "ops_cost": V(lp.lpSum(state["cost"])),
                 "fail": state.get("fail", []), "profile_scale": state.get("profile_scale"),
                 "flow": extract_flow_block(sc,state["flow"]),
                 "physical": extract_physical(sc,state["flow"]["physical"]) if sc.flow_system is not None else {},
                 "stocks": extract_stock_epoch(state.get("stocks"))}
                for state in o["states"]],
            "lump_builds": {n: V(x) for (n, v), x in h["lump"].items() if v == k and V(x) > 0.5},
            "builds": {n: V(x) for (n, v), x in h["build"].items() if v == k and keep_build(n, v, x)},
            "orders": {n: V(x) for (n, v), x in h["build"].items() if v == k and keep_build(n, v, x)},
            "commissioned": {
                n: sum(V(a) for (nn,v,kk),a in h["an"].items()
                       if nn == n and kk == k and h["commission"].get((nn,v)) == k)
                   + sum(V(a) for (pi,kk),a in h.get("project_alive", {}).items()
                         if kk == k and h["projects"][pi].design == n and h["projects"][pi].commission == k)
                for n in sc.designs
            },
            "wip": (
                [{"design": p.design, "ordered": p.ordered, "commission": p.commission,
                  "capacity": p.capacity, "canceled": V(h["project_cancel"].get(pi, 0.0))}
                 for pi, p in enumerate(h.get("projects", [])) if p.commission > k]
                + [{"design": n, "ordered": v, "commission": h["commission"][(n,v)],
                    "capacity": V(x), "canceled": 0.0}
                   for (n,v),x in h["build"].items()
                   if v <= k < h["commission"][(n,v)] and V(x) > 1e-8]
            ),
            "stranded_work": sum(V(x) for x in h.get("project_cancel", {}).values()) if k == min(K) else 0.0,
        }
        rh = h.get("realizability")
        if rh is not None:
            out["epochs"][k]["realizability"] = extract_realizability(rh,k,V)
        ih = h.get("integration")
        if ih is not None and sc.interface_system is not None:
            actions=[t for (t,j),q in ih["done"].items() if j==k and V(q)>.5 and t.startswith('interface_migration:')]
            out['epochs'][k]['interface_migration'] = {
                'completed_actions':[t.split(':',1)[1] for t in actions],
                'preparation_cost':sum(ih['spec'].tasks[t].completion_cost for t in actions),
                'accounting':'subset of integration_cost; do not add again'}
        if ih is not None:
            completed = sorted(t for (t,j),q in ih["done"].items() if j==k and V(q)>0.5)
            known = set(ih["known"]) | {t for (t,j),q in ih["done"].items() if j<=k and V(q)>0.5}
            out["epochs"][k]["integration"] = {
                "completed_tasks":completed, "known_tasks":sorted(known),
                "effort":sum(ih["spec"].tasks[t].effort for t in completed),
                "budget":ih["spec"].limit(k),
                "first_deployments":sorted(n for (n,j),r in ih["release"].items() if j==k and V(r)>0.5),
            }
    out["hist_alive"] = {key: V(a) for key, a in h["ah"].items()}
    out["new_alive"] = {key: V(a) for key, a in h["an"].items()}
    out["build"] = {key: V(x) for key, x in h["build"].items()}
    out["project_cancel"] = {key: V(x) for key, x in h.get("project_cancel", {}).items()}
    return out


def solve_window(sc: Scenario, traj: "Trajectory", prm: "Params", k0: int, k1: int,
                 history: List["Vintage"], m_new: Optional[int] = None,
                 expectations: str = "true", budget: Optional[List[float]] = None,
                 forbid: Tuple[str, ...] = (), time_limit: float = 120.0, contingencies=None,
                 integration=None, completed_tasks=None, stocks=None, stock_state=None, projects=None, realizability=None, capability_grants=None,
                 extras=None, institutions=None):
    """Optimize builds, retirements and operation over epochs k0..k1 for one trajectory.

    institutions : optional list of techgraph.institutions objects (aggregate requirements).
                   None (default) leaves the window unchanged.

    expectations='true'  : future epochs use the trajectory as given.
    expectations='static': future epochs use epoch-k0 values (fuel, demand, costs).
    forbid               : designs that may not be built in this window.
    """
    prob = lp.LpProblem("stage2", lp.LpMinimize)
    obj, ops, h, _ = _build_window(prob, sc, traj, prm, k0, k1, history, m_new, expectations,
                                   budget, forbid, contingencies=contingencies,
                                   integration=integration, completed_tasks=completed_tasks,
                                   stocks=stocks, stock_state=stock_state, projects=projects, realizability=realizability, capability_grants=capability_grants,
                                   extras=extras)
    inst_handles = None
    if institutions:
        from .institutions import add_institutions
        inst_terms, inst_handles = add_institutions(prob, sc, k0, k1, ops, institutions,
                                                    discount=traj.discount, annual_factor=365.0 / float(sc.days))
        obj = list(obj) + inst_terms
    prob += lp.lpSum(obj)
    prob.solve(mip_solver(msg=False, timeLimit=time_limit, presolve=sc.interface_system is None))
    require_optimal(prob)
    out = _extract(sc, range(k0, k1 + 1), ops, h)
    if inst_handles is not None:
        from .institutions import extract_institutions
        out["institutions"] = extract_institutions(prob, inst_handles)
    out["solver"] = solver_metadata(prob)
    out["status"] = lp.LpStatus[prob.status]
    out["objective"] = float(lp.value(prob.objective) or 0.0)
    return out


def solve_window_stochastic(sc: Scenario, trajs: List["Trajectory"], weights: List[float],
                            prm: "Params", k0: int, k1: int, history: List["Vintage"],
                            m_new: Optional[int] = None, budget=None, forbid=(),
                            time_limit: float = 300.0, integration=None, completed_tasks=None,
                            stocks=None, stock_state=None, projects=None, realizability=None, capability_grants=None):
    """Scenario-path stochastic window.

    Investment/capability/WIP decisions in epoch k0 are shared across scenarios.
    Operation in k0 is scenario-adaptive: uncertainty is interpreted as revealed
    after first-stage investment but before operation. Later decisions adapt by path.
    Active stocks evolve independently on every scenario path from the same inherited
    opening state. Attributes and optional service are evaluated pathwise.
    """
    if len(trajs) != len(weights) or not trajs:
        raise ValueError("One probability weight per nonempty scenario trajectory is required")
    if any(w < 0 for w in weights) or abs(sum(weights)-1.0) > 1e-8:
        raise ValueError("Stochastic scenario weights must be nonnegative and sum to one")
    prob = lp.LpProblem("stage2_stoch", lp.LpMinimize)
    shared = None
    parts = []
    total = []
    for sidx, (tr, w) in enumerate(zip(trajs, weights)):
        state_s = stock_state[sidx] if isinstance(stock_state, (list, tuple)) else stock_state
        obj, ops, h, shared = _build_window(prob, sc, tr, prm, k0, k1, history, m_new, "true",
                                            budget, forbid, tag=f"s{sidx}", shared=shared,
                                            integration=integration, completed_tasks=completed_tasks,
                                            stocks=stocks, stock_state=state_s, projects=projects,
                                            realizability=realizability, capability_grants=capability_grants)
        total.append(w * lp.lpSum(obj))
        parts.append((ops, h))
    if m_new is not None:
        prob += lp.lpSum(v for key, v in shared.items() if key[0] == "i") <= m_new
    prob += lp.lpSum(total)
    prob.solve(mip_solver(msg=False, timeLimit=time_limit, presolve=sc.interface_system is None))
    require_optimal(prob)
    scenario_outputs=[]
    for ops,h in parts:
        scenario_outputs.append(_extract(sc, range(k0,k1+1), ops, h))
    out=scenario_outputs[0]
    out["scenarios"]=scenario_outputs
    out["scenario_weights"]=list(weights)
    out["solver"] = solver_metadata(prob)
    out["status"] = lp.LpStatus[prob.status]
    out["objective"] = float(lp.value(prob.objective) or 0.0)
    return out


# --------------------------------------------------------------------------
def run_policy(sc: Scenario, traj: Trajectory, prm: Params, history0: List[Vintage],
               horizon: int = 1, expectations: str = "true", m_new: Optional[int] = None,
               budget=None, forbid=(), contingencies=None, integration=None, stocks=None, stock_state0=None, projects0=None, realizability=None, capability_grants0=None, time_limit: float = 120.0, epoch_callback=None):
    """Rolling-horizon policy. horizon >= K with true expectations is perfect foresight."""
    integration = migration_integration(sc,integration)
    if horizon < 1:
        raise ValueError("Planning horizon must be positive")
    if integration is not None:
        if m_new is not None:
            raise ValueError("Explicit integration tasks and legacy m_new cannot be combined")
        integration.validate(sc, traj.K)
    if realizability is not None:
        realizability.validate(sc)
    initial_stocks = validate_context(sc, stocks, traj.K, 0, stock_state0, contingencies)
    stock_state = initial_stocks
    stock_config = None if stocks is None else stocks.manifest(sc)
    history = [replace(v) for v in history0]
    projects = [replace(p) for p in (projects0 or [])]
    capability_grants = list(capability_grants0 or [])
    completed = None if integration is None else integration.known(history)
    config = None if integration is None else integration.manifest(sc)
    record = []
    snapshots = []
    solver_log = []
    ks = range(traj.K)
    if horizon >= traj.K and expectations == "true":
        sol = solve_window(sc, traj, prm, 0, traj.K - 1, history, m_new, "true", budget, forbid,
                           contingencies=contingencies, integration=integration, completed_tasks=completed,
                           stocks=stocks, stock_state=stock_state, projects=projects, realizability=realizability, capability_grants=capability_grants, time_limit=time_limit)
        for k in ks:
            record.append(sol["epochs"][k])
            if epoch_callback is not None:
                from copy import deepcopy
                epoch_callback({'epoch': k, 'operating': deepcopy(record[-1]), 'solver': deepcopy(sol['solver'])})
        return reconcile_run(sc, traj, prm, {"epochs": record, "status": sol["status"],
                             "solver_log": [sol["solver"]], "window_objective": sol["objective"],
                             "integration_config":config, "realizability_config":None if realizability is None else realizability.manifest(),
                             "stock_config":stock_config, "initial_stocks":initial_stocks})
    for k in ks:
        # Projects reaching their commissioning epoch become installed vintages before operation.
        due = [p for p in projects if p.commission <= k]
        for p in due:
            history.append(Vintage(p.design, p.commission, p.capacity, p.capacity,
                                   p.annual_cost, p.fixed_cost, p.life))
        projects = [p for p in projects if p.commission > k]
        k1 = min(traj.K - 1, k + horizon - 1)
        sol = solve_window(sc, traj, prm, k, k1, history, m_new, expectations, budget, forbid,
                           contingencies=contingencies, integration=integration, completed_tasks=completed,
                           stocks=stocks, stock_state=stock_state, projects=projects, realizability=realizability, capability_grants=capability_grants, time_limit=time_limit)
        solver_log.append(sol["solver"])
        e = sol["epochs"][k]
        if due:
            commissioned = dict(e.get("commissioned", {}))
            for project in due:
                commissioned[project.design] = commissioned.get(project.design, 0.0) + project.capacity
            e["commissioned"] = commissioned
        if stocks is not None:
            stock_state = {n: s["stock_end"] for n, s in e["stocks"].items()}
        if integration is not None:
            completed.update(e["integration"]["completed_tasks"])
        if realizability is not None:
            for g in e.get("realizability",{}).get("acquired",[]):
                capability_grants.append(CapabilityGrant(g["capability"],g["acquired"],g["ready_from"],g["ready_until"]))
        record.append(e)
        # apply epoch-k decisions: retirements of inherited vintages, new builds
        for i, v in enumerate(history):
            v.alive = sol["hist_alive"][i, k]
        # Apply first-epoch cancellation of inherited work in progress.
        canceled = sol.get("project_cancel", {})
        if canceled:
            kept = []
            for pi, p in enumerate(projects):
                remaining = max(0.0, p.capacity - canceled.get(pi, 0.0))
                if remaining > 1e-8:
                    kept.append(replace(p, capacity=remaining))
            projects = kept
        for (n, v), x in sol["build"].items():
            if v == k and (n in e["builds"] if integration is not None or sc.flow_system is not None or enabled(sc) or attributes_enabled(sc) else x > 1e-4):
                d = sc.designs[n]
                lead = traj.lead(n, k)
                if lead == 0:
                    history.append(Vintage(n, k, x, sol["new_alive"].get((n, k, k), x),
                                           d.annual_cost * traj.mult(n, k), d.fixed_cost * traj.mult(n, k),
                                           prm.life[n]))
                else:
                    projects.append(Project(n, k, x, k + lead,
                                            d.annual_cost * traj.mult(n, k),
                                            d.fixed_cost * traj.mult(n, k), prm.life[n]))
        snapshots.append([replace(v) for v in history])
        if epoch_callback is not None:
            from copy import deepcopy
            epoch_callback({'epoch': k, 'operating': deepcopy(e), 'solver': deepcopy(sol['solver'])})
    return reconcile_run(sc, traj, prm, {"epochs": record, "status": "Rolling", "snapshots": snapshots,
                         "solver_log": solver_log, "integration_config":config, "realizability_config":None if realizability is None else realizability.manifest(),
                         "stock_config":stock_config, "initial_stocks":initial_stocks})


def path_cost(traj: Trajectory, run) -> float:
    """Discounted avoidable cost: capital of new vintages, O&M of all capacity, operation."""
    return sum(traj.discount ** k * (e["capital"] + e["fom"] + e["ops_cost"] + e.get("integration_cost", 0.0) + e.get("realizability_cost",0.0) + e.get("stock_cost", 0.0)
                                         + e.get("switching_cost", 0.0) + e.get("congestion_cost", 0.0))
               for k, e in enumerate(run["epochs"]))


def path_benefit(traj: Trajectory, run) -> float:
    """Discounted value of optional service actually delivered, not foregone benefit."""
    return sum(traj.discount**k * e.get("service_benefit",0.0) for k,e in enumerate(run["epochs"]))

def path_objective(traj: Trajectory, run) -> float:
    """Expenditure minus benefit: the criterion optimized with optional service."""
    return path_cost(traj,run)-path_benefit(traj,run)

def path_net_value(traj: Trajectory, run) -> float:
    return -path_objective(traj,run)
