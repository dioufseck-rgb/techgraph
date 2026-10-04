"""A rule-following daily simulation of the Washington metropolitan area (WMA) water supply system, built from the
published description of CO-OP's PRRISM model (ICPRB, 2025 WMA Water Supply Study, Chapters 5-6 and Appendix A).

Purpose: replicate the study's historic-flow scenarios (Tables A.4-1 to A.4-9) as a first validation step, before the
same system is represented in Techgraph. Everything taken from the study is marked [study]; every approximation made
where the study is not specific is marked [approx].

Units: flows in MGD, storage in MG.
"""
import csv, math, datetime as dt
from dataclasses import dataclass, field

CFS_TO_MGD = 0.646317
LF_AREA = 11560.0                              # sq mi above Little Falls

# ---------------------------------------------------------------- inputs from the study
CU_2018 = [71.03, 70.21, 70.98, 107.56, 111.64, 120.74, 124.68, 122.50, 119.14, 108.16, 99.98, 68.46]   # [study] Table 6-4
CU_GROWTH = [0.09, 0.14, 0.15, 0.51, 0.53, 0.51, 0.49, 0.62, 0.59, 0.60, 0.57, 0.119]                   # MGD/yr
DC_CU = {2030: 1.3, 2045: 4.1, 2050: 4.7}                                                              # [study] Table A.3-1, medium
DC_MONTH = [0.7, 0.6, 0.6, 0.7, 0.9, 1.0, 1.5, 1.8, 1.5, 1.0, 0.9, 0.8]                                   # [study] Table A.3-2
RETURNS = {2030: 17.20 + 0.85 + 10, 2045: 18.99 + 0.93 + 13, 2050: 19.50 + 0.95 + 14}                  # [study] Table 5-2, to Potomac
UOSA = {2030: 35.70, 2045: 37.39, 2050: 37.95}                                                         # [study] Table 5-2, to Occoquan
# monthly demand factors, system-weighted from supplier long-term monthly means [study] Table 4-3
_MEANS = [(122.8, 156.3, 123.5, 22.2), (120.9, 154.1, 124.4, 22.0), (119.7, 150.4, 123.6, 22.5), (128.4, 154.0, 127.4, 25.4),
          (139.5, 161.3, 131.9, 28.5), (153.9, 170.5, 143.1, 33.7), (163.0, 178.0, 150.1, 36.0), (159.2, 174.2, 145.0, 34.8),
          (154.1, 170.0, 143.3, 32.6), (139.4, 159.3, 131.7, 27.3), (126.2, 154.1, 121.8, 23.3), (122.1, 152.0, 118.2, 22.3)]
_ANNUAL = 137.4 + 161.2 + 132.0 + 27.6
DEMAND_MONTH = [sum(m) / _ANNUAL for m in _MEANS]
# usable capacities, MG [study] Table 5-1 (2030 interpolated between 2025 and 2045)
def _cap(c2025, c2045, c2050, y):
    return c2025 + (c2045 - c2025) * (y - 2025) / 20 if y <= 2045 else c2045 + (c2050 - c2045) * (y - 2045) / 5
CAPS = lambda y: dict(JR=_cap(12857, 12456, 12356, y), LS=_cap(3843, 3763, 3743, y), PAX=_cap(10284, 9792, 9669, y), OCC=8170.0,
                      MILESTONE=1120.0 if y >= 2028 else 0.0, VULCAN=1700.0 if y >= 2040 else 0.0)
# [approx] drainage areas (sq mi) used to scale tributary reservoir inflows from the Little Falls natural flow
AREA = dict(JR=263.0, LS=20.5, PAX=132.0, OCC=570.0)
FLOWBY = 100.0                                    # [study] environmental flow-by at Little Falls
LUKE_TARGET = 77.6                                # [study] North Branch minimum flow at Luke, met from JR inflow first
LS_FLOWBY = 1.12                                  # [study]
DUCKETT_FLOWBY = 10.3                             # [study]


