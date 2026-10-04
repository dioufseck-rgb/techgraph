"""The Washington metropolitan area water supply system in Techgraph, operated by rolling-horizon optimization.

Each day d, operators plan days d+1..d+H with forecast flows (recession from today's flow), with Jennings Randolph
releases already in transit fixed (nine-day travel time). They commit tomorrow's decisions: Little Seneca release,
Occoquan and Patuxent transfers, Milestone use, and the Jennings Randolph release arriving at d+9. Day d+1 is then
realized with actual flows and the committed decisions fixed; any shortfall is a deficit.

Operating priorities are expressed as values on water left in storage at the end of each plan, by storage zone:
upper zones (above 60% of capacity, the voluntary-restriction trigger) are used first, the Occoquan and Patuxent
before Jennings Randolph and Little Seneca, and lower zones are protected most. With a short horizon and forecast
information, this is myopic optimization per decision period; lengthening the horizon or giving it actual flows
measures the value of foresight.

Inputs are those of prrism_lite (ICPRB 2025 study), so the two can be compared directly.
"""
import os, sys, datetime as dt
from dataclasses import dataclass, field, replace
os.environ.setdefault('TECHGRAPH_BACKEND', 'scipy')
sys.path.insert(0, os.environ.get('TECHGRAPH_PATH', os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..'))))
from techgraph.catalog import Design, Scenario                 # noqa: E402
from techgraph.model import solve                              # noqa: E402
from techgraph.demands import Demand                           # noqa: E402
import prrism_lite as PL                                       # noqa: E402

UP = 0.40          # share of capacity in the upper zone (above the 60% trigger)
LOCS = ('LF', 'WMA', 'JRL', 'LSL', 'OCCL', 'PAXL', 'MSL', 'D')


@dataclass
class Policy:
    """Values per MG left in storage at the end of a plan (operating priorities), and the deficit penalty."""
    values: dict = field(default_factory=lambda: dict(OCC_UP=1.0, PAX_UP=1.0, MS=1.5, JR_UP=2.0, LS_UP=2.0,
                                                      OCC_LO=5.0, PAX_LO=5.0, JR_LO=8.0, LS_LO=8.0))
    deficit_cost: float = 1000.0
    horizon: int = 10
    perfect: bool = False          # True: plans see actual future flows (foresight) instead of forecasts
    rule_offpotomac: bool = False  # True: Occoquan and Patuxent transfers follow prrism_lite's load-shift rules
    same_info: bool = False        # True: rules judged on the next day's actual flow, and Little Seneca responds same-day (as prrism_lite)


def designs(sc_year, pax_max):
    D = Design
    zone = lambda n, form, loc, cap_rate: D(n, 'store', annual_cost=0.0, form=form, loc=loc, duration_h=1.0, eta_c=1.0, eta_d=1.0, max_cap=1e9)
    d = [D('RIVER', 'renewable', annual_cost=0.0, loc='LF', profile='lf', form_out='water', max_cap=1e9),
         D('JR_IN', 'renewable', annual_cost=0.0, loc='JRL', profile='jr', form_out='jrin', max_cap=1e9),
         D('JR_FILL', 'convert', annual_cost=0.0, form_in='jrin', form_out='jrw', loc='JRL', eff=1.0, max_cap=1e9),
         zone('JR_UP', 'jrw', 'JRL', 0), zone('JR_LO', 'jrw', 'JRL', 0),
         D('JR_REL', 'transport', annual_cost=0.0, form='jrw', loc_from='JRL', loc_to='LF', loss=0.0, max_cap=1e9),
         D('JR_OUT', 'convert', annual_cost=0.0, form_in='jrw', form_out='water', loc='LF', eff=1.0, max_cap=1e9),
         D('JR_PASS', 'transport', annual_cost=0.0, form='jrin', loc_from='JRL', loc_to='LF', loss=0.0, max_cap=1e9),
         D('JR_PASSC', 'convert', annual_cost=0.0, form_in='jrin', form_out='water', loc='LF', eff=1.0, max_cap=1e9),
         D('LS_IN', 'renewable', annual_cost=0.0, loc='LSL', profile='ls', form_out='lsin', max_cap=1e9),
         D('LS_FILL', 'convert', annual_cost=0.0, form_in='lsin', form_out='lsw', loc='LSL', eff=1.0, max_cap=1e9),
         zone('LS_UP', 'lsw', 'LSL', 0), zone('LS_LO', 'lsw', 'LSL', 0),
         D('LS_REL', 'transport', annual_cost=0.0, form='lsw', loc_from='LSL', loc_to='LF', loss=0.0, max_cap=1e9),
         D('LS_OUT', 'convert', annual_cost=0.0, form_in='lsw', form_out='water', loc='LF', eff=1.0, max_cap=1e9),
         D('LS_PASS', 'transport', annual_cost=0.0, form='lsin', loc_from='LSL', loc_to='LF', loss=0.0, max_cap=1e9),
         D('LS_PASSC', 'convert', annual_cost=0.0, form_in='lsin', form_out='water', loc='LF', eff=1.0, max_cap=1e9),
         D('INTAKES', 'transport', annual_cost=0.0, form='water', loc_from='LF', loc_to='WMA', loss=0.0, max_cap=1e9),
         D('OCC_IN', 'renewable', annual_cost=0.0, loc='OCCL', profile='occ', form_out='water', max_cap=1e9),
         zone('OCC_UP', 'water', 'OCCL', 0), zone('OCC_LO', 'water', 'OCCL', 0),
         D('OCC_T', 'transport', annual_cost=0.0, form='water', loc_from='OCCL', loc_to='WMA', loss=0.0, max_cap=1e9),
         D('PAX_IN', 'renewable', annual_cost=0.0, loc='PAXL', profile='pax', form_out='water', max_cap=1e9),
         zone('PAX_UP', 'water', 'PAXL', 0), zone('PAX_LO', 'water', 'PAXL', 0),
         D('PAX_T', 'transport', annual_cost=0.0, form='water', loc_from='PAXL', loc_to='WMA', loss=0.0, max_cap=1e9),
         D('MS_FILL', 'transport', annual_cost=0.0, form='water', loc_from='LF', loc_to='MSL', loss=0.0, max_cap=1e9),
         zone('MS', 'water', 'MSL', 0),
         D('MS_T', 'transport', annual_cost=0.0, form='water', loc_from='MSL', loc_to='WMA', loss=0.0, max_cap=1e9)]
    return {x.name: x for x in d}


def capacities(caps, pax_max):
    """Installed capacities (MG for stores, MGD for links); store rate limits are set by capacity (duration 1 day)."""
    c = {'RIVER': 1.0, 'JR_IN': 1.0, 'LS_IN': 1.0, 'OCC_IN': 1.0, 'PAX_IN': 1.0, 'JR_FILL': 1e6, 'LS_FILL': 1e6, 'JR_OUT': 1e6, 'LS_OUT': 1e6,
         'JR_PASSC': 1e6, 'LS_PASSC': 1e6, 'JR_REL': 2000.0, 'LS_REL': 500.0, 'JR_PASS': 1e6, 'LS_PASS': 1e6, 'INTAKES': 900.0,
         'OCC_T': 120.0, 'PAX_T': pax_max, 'MS_FILL': 40.0, 'MS_T': 20.0}
    for n, cap in (('JR', caps['JR']), ('LS', caps['LS']), ('OCC', caps['OCC']), ('PAX', caps['PAX'])):
        c[n + '_UP'] = UP * cap; c[n + '_LO'] = (1 - UP) * cap
    c['MS'] = max(caps['MILESTONE'], 1e-3)
    return c


def split(level, cap):
    lo = min(level, (1 - UP) * cap); return level - lo, lo


class WMA:
    def __init__(self, flows, year, annual_demand, k, policy=Policy(), extra_dc=0.0):
        self.flows, self.year, self.ad, self.k, self.pol, self.extra_dc = flows, year, annual_demand, k, policy, extra_dc
        self.caps = PL.CAPS(year); self.pax_max = 110.0 if year >= 2040 else 72.0
        self.des = designs(year, self.pax_max); self.capd = capacities(self.caps, self.pax_max)

    def inputs(self, d, q):
        """Daily inputs given natural Little Falls flow q (MGD) on day d."""
        m = d.month - 1; y = self.year
        cu = PL.CU_2018[m] + PL.CU_GROWTH[m] * (y - 2018) + PL.DC_CU[y] * PL.DC_MONTH[m]
        jr = max(0.0, q * PL.AREA['JR'] / PL.LF_AREA - PL.LUKE_TARGET)
        ls = max(0.0, q * PL.AREA['LS'] / PL.LF_AREA - PL.LS_FLOWBY)
        lf = q - jr - ls - cu + PL.RETURNS[y]
        occ = q * PL.AREA['OCC'] / PL.LF_AREA + PL.UOSA[y]
        pax = max(0.0, q * PL.AREA['PAX'] / PL.LF_AREA - PL.DUCKETT_FLOWBY)
        return dict(lf=lf, jr=jr, ls=ls, occ=occ, pax=pax)

    def scenario(self, days_inputs, demand, levels, fixed, values):
        T = len(days_inputs)
        prof = {key: [x[key] for x in days_inputs] for key in ('lf', 'jr', 'ls', 'occ', 'pax')}
        dem = (Demand('wma', 'WMA', tuple(demand), 'wma', 'municipal', form='water', shortage_cost=self.pol.deficit_cost),
               Demand('flowby', 'LF', tuple([PL.FLOWBY] * T), 'river', 'environment', form='water', shortage_cost=self.pol.deficit_cost))
        return Scenario(periods=T, hours=1.0, demand_D=[0.0] * T, hub_energy=0.0, hub_max_rate=0.0, profiles=prof, fuel_price_R=0.0,
                        voll=self.pol.deficit_cost, designs=self.des, extra_demand={}, demands=dem, locations=LOCS, fuel_sites=(),
                        store_initial=levels, store_terminal_value=values, fixed_activity=fixed)

    def run(self, start, end, record_levels=False):
        days = [d for d in sorted(self.flows) if start <= d <= end]
        caps = self.caps
        L = {'JR': caps['JR'], 'LS': caps['LS'], 'OCC': caps['OCC'], 'PAX': caps['PAX'], 'MS': caps['MILESTONE']}
        pipeline = {}
        out = []
        comb = caps['JR'] + caps['LS']
        for i, d in enumerate(days[:-1]):
            nxt = days[i + 1]
            frac = (L['JR'] + L['LS']) / comb
            summer = nxt.month in (6, 7, 8, 9)
            cut = (0.15 if summer else 0.05) if frac < 0.05 else ((0.05 if summer else 0.03) if frac < 0.60 else 0.0)
            dem_of = lambda dd: self.ad * PL.DEMAND_MONTH[dd.month - 1] * (1 - cut) + self.extra_dc * PL.DC_MONTH[dd.month - 1]
            H = min(self.pol.horizon, len(days) - 1 - i)
            hdays = days[i + 1:i + 1 + H]
            q0 = self.flows[d]
            fq = [(self.flows[x] if self.pol.perfect else q0 * self.k ** (j + 1)) for j, x in enumerate(hdays)]
            fin = [self.inputs(x, qq) for x, qq in zip(hdays, fq)]
            demand = [dem_of(x) for x in hdays]
            full = all(abs(L[n] - (caps[n] if n != 'MS' else caps['MILESTONE'])) < 1e-6 for n in ('JR', 'LS', 'OCC', 'PAX', 'MS'))
            surplus = min(f['lf'] - PL.FLOWBY - dm for f, dm in zip(fin, demand))
            act_in = self.inputs(nxt, self.flows[nxt])
            committed_today = pipeline.get(nxt, 0.0)
            if (not self.pol.rule_offpotomac) and full and surplus > 0 and not any(v > 0 for v in pipeline.values()) and act_in['lf'] - PL.FLOWBY - demand[0] > 0:
                out.append((nxt, L['JR'] + L['LS'], 0.0, cut > 0)); pipeline.pop(nxt, None)
                continue
            levels = {}
            for n in ('JR', 'LS', 'OCC', 'PAX'):
                levels[n + '_UP'], levels[n + '_LO'] = split(L[n], caps[n])
            levels['MS'] = L['MS']
            # JR releases already in transit arrive on plan days 0..7 (d+1..d+8)
            fixed = {('JR_REL', 'forward'): {j: pipeline.get(x, 0.0) for j, x in enumerate(hdays) if j < 8}}
            if self.pol.rule_offpotomac:            # same load-shift rules as prrism_lite, applied to each plan day
                occ_r, pax_r = {}, {}
                ro, rp = L['OCC'], L['PAX']                     # projected storage, so commitments stay feasible
                stress0 = act_in['lf'] - PL.FLOWBY < demand[0]
                for j, (f, dm) in enumerate(zip(fin, demand)):
                    stress = stress0 if self.pol.same_info else (f['lf'] - PL.FLOWBY < dm)
                    o = (min(120.0, max(45.0, 0.40 * 0.36 * dm + (40.0 if stress else 0.0))) if ro > 0.1 * caps['OCC'] else 45.0)
                    pp = (min(self.pax_max, 40.0 + (30.0 if stress else 0.0)) if rp > 1000.0 else 20.0)
                    o = max(0.0, min(o, ro + f['occ'] - 1e-6)); pp = max(0.0, min(pp, rp + f['pax'] - 1e-6))
                    occ_r[j], pax_r[j] = o, pp
                    ro = min(caps['OCC'], ro + f['occ'] - o); rp = min(caps['PAX'], rp + f['pax'] - pp)
                fixed[('OCC_T', 'forward')] = occ_r; fixed[('PAX_T', 'forward')] = pax_r
            vals = {n: v for n, v in self.pol.values.items()}
            plan = solve(self.scenario(fin, demand, levels, fixed, vals), [], existing=self.capd, fixed=True)
            A = plan.activity
            # commit tomorrow's decisions and the JR release arriving at d+9
            if H > 8:
                pipeline[hdays[8]] = A['JR_REL']['forward'][8]
            cap_now = lambda n, key: max(0.0, min(A[n]['forward'][0], L[key] + act_in[key.lower()] - 1e-6))
            dec = {('LS_REL', 'forward'): {0: min(A['LS_REL']['forward'][0], max(0.0, L['LS'] + act_in['ls'] - 1e-6))},
                   ('OCC_T', 'forward'): {0: cap_now('OCC_T', 'OCC')}, ('PAX_T', 'forward'): {0: cap_now('PAX_T', 'PAX')},
                   ('MS_T', 'forward'): {0: min(A['MS_T']['forward'][0], max(0.0, L['MS'] - 1e-6))},
                   ('JR_REL', 'forward'): {0: min(committed_today, max(0.0, L['JR'] + act_in['jr'] - 1e-6))}}
            # realize tomorrow with actual flows and committed decisions
            if self.pol.same_info:
                dec.pop(('LS_REL', 'forward'))               # Little Seneca covers the actual gap on the day, as in prrism_lite
            real = solve(self.scenario([act_in], [dem_of(nxt)], levels, dec, vals), [], existing=self.capd, fixed=True)
            R = real.activity
            for n in ('JR', 'LS', 'OCC', 'PAX'):
                L[n] = R[n + '_UP']['end'][0] + R[n + '_LO']['end'][0]
            L['MS'] = R['MS']['end'][0]
            deficit = sum(real.flexibility[x]['shortage'][0] for x in ('wma', 'flowby'))
            pipeline.pop(nxt, None)
            out.append((nxt, L['JR'] + L['LS'], deficit, cut > 0))
        return out


def metrics(rec):
    return dict(min_LS_JRws_bg=min(x[1] for x in rec) / 1000.0, deficit_days=sum(1 for x in rec if x[2] > 0.01),
                max_deficit_mgd=max(x[2] for x in rec))