def load_flows(path_lf, path_por):
    """Daily natural flow at Little Falls (MGD), from the USGS adjusted series (01646502), with Oct 1929-Feb 1930
    filled from Point of Rocks (01638500) scaled by the median ratio over the overlap [approx]."""
    def read(p):
        out = {}
        for line in open(p):
            if line.startswith('USGS'):
                parts = line.rstrip('\n').split('\t')
                try: out[dt.date.fromisoformat(parts[2])] = float(parts[3]) * CFS_TO_MGD
                except ValueError: pass
        return out
    lf, por = read(path_lf), read(path_por)
    ratios = sorted(lf[d] / por[d] for d in lf if d in por and por[d] > 0 and d.year < 1960)
    r = ratios[len(ratios) // 2]
    days = sorted(set(lf) | {d for d in por if d < min(lf)})
    return {d: lf.get(d, por.get(d, 0.0) * r) for d in days}, r


def fit_recession(flows):
    """[approx] Daily recession constant: median ratio of consecutive falling low flows in June-October."""
    ds = sorted(flows); ratios = []
    # baseflow recession: consecutive falling days at drought-level flows, after at least five falling days
    run = 0
    for a, b in zip(ds, ds[1:]):
        run = run + 1 if flows[b] < flows[a] else 0
        if a.month in (6, 7, 8, 9, 10) and run >= 5 and 0 < flows[b] < flows[a] < 1500:
            ratios.append(flows[b] / flows[a])
    ratios.sort()
    return ratios[len(ratios) // 2]


@dataclass
class Scenario:
    year: int
    annual_demand: float          # MGD, WMA total [study] Tables A.4
    pax_max: float = None
    def __post_init__(self):
        if self.pax_max is None:
            self.pax_max = 110.0 if self.year >= 2040 else 72.0      # [study] Table 5-5


def simulate(flows, sc: Scenario, k, start=dt.date(1929, 10, 1), end=dt.date(2009, 12, 31), occ_boost=40.0, pax_boost=30.0, extra_dc=0.0):
    caps = CAPS(sc.year)
    S = {n: caps[n] for n in caps}                 # start full
    combined_cap = caps['JR'] + caps['LS']
    days = [d for d in sorted(flows) if start <= d <= end]
    jr_pipeline = {}                               # arrival day -> JR release (MGD)
    rec = []
    for i, d in enumerate(days):
        m = d.month - 1
        q = flows[d]
        cu = CU_2018[m] + CU_GROWTH[m] * (sc.year - 2018) + DC_CU[sc.year] * DC_MONTH[m]
        avail = q - cu + RETURNS[sc.year]                                   # flow reaching Little Falls before releases
        # restrictions [study] Table 5-4
        frac = (S['JR'] + S['LS']) / combined_cap
        summer = d.month in (6, 7, 8, 9)
        cut = (0.15 if summer else 0.05) if frac < 0.05 else ((0.05 if summer else 0.03) if frac < 0.60 else 0.0)
        demand = sc.annual_demand * DEMAND_MONTH[m] * (1 - cut) + extra_dc * DC_MONTH[m]   # extra data-center use beyond the forecast
        stress = avail - FLOWBY < demand * 1.0                               # Potomac alone could not carry all demand
        # off-Potomac production [approx]: baseline shares, raised under stress within plant and storage limits
        occ_prod = min(120.0, max(45.0, 0.40 * 0.36 * demand + (occ_boost if stress else 0.0))) if S['OCC'] > 0.1 * caps['OCC'] else 45.0
        pax_prod = (min(sc.pax_max, 40.0 + (pax_boost if stress else 0.0)) if S['PAX'] > 1000.0 else 20.0)
        store_draw = 0.0
        if stress:
            for n, rate in (('MILESTONE', 20.0), ('VULCAN', 10.0)):        # [approx] Loudoun plant scale; Vulcan supplements Griffith
                take = min(rate, S[n]); S[n] -= take; store_draw += take
        potomac_w = max(0.0, demand - occ_prod - pax_prod - store_draw)
        # nine-day JR release decision for arrival at d+9 [study logic, approx forecast]
        if i + 9 < len(days):
            d9 = days[i + 9]; m9 = d9.month - 1
            f9 = q * k ** 9 - (CU_2018[m9] + CU_GROWTH[m9] * (sc.year - 2018) + DC_CU[sc.year] * DC_MONTH[m9]) + RETURNS[sc.year]
            need9 = potomac_w + FLOWBY - f9
            rel = min(max(0.0, need9), S['JR'])
            S['JR'] -= rel; jr_pipeline[d9] = rel
        jr_arr = jr_pipeline.pop(d, 0.0)
        # one-day Little Seneca release to cover the remaining gap
        gap = potomac_w + FLOWBY - (avail + jr_arr)
        ls_rel = min(max(0.0, gap), S['LS'])
        S['LS'] -= ls_rel
        deficit = max(0.0, gap - ls_rel)
        # reservoir refill [approx inflows by drainage-area ratio]
        inflow = {n: q * AREA[n] / LF_AREA for n in AREA}
        S['JR'] = min(caps['JR'], S['JR'] + max(0.0, inflow['JR'] - LUKE_TARGET))
        S['LS'] = min(caps['LS'], S['LS'] + max(0.0, inflow['LS'] - LS_FLOWBY))
        S['PAX'] = min(caps['PAX'], max(0.0, S['PAX'] + inflow['PAX'] - pax_prod - DUCKETT_FLOWBY))
        S['OCC'] = min(caps['OCC'], max(0.0, S['OCC'] + inflow['OCC'] + UOSA[sc.year] - occ_prod))
        if not stress:
            S['MILESTONE'] = min(caps['MILESTONE'], S['MILESTONE'] + 40.0)          # [study] 40 MGD refill pipe
            S['VULCAN'] = min(caps['VULCAN'], S['VULCAN'] + 0.05 * occ_prod)        # [study] refill from 5% of Griffith output
        rec.append((d, S['JR'] + S['LS'], deficit, cut > 0, cut >= 0.05 and frac < 0.05, avail, potomac_w, jr_arr, ls_rel, occ_prod, pax_prod))
    return rec


def metrics(rec, window=None):
    r = [x for x in rec if window is None or window[0] <= x[0] <= window[1]]
    years = sorted({x[0].year for x in r})
    def_years = {x[0].year for x in r if x[2] > 0.01}
    return dict(min_LS_JRws_bg=min(x[1] for x in r) / 1000.0, deficit_days=sum(1 for x in r if x[2] > 0.01),
                max_deficit_mgd=max(x[2] for x in r), pct_years_no_deficit=100.0 * (1 - len(def_years) / len(years)),
                pct_days_voluntary=100.0 * sum(1 for x in r if x[3]) / len(r))
