"""Version 9: the Energy Plan pathways run to 2050 (net-zero emission limit, RPS to 100% in 2045, storage petitions
to 2045, compounding demand at the plan's rates, falling technology costs).
Version 8: the 2026 Virginia Energy Plan scenarios (RGGI carbon price, distributed resources, non-combustion
generation, no-new-gas and limited-import variants) on the calibrated version-7 model.
Version 7 notes: calibrated baseline and statutes.

Changes from version 6: an existing fleet calibrated so the 2025 electricity balance matches observed generation
(gas, nuclear, coal including Mt Storm, solar, biomass, hydro, imports); imports split into hourly-priced energy
and separately purchased capacity; storage in three statutory duration classes (under 10 hours, 10-24 hours, over
24 hours); the solar provision as a solar-or-onshore-wind requirement; both statutes expressed as petition
schedules with installation lags, and the long-duration targets treated as contingent.
Version 6 notes:

Data-center load is split by workload: conventional cloud (flat, inflexible, prefers the Northern Virginia hub),
interactive inference (follows users through the day, inflexible, prefers the hub), batch inference (shiftable
within the day; pricing can enlarge it) and training (pausable or movable within a budget at the cost of idle
chips; sites anywhere in the zone). Shares follow McKinsey's 2025-2030 projection, extended to 2035.
Earlier versions treated data-center load as one block:

Data-center demands may curtail (including moving work out of the zone) within an annual budget, and shift
within the day. Whether adequacy and deliverability rules credit the flexible part is an institutional switch.

Scopes
  Physical system : the whole PJM Dominion (DOM) zone, all load-serving entities.
  Institutions    : Virginia RPS, storage and solar mandates apply to Dominion Energy Virginia only
                    (owner 'dominion_va'); PJM adequacy and Northern Virginia deliverability apply to all load.
  Bills           : Dominion Energy Virginia residential customers.
Demands carry an owner and a segment (techgraph.demands.Demand). Costs are attributed to owners by rule:
Dominion-only costs (existing Dominion fleet, mandated resources, compliance payments) go to Dominion;
shared costs (new gas, market capacity, corridor, energy) are split by coincident-peak or energy share.
"""
import os, sys, math, json
from dataclasses import dataclass, replace

os.environ.setdefault('TECHGRAPH_BACKEND', 'scipy')
sys.path.insert(0, os.environ.get('TECHGRAPH_PATH', os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..'))))
from techgraph.catalog import Design, Scenario                                         # noqa: E402
from techgraph.dynamic import Trajectory, Params, Vintage, solve_window                 # noqa: E402
from techgraph.model import solve                                                       # noqa: E402
from techgraph.institutions import EnergyShare, CapacityQuantity, AccreditedCapacity, EmissionCap    # noqa: E402
from techgraph.demands import Demand, shares                                            # noqa: E402

_P = json.load(open(os.path.join(os.path.dirname(os.path.abspath(__file__)), 'va_days2.json')))
BLOCKS = tuple(tuple(b) for b in _P['blocks'])
SHAPE, SOLAR, WIND_OFF, W = _P['load'], _P['solar'], _P['wind'], _P['period_weights']
NT = len(SHAPE)
EPOCH_YEARS = list(range(2025, 2050, 2))          # 2025 ... 2049 (2049 stands for 2050)
GAS = 3.5
RPS_SHARE = [0.26, 0.32, 0.38, 0.45, 0.52, 0.59]
AVAIL = 0.88                                # equivalent availability of existing thermal plants (calibrated)
# accreditation; existing thermal capacity is entered net of availability, so its rating is scaled by 1/AVAIL
ELCC = {'NUCLEAR': .95 / .93, 'GAS_CC_EXIST': .79 / AVAIL, 'GAS_CT_EXIST': .62 / AVAIL, 'COAL': .83 / AVAIL,
        'BIOMASS': .80, 'HYDRO': .30, 'NEW_CC': .79, 'NEW_CT': .62, 'SMR': .95,
        'SOLAR': .08, 'ONSHORE_WIND': .30, 'OSW': .55,
        'BATT4': .50 / 4, 'LDES12': .75 / 12, 'LDES100': .85 / 100, 'BATH_E': .70 / 11,
        'PJM_CAPACITY': 1.0, 'ROOF_NOVA': .0, 'ROOF_VA': .0, 'FC_NOVA': .90, 'FC_VA': .90, 'DER_SOLAR': .08, 'VPP': .50 / 4}
MANDATED = ('SOLAR', 'ONSHORE_WIND', 'OSW', 'BATT4', 'LDES12', 'LDES100')


def rps_share(y):
    pts = [(2025, .26), (2030, .41), (2035, .59), (2040, .79), (2045, 1.0)]
    if y >= 2045: return 1.0
    for (y0, a), (y1, b) in zip(pts, pts[1:]):
        if y0 <= y <= y1: return a + (b - a) * (y - y0) / (y1 - y0)
    return pts[0][1]


def petition_paths(c, y):
    """Installed-capacity requirements implied by the statutes' petition schedules (MW), with an installation lag.

    Solar or onshore wind (Code 56-585.5 D 2): petitions for 16,100 MW by end-2035, at least 3,000 MW by 2024;
    linear in between. Installed = petitioned (y - lag), plus the zone's non-Dominion utility solar (about 1.25 GW).
    Short-duration storage (2026 law): petitions for 16,000 MW by 2045; assumed linear from 2025.
    Long-duration storage: 4,000 MW by 2045, half petitioned by 2035, split between 10-24 hours and over 24 hours
    (assumed to parallel the Appalachian Power provision), contingent on the Commission's viability finding due
    March 2031; 'central' assumes petitions start after that finding."""
    yp = y - c.petition_lag
    sol = 3_000 + (16_100 - 3_000) * min(1.0, max(0.0, (yp - 2024) / 11))
    solar_req = max(4_750, sol) + 1_250
    sds = 4_000 * min(1.0, max(0.0, (yp - 2025) / 5)) + 12_000 * min(1.0, max(0.0, (yp - 2030) / 15))   # 4 GW by 2030, 16 GW by 2045
    if c.ldes_mode == 'early':
        ldes = 2_000 * min(1.0, max(0.0, (yp - 2026) / 9))
    elif c.ldes_mode == 'central':
        ldes = 2_000 * min(1.0, max(0.0, (yp - 2031) / 4)) + 2_000 * min(1.0, max(0.0, (yp - 2035) / 10))   # 4 GW by 2045
    else:
        ldes = 0.0
    return solar_req, sds, ldes / 2, ldes / 2


# workload shares of data-center load (McKinsey global projection: 2025 47/25/28, 2030 29/43/28; 2035 extended)
# workload split scenarios: shares of data-center load (cloud, inference, training) at anchor years; linear in between
SPLITS = {
    'mckinsey': {2025: (.47, .25, .28), 2030: (.29, .43, .28), 2035: (.22, .50, .28), 2050: (.15, .57, .28)},
    'iea_inference': {2025: (.85, .10, .05), 2035: (.50, .40, .10), 2050: (.40, .50, .10)},
    'lbnl_half': {2025: (.60, .20, .20), 2035: (.35, .32, .33), 2050: (.30, .35, .35)},
    'training_heavy': {2025: (.50, .20, .30), 2035: (.30, .25, .45), 2050: (.30, .25, .45)},
}


def split_shares(name, y):
    pts = sorted(SPLITS[name].items())
    if y <= pts[0][0]: v = pts[0][1]
    elif y >= pts[-1][0]: v = pts[-1][1]
    else:
        for (y0, a), (y1, b) in zip(pts, pts[1:]):
            if y0 <= y <= y1:
                f = (y - y0) / (y1 - y0); v = tuple(x + (z - x) * f for x, z in zip(a, b)); break
    return {'cloud': v[0], 'inference': v[1], 'training': v[2]}


def workload_shares(y, train_2035=0.28, split=None):
    if split:
        return split_shares(split, y)
    def lerp(a, b, f): return a + (b - a) * f
    if y <= 2030:
        f = (y - 2025) / 5; cloud, inf, train = lerp(.47, .29, f), lerp(.25, .43, f), .28
    else:
        f = (y - 2030) / 5; cloud, train = lerp(.29, .22, f), lerp(.28, train_2035, f); inf = 1 - cloud - train
    return {'cloud': cloud, 'inference': inf, 'training': train}
_TRAFFIC = [0.86, 0.84, 0.83, 0.83, 0.85, 0.89, 0.95, 1.01, 1.06, 1.09, 1.11, 1.12, 1.12, 1.12, 1.11, 1.10, 1.08, 1.06, 1.04, 1.02, 0.99, 0.95, 0.91, 0.88]
INFER = [x / (sum(_TRAFFIC) / 24) for x in _TRAFFIC]   # interactive inference power, mean 1 (assumption: follows US daytime use)          # Dominion-owned resources procured under state mandates


@dataclass
class Case:
    # 2025 load at the zone winter peak (GW), by owner; zone total 25.4 GW (EIA, 2025-26 winter)
    dva_nova: float = 4.6            # Dominion Virginia, non-data-center, Northern Virginia
    dva_rest: float = 11.7           # Dominion Virginia, non-data-center, rest of zone
    dva_res_share: float = 0.45      # residential share of Dominion Virginia non-data-center peak
    dnc: float = 0.9                 # Dominion North Carolina
    novec: float = 1.0               # NOVEC non-data-center (Northern Virginia)
    coops: float = 2.0               # other cooperatives and municipalities (rest of zone)
    dc_dom_2035: float = 17.0        # Dominion data-center peak in 2035 (4.0 GW in 2025)
    dc_novec_2025: float = 1.2       # NOVEC data-center peak (about 900 MW reported; 1,449 MW 2025 forecast)
    dc_novec_2035: float = 4.0
    nondc_growth: float = 0.005
    allocation: str = 'socialized'
    export_rule: str = 'net_metering'
    institutions_on: bool = True
    rps_dc_in_base: bool = True
    corridor_rate: float = 1_500
    gas_rate_cc: float = 1_000
    gas_rate_ct: float = 800
    solar_rate: float = 2_500
    osw_rate: float = 1_500
    osw_cost: float = 500_000
    nova_air_permits: bool = True
    dc_siting: bool = True
    rps_acp: float = 50.0
    rec_import_price: float = 30.0
    adequacy_margin: float = 0.05
    deliverability_margin: float = 0.05
    homes: float = 2.4e6
    kwh_home: float = 12_000
    nova_home_share: float = 0.35
    adopters0: float = 55_000
    eligible: float = 0.40
    kw_sys: float = 7.0
    cost_w: float = 3.0
    yield_kwh: float = 1_500
    self_use: float = 0.5
    uptake0: float = 0.0090
    payback_ref: float = 10.8
    beta: float = 0.06
    other_fixed: float = 2.4e9       # Dominion Virginia residential distribution and customer costs (calibration)
    embedded_dom: float = 2.4e9      # $/yr embedded cost of Dominion's 2025 fleet (assumption)
    trans_cost: float = 40_000
    pjm_cap: float = 325 * 365
    pjm_energy: float = 40.0
    tie_mw: float = 8_500
    corridor_mw: float = 12_000      # existing import capability into Northern Virginia (assumption)
    assigned_baseline: tuple = ()
    # data-center flexibility (all zero = inflexible)
    dc_curtail_frac: float = 0.0      # share of data-center load that can be curtailed in a given hour
    dc_curtail_budget: float = 0.0    # annual curtailed energy as a share of data-center energy
    dc_curtail_cost: float = 500.0    # $/MWh opportunity cost of curtailed computing (assumption)
    dc_shift_frac: float = 0.0        # share of data-center load that can be shifted within the day
    dc_shift_cost: float = 5.0        # $/MWh shifted (assumption)
    gas_price: float = 4.5            # $/MMBtu delivered (calibrated to the 2025 balance)
    coal_cost: float = 40.0           # $/MWh (calibrated)
    import_avg: float = 40.0          # $/MWh average PJM energy price (calibrated); shape follows zone load
    import_alpha: float = 2.5         # steepness of the import price shape (calibrated)
    import_growth: float = 0.0        # real annual growth of the import price level (sensitivity)
    petition_lag: int = 3             # years from petition to service
    mandates: str = 'petition'        # 'petition' (schedules with lags), 'none', or 'hard' (installed floors as in v6)
    ldes_mode: str = 'central'        # 'central', 'early', or 'none'
    onshore_rate: float = 200.0       # MW per two years (limited ridgetop sites)
    storage_elcc_scale: float = 1.0   # sensitivity on storage accreditation
    ldes12_rate: float = 500.0        # MW per two years, 10-24 hour storage (pumped hydro, flow batteries)
    ldes100_rate: float = 500.0       # MW per two years, over-24-hour storage
    ldes100_from: int = 2033          # first year over-24-hour storage can enter service (after the 2031 viability order)
    carbon_price: float = 0.0         # $/short ton CO2 (RGGI) on in-state fossil units; imports and Mt Storm uncovered
    der_solar_2035: float = 0.0       # MW of added distributed and community solar by 2035 (programs, beyond rooftop adoption)
    vpp_2035: float = 0.0             # MW of aggregated home and business batteries (4-hour) by 2035
    der_cost: float = 150_000.0       # $/MW-yr for program distributed solar
    vpp_cost: float = 110_000.0       # $/MW-yr for virtual-power-plant batteries
    fuel_cells: bool = False          # non-combustion generators (fuel cells, linear generators) allowed, incl. in NOVA
    fc_cost: float = 250_000.0        # $/MW-yr (~$2,500/kW, assumption)
    fc_rate: float = 1_000.0          # MW per two years
    no_new_gas: bool = False          # no new combustion gas plants
    smr_cost: float = 850_000.0
    smr_from: int = 2033
    nondc_growth_override: float = -1 # if >= 0, replaces nondc_growth (electrification)
    load_growth: float = 0.0          # if > 0: total zone load compounds at this rate; data centers fill the remainder
    net_zero: bool = False            # in-zone power emissions capped from 2035, falling to zero by 2049 (~2050)
    cap_2035_mst: float = 28.0        # cap in 2035, million short tons
    import_cap_mw: float = 0.0        # if > 0: imports limited to this many MW from import_cap_from
    import_cap_from: int = 2029
    import_emis: float = 0.45         # short tons CO2 per MWh of imports (assumption, between PJM average and marginal)
    carbon_on_imports: bool = False   # RGGI-like price applied to imports at import_emis (border adjustment)
    cap_counts_imports: bool = False  # the net-zero cap counts imported emissions (consumption-based)
    cap_floor_mst: float = 0.0        # residual emissions allowed in 2049 ("net" zero with offsets)
    split: str = ''                   # workload split scenario name (see SPLITS); '' = legacy McKinsey path
    train_shift_frac: float = 0.0     # share of training load that can be rescheduled within the day (off-peak training)
    train_shift_cost: float = 20.0    # $/MWh shifted (scheduling and checkpoint overhead, assumption)
    flex_credit_share: float = 1.0    # share of flexible data-center load credited for adequacy
    train_daily_hours: float = 0.0    # if > 0: training can be paused at most this many hours per day
    cost_decline: bool = True         # real cost declines: solar 2%/yr, storage 3%/yr, offshore wind 1.5%/yr, SMR 2%/yr after 2030
    credit_flex: bool = False         # PJM adequacy credits the flexible part of data-center load
    workloads: bool = True            # split data-center load by workload (False = one inflexible block)
    train_curtail_frac: float = 0.8   # share of a training load that can pause or move in a given hour
    train_budget: float = 0.01        # annual paused or moved energy, share of training energy
    train_cost: float = 2000.0        # $/MWh: idle-chip opportunity cost (GPU rental ~ $2/h per ~1 kW)
    batch_share: float = 0.15         # share of inference that is batch (shiftable within the day)
    price_shift: float = 0.0          # extra share of inference moved within the day by peak pricing
    train_share_2035: float = 0.28    # training share of data-center load in 2035 (McKinsey 2030: 28%)
    credit_flex_deliv: bool = False   # NOVA deliverability also credits it (valid only if the constraint binds rarely)


CO2_ST_PER_MMBTU = 0.0585   # short tons CO2 per MMBtu of natural gas


def designs(c):
    cp = c.carbon_price
    hr = lambda h: c.gas_price * h + cp * CO2_ST_PER_MMBTU * h
    D = Design
    d = [D('NUCLEAR', 'convert', annual_cost=0, var_cost=10.0, form_in='fuel', form_out='elec', loc='VA', max_cap=1e7),
         D('GAS_CC_EXIST', 'convert', annual_cost=0, var_cost=3.0 + hr(6.9), emis=6.9 * CO2_ST_PER_MMBTU, form_in='fuel', form_out='elec', loc='VA', max_cap=1e7),
         D('GAS_CT_EXIST', 'convert', annual_cost=0, var_cost=4.0 + hr(10.5), emis=10.5 * CO2_ST_PER_MMBTU, form_in='fuel', form_out='elec', loc='VA', max_cap=1e7),
         D('COAL', 'convert', annual_cost=0, var_cost=c.coal_cost + 0.4 * cp * 1.1, emis=1.1, form_in='fuel', form_out='elec', loc='VA', max_cap=1e7),
         D('BIOMASS', 'renewable', annual_cost=0, var_cost=5.0, loc='VA', profile='flat65', max_cap=1e7),
         D('HYDRO', 'renewable', annual_cost=0, loc='VA', profile='flat40', max_cap=1e7),
         D('BATH_E', 'store', annual_cost=0, form='elec', loc='VA', duration_h=11.0, eta_c=.89, eta_d=.89, max_cap=1e7),
         D('SOLAR', 'renewable', annual_cost=128_000, loc='VA', profile='solar', max_cap=1e7),
         D('ONSHORE_WIND', 'renewable', annual_cost=180_000, loc='VA', profile='wind_on', max_cap=1e7),
         D('OSW', 'renewable', annual_cost=c.osw_cost, loc='VA', profile='wind_off', max_cap=1e7),
         D('SMR', 'convert', annual_cost=c.smr_cost, var_cost=12.0, form_in='fuel', form_out='elec', loc='VA', max_cap=1e7),
         D('NEW_CC', 'convert', annual_cost=195_000, var_cost=3.55 + hr(6.6), emis=6.6 * CO2_ST_PER_MMBTU, form_in='fuel', form_out='elec', loc='VA', max_cap=1e7),
         D('NEW_CT', 'convert', annual_cost=134_000, var_cost=4.0 + hr(10.5), emis=10.5 * CO2_ST_PER_MMBTU, form_in='fuel', form_out='elec', loc='VA', max_cap=1e7),
         D('NEW_CT_NOVA', 'convert', annual_cost=134_000 * 1.25, var_cost=4.0 + hr(10.5), emis=10.5 * CO2_ST_PER_MMBTU, form_in='fuel', form_out='elec', loc='NOVA', max_cap=1e7),
         D('BATT4', 'store', annual_cost=22_494 + 5_622 + (19_584 + 4_895) / 4, form='elec', loc='VA', duration_h=4.0, eta_c=.92, eta_d=.92, max_cap=1e7),
         D('LDES12', 'store', annual_cost=260_000 / 12, form='elec', loc='VA', duration_h=12.0, eta_c=.87, eta_d=.87, max_cap=1e7),
         D('LDES100', 'store', annual_cost=200_000 / 100, form='elec', loc='VA', duration_h=100.0, eta_c=.65, eta_d=.65, max_cap=1e7),
         D('PJM_ENERGY', 'convert', annual_cost=0.0, var_cost=1.0, var_cost_profile='pjm_price', form_in='fuel', form_out='elec', loc='PJM', max_cap=1e9,
           emis=(c.import_emis if c.cap_counts_imports else 0.0)),
         D('PJM_CAPACITY', 'convert', annual_cost=c.pjm_cap, var_cost=1e5, form_in='fuel', form_out='elec', loc='PJM', max_cap=1e7),
         D('TIE_PJM_VA', 'transport', annual_cost=0.0, form='elec', loc_from='PJM', loc_to='VA', loss=0.01, max_cap=1e7),
         D('CORRIDOR', 'transport', annual_cost=c.trans_cost, form='elec', loc_from='VA', loc_to='NOVA', loss=0.02, bidirectional=True, max_cap=1e7),
         D('FC_NOVA', 'convert', annual_cost=c.fc_cost, var_cost=5.0 + hr(7.5), emis=7.5 * CO2_ST_PER_MMBTU, form_in='fuel', form_out='elec', loc='NOVA', max_cap=1e7),
         D('FC_VA', 'convert', annual_cost=c.fc_cost, var_cost=5.0 + hr(7.5), emis=7.5 * CO2_ST_PER_MMBTU, form_in='fuel', form_out='elec', loc='VA', max_cap=1e7),
         D('DER_SOLAR', 'renewable', annual_cost=0.0, loc='NOVA', profile='solar', max_cap=1e7),
         D('VPP', 'store', annual_cost=0.0, form='elec', loc='NOVA', duration_h=4.0, eta_c=.92, eta_d=.92, max_cap=1e7),
         D('ROOF_NOVA', 'renewable', annual_cost=0.0, loc='NOVA', profile='solar', max_cap=1e7),
         D('ROOF_VA', 'renewable', annual_cost=0.0, loc='VA', profile='solar', max_cap=1e7)]
    return {x.name: x for x in d}


def demand_set(c, y, dc_dom_nova, dc_dom_va, dc_novec):
    g = (1 + c.nondc_growth) ** (y - 2025)
    prof = lambda gw: tuple(1000 * gw * g * x for x in SHAPE)
    flat = lambda gw: tuple([1000 * gw] * NT)
    infer = lambda gw: tuple(1000 * gw * INFER[t % 24] for t in range(NT))
    r = c.dva_res_share
    out = [Demand('dva_res_nova', 'NOVA', prof(c.dva_nova * r), 'dominion_va', 'residential'),
           Demand('dva_ci_nova', 'NOVA', prof(c.dva_nova * (1 - r)), 'dominion_va', 'commercial_industrial'),
           Demand('dva_res_rest', 'VA', prof(c.dva_rest * r), 'dominion_va', 'residential'),
           Demand('dva_ci_rest', 'VA', prof(c.dva_rest * (1 - r)), 'dominion_va', 'commercial_industrial'),
           Demand('dnc', 'VA', prof(c.dnc), 'dominion_nc', 'all'),
           Demand('novec', 'NOVA', prof(c.novec), 'novec', 'all'),
           Demand('coops', 'VA', prof(c.coops), 'other_coops', 'all')]
    blocks = [('dva', 'NOVA', dc_dom_nova, 'dominion_va'), ('dva_rest', 'VA', dc_dom_va, 'dominion_va'), ('novec', 'NOVA', dc_novec, 'novec')]
    if not c.workloads:
        fx = dict(curtail_max_frac=c.dc_curtail_frac, curtail_budget=c.dc_curtail_budget, curtail_cost=c.dc_curtail_cost,
                  shift_frac=c.dc_shift_frac, shift_cost=c.dc_shift_cost)
        for tag, loc, gw, own in blocks:
            out.append(Demand(f'{tag}_dc', loc, flat(sum(gw.values()) if isinstance(gw, dict) else gw), own, 'data_center', **fx))
        return tuple(out)
    for tag, loc, mix, own in blocks:            # mix: {'cloud': GW, 'inference': GW, 'training': GW}
        out.append(Demand(f'{tag}_cloud', loc, flat(mix['cloud']), own, 'data_center'))
        out.append(Demand(f'{tag}_inference', loc, infer(mix['inference']), own, 'data_center',
                          shift_frac=min(0.9, c.batch_share + c.price_shift), shift_cost=c.dc_shift_cost))
        out.append(Demand(f'{tag}_training', loc, flat(mix['training']), own, 'data_center',
                          curtail_max_frac=c.train_curtail_frac, curtail_budget=c.train_budget, curtail_cost=c.train_cost,
                          shift_frac=c.train_shift_frac, shift_cost=c.train_shift_cost, curtail_daily_hours=c.train_daily_hours))
    return tuple(out)


def mixes(c, y, dc_nova, dc_va, dc_nv):
    """Split data-center GW by workload. Training sits outside the hub first; cloud and inference fill the rest."""
    sh = workload_shares(y, c.train_share_2035, c.split)
    def split(total, train):
        rest = max(0.0, total - train); ci = sh['cloud'] + sh['inference']
        return {'cloud': rest * sh['cloud'] / ci, 'inference': rest * sh['inference'] / ci, 'training': train}
    train_dom = sh['training'] * (dc_nova + dc_va)
    t_va = min(dc_va, train_dom); t_nova = train_dom - t_va
    return split(dc_nova, t_nova), split(dc_va, t_va), split(dc_nv, sh['training'] * dc_nv)


def scenario(c, y, dc_dom_nova, dc_dom_va, dc_novec):
    if c.workloads:
        dc_dom_nova, dc_dom_va, dc_novec = mixes(c, y, dc_dom_nova, dc_dom_va, dc_novec)
    dem = demand_set(c, y, dc_dom_nova, dc_dom_va, dc_novec)
    L = [sum(d.profile[t] for d in dem) for t in range(NT)]
    Lbar = sum(W[t] * L[t] for t in range(NT)) / sum(W)
    raw = [(l / Lbar) ** c.import_alpha for l in L]
    m = sum(W[t] * raw[t] for t in range(NT)) / sum(W)
    level = c.import_avg * (1 + c.import_growth) ** (y - 2025)
    price = [level * x / m + (c.carbon_price * c.import_emis if (c.carbon_on_imports and y >= 2027) else 0.0) for x in raw]
    wind_on = [min(1.0, 0.30 / 0.436 * x) for x in WIND_OFF]      # proxy shape, capacity factor ~0.30
    sc = Scenario(periods=NT, hours=1.0, demand_D=[0.0] * NT, hub_energy=0.0, hub_max_rate=0.0,
                  profiles={'solar': SOLAR, 'wind_off': WIND_OFF, 'wind_on': wind_on, 'flat65': [0.65] * NT,
                            'flat40': [0.40] * NT, 'pjm_price': price}, fuel_price_R=0.0, voll=10_000.0,
                  designs=designs(c if y >= 2027 else replace(c, carbon_price=0.0)), days=365.0, period_weights=tuple(W), cycle_blocks=BLOCKS,   # RGGI from mid-2026
                  demands=dem,
                  locations=('NOVA', 'VA', 'PJM', 'D'), fuel_sites=('VA', 'PJM', 'NOVA'))
    return sc


def institutions(c, k):
    el = {n: (v * c.storage_elcc_scale if n in ('BATT4', 'LDES12', 'LDES100', 'BATH_E') else v) for n, v in ELCC.items()}
    inst = [AccreditedCapacity('adequacy', accreditation=el, margin=c.adequacy_margin, escape_price=1e6,
                               credit_flexibility=c.credit_flex, flexibility_credit=c.flex_credit_share),
            AccreditedCapacity('nova_deliverability', accreditation={'CORRIDOR': 0.98, 'NEW_CT_NOVA': 0.62, 'FC_NOVA': 0.90, 'VPP': 0.50 / 4},
                               margin=c.deliverability_margin, escape_price=1e6, locations=('NOVA',),
                               credit_flexibility=c.credit_flex_deliv)]
    if c.net_zero and EPOCH_YEARS[k] >= 2035:
        f = max(0.0, (2049 - EPOCH_YEARS[k]) / 14)
        cap = 1e6 * (c.cap_floor_mst + (c.cap_2035_mst - c.cap_floor_mst) * f)
        inst.append(EmissionCap('net_zero', cap=cap, escape_price=1_000.0))      # $/short ton above the cap (reported)
    if c.institutions_on and k > 0:
        y = EPOCH_YEARS[k]
        segs = None if c.rps_dc_in_base else ('residential', 'commercial_industrial')
        inst.append(EnergyShare('rps', members=('SOLAR', 'ONSHORE_WIND', 'OSW'), share=rps_share(EPOCH_YEARS[k]), excluded=('NUCLEAR', 'SMR'),   # the base is non-nuclear sales, existing or new
                                escape_price=c.rps_acp, escape_tiers=((c.rec_import_price, 0.25),),
                                base_owners=('dominion_va',), base_segments=segs))
        if c.mandates != 'none':
            solar_req, sds, l12, l100 = petition_paths(c, y)
            if c.mandates == 'hard':                     # version 6 representation, for comparison
                solar_req, sds = [4_750, 7_000, 9_300, 11_500, 13_800, 16_100][k], [0, 1_500, 3_000, 4_500, 7_000, 10_000][k]
            inst += [CapacityQuantity('solar_or_onshore_wind', members=('SOLAR', 'ONSHORE_WIND', 'DER_SOLAR'), minimum=solar_req, escape_price=1e6),
                     CapacityQuantity('short_duration_storage', members=('BATT4',), minimum=4 * sds, escape_price=1e6)]
            if l12 > 0:
                inst.append(CapacityQuantity('ldes_10_24h', members=('LDES12',), minimum=12 * l12, escape_price=1e6))
            if l100 > 0:
                inst.append(CapacityQuantity('ldes_over_24h', members=('LDES100',), minimum=100 * l100, escape_price=1e6))
    return inst


def window(c, k, y, sc, hist, forbid):
    n = y - 2025
    dec = (lambda r: (1 - r) ** n) if c.cost_decline else (lambda r: 1.0)
    smr = (1 - 0.02) ** max(0, y - 2030) if c.cost_decline else 1.0
    cm = {'SOLAR': [(0.75 if y <= 2027 else 1.0) * dec(0.02)], 'ONSHORE_WIND': [dec(0.01)], 'OSW': [dec(0.015)],
          'BATT4': [dec(0.03)], 'LDES12': [dec(0.02)], 'LDES100': [dec(0.03)], 'SMR': [smr], 'FC_NOVA': [dec(0.02)], 'FC_VA': [dec(0.02)]}
    traj = Trajectory(K=1, fuel_price=[0.0], demand_mult=[1.0], cost_mult=cm,
                      build_rate={'CORRIDOR': [c.corridor_rate], 'NEW_CC': [c.gas_rate_cc], 'NEW_CT': [c.gas_rate_ct],
                                  'PJM_CAPACITY': [c.tie_mw], 'SOLAR': [c.solar_rate], 'OSW': [c.osw_rate],
                                  'ONSHORE_WIND': [c.onshore_rate],
                                  'LDES12': [12 * c.ldes12_rate], 'LDES100': [100 * c.ldes100_rate],
                                  'FC_NOVA': [c.fc_rate], 'FC_VA': [c.fc_rate]},
                      avail_from={'OSW': 0 if y >= 2031 else 9, 'SMR': 0 if y >= c.smr_from else 9,
                                  'LDES100': 0 if y >= c.ldes100_from else 9})
    prm = Params(life={n: 100 for n in sc.designs}, fom_share=0.0, aging=0.0)
    return traj, solve_window(sc, traj, prm, 0, 0, hist, forbid=tuple(forbid), institutions=institutions(c, k))


def run(c: Case):
    E = lambda n, mw: Vintage(n, -1, mw, mw, 0, 0, 100)
    history = [E('NUCLEAR', 3_350), E('GAS_CC_EXIST', 10_000 * AVAIL), E('GAS_CT_EXIST', 5_000 * AVAIL), E('COAL', 2_500 * AVAIL),
               E('BIOMASS', 600), E('HYDRO', 300), E('SOLAR', 6_000), E('BATH_E', 19_800),
               E('PJM_ENERGY', 1e6), E('TIE_PJM_VA', c.tie_mw), E('CORRIDOR', c.corridor_mw)]
    forbid = ['NUCLEAR', 'GAS_CC_EXIST', 'GAS_CT_EXIST', 'COAL', 'BIOMASS', 'HYDRO', 'BATH_E', 'PJM_ENERGY', 'TIE_PJM_VA', 'ROOF_NOVA', 'ROOF_VA']
    forbid += ['DER_SOLAR', 'VPP']
    if c.nova_air_permits:
        forbid.append('NEW_CT_NOVA')
    if not c.fuel_cells:
        forbid += ['FC_NOVA', 'FC_VA']
    if c.no_new_gas:
        forbid += ['NEW_CC', 'NEW_CT', 'NEW_CT_NOVA']
    if c.nondc_growth_override >= 0:
        c = replace(c, nondc_growth=c.nondc_growth_override)
    der_cost_yr = 0.0
    cap_by_design = {}
    adopters, rate_prev = c.adopters0, 15.0
    cap_pooled, cap_mandated = 0.0, 0.0          # $/yr of new vintages: shared versus Dominion-mandated
    dc_nova, dc_va, dc_nv = 4.0, 0.0, c.dc_novec_2025
    out = []
    for k, y in enumerate(EPOCH_YEARS):
        if c.import_cap_mw > 0 and y >= c.import_cap_from:
            history = [v if v.design != 'PJM_ENERGY' else Vintage('PJM_ENERGY', -1, c.import_cap_mw, c.import_cap_mw, 0, 0, 100) for v in history]
        if y == 2027:
            history.append(Vintage('OSW', -1, 2_600, 2_600, 0, 0, 100))
        # ---- society layer: developers site and the grid admits new load
        f = (y - 2025) / 10
        if c.load_growth > 0:          # total load compounds; non-data-center load grows at nondc_growth
            dc_total = max(5.2, (144.6 * (1 + c.load_growth) ** (y - 2025) - 99.05 * (1 + c.nondc_growth) ** (y - 2025)) / 8.76)
            want_dom, want_nv = dc_total * 4.0 / 5.2, dc_total * 1.2 / 5.2
        else:
            want_dom = 4.0 + (c.dc_dom_2035 - 4.0) * f
            want_nv = c.dc_novec_2025 + (c.dc_novec_2035 - c.dc_novec_2025) * f
        new_dom, new_nv = want_dom - dc_nova - dc_va, max(0.0, want_nv - dc_nv)
        g = (1 + c.nondc_growth) ** (y - 2025)
        corridor = sum(v.alive for v in history if v.design == 'CORRIDOR')
        firm = (1 - min(1.0, c.dc_curtail_frac * (c.dc_curtail_budget > 0) + c.dc_shift_frac)) if c.credit_flex_deliv else 1.0
        nova_other = (c.dva_nova + c.novec) * g + firm * (dc_nova + dc_nv + new_nv)
        headroom = max(0.0, (corridor + c.corridor_rate) * 0.98 / 1000 / (1 + c.deliverability_margin) - nova_other) / firm
        if c.workloads and c.dc_siting:      # training sites outside the hub; cloud and inference want the hub
            sh = workload_shares(y, c.train_share_2035, c.split)
            new_train = max(0.0, min(new_dom, sh['training'] * want_dom - min(dc_va, sh['training'] * (dc_nova + dc_va))))
            to_nova = min(new_dom - new_train, headroom)
        else:
            to_nova = min(new_dom, headroom) if c.dc_siting else new_dom
        a_nova, a_va, a_nv = to_nova, new_dom - to_nova, new_nv
        f_der = (y - 2025) / 10
        der_mw, vpp_mw = c.der_solar_2035 * f_der, c.vpp_2035 * f_der
        der_cost_yr = der_mw * c.der_cost + vpp_mw * c.vpp_cost
        roof_mw = adopters * c.kw_sys / 1000
        roof = [Vintage('ROOF_NOVA', -1, roof_mw * c.nova_home_share, roof_mw * c.nova_home_share, 0, 0, 100),
                Vintage('ROOF_VA', -1, roof_mw * (1 - c.nova_home_share), roof_mw * (1 - c.nova_home_share), 0, 0, 100)]
        if der_mw > 0:
            roof.append(Vintage('DER_SOLAR', -1, der_mw, der_mw, 0, 0, 100))
        if vpp_mw > 0:
            roof.append(Vintage('VPP', -1, 4 * vpp_mw, 4 * vpp_mw, 0, 0, 100))
        for _ in range(40):
            sc = scenario(c, y, dc_nova + a_nova, dc_va + a_va, dc_nv + a_nv)
            traj, sol = window(c, k, y, sc, history + roof, forbid)
            ir = {r['name']: r for r in sol['institutions']}
            s_all, s_nova = ir['adequacy']['shortfall'], ir['nova_deliverability']['shortfall']
            if (s_all < 1.0 and s_nova < 1.0) or a_nova + a_va + a_nv < 1e-3:
                break
            if s_nova >= 1.0:                   # queue NOVA requests, the cooperative's and Dominion's in proportion
                cut = s_nova / 1000 / (1 + c.deliverability_margin) + 0.01
                tot = a_nova + a_nv
                if tot > 0:
                    a_nova = max(0.0, a_nova - cut * a_nova / tot); a_nv = max(0.0, a_nv - cut * a_nv / tot)
            if s_all >= 1.0:
                cut = s_all / 1000 / (1 + c.adequacy_margin) + 0.01
                take = min(a_va, cut); a_va -= take; cut -= take
                tot = a_nova + a_nv
                if cut > 0 and tot > 0:
                    a_nova = max(0.0, a_nova - cut * a_nova / tot); a_nv = max(0.0, a_nv - cut * a_nv / tot)
        dc_nova += a_nova; dc_va += a_va; dc_nv += a_nv
        backlog_dom, backlog_nv = want_dom - dc_nova - dc_va, want_nv - dc_nv
        builds = {n: x for n, x in sol['epochs'][0]['builds'].items() if x > 1e-3}
        pjm_mw = builds.pop('PJM_CAPACITY', 0.0)
        for n, x in builds.items():
            ann = sc.designs[n].annual_cost * traj.mult(n, 0)
            cap_by_design[n] = cap_by_design.get(n, 0.0) + ann * x
            history.append(Vintage(n, -1, x, x, ann, 0, 100))
            if n in MANDATED:
                cap_mandated += ann * x
            elif n != 'CORRIDOR':
                cap_pooled += ann * x
        corridor_new = sum(v.capacity for v in history if v.design == 'CORRIDOR') - c.corridor_mw
        trans_new = corridor_new * c.trans_cost
        compliance = (ir['rps']['shortfall'] * c.rps_acp + sum(ir['rps']['tier_use']) * c.rec_import_price) if 'rps' in ir else 0.0
        # ---- operate the installed system
        caps = {}
        for v in history + roof:
            caps[v.design] = caps.get(v.design, 0.0) + v.alive
        if pjm_mw > 0: caps['PJM_CAPACITY'] = pjm_mw
        nz = ir.get('net_zero')
        shadow = (nz['implicit_price'] or 0.0) if nz else 0.0          # $/short ton: the cap's implicit carbon price
        sc_op = sc if shadow <= 0 else replace(sc, designs={n: (replace(d, var_cost=d.var_cost + d.emis * shadow) if d.emis > 0 else d)
                                                          for n, d in sc.designs.items()})
        op = solve(sc_op, [], existing=caps, fixed=True, existing_fom_share=0.0)
        p_va = [op.prices[('elec', 'VA', t)] for t in range(NT)]
        p_nova = [op.prices[('elec', 'NOVA', t)] for t in range(NT)]
        ops_year = op.costs['variable'] + op.costs.get('unmet', 0.0)
        # --- separate accounting items (all $/yr)
        annual = lambda n: sum(W[t] * x for t, x in enumerate(op.activity[n]['output'])) if n in op.activity and 'output' in op.activity[n] else 0.0
        shadow_cost = sum(sc_op.designs[n].emis * shadow * annual(n) for n in sc.designs if sc.designs[n].emis > 0) if shadow > 0 else 0.0
        ops_year -= shadow_cost              # the cap's implicit price is a dispatch signal, not a payment
        cp_y = c.carbon_price if y >= 2027 else 0.0
        gas_hr = {'GAS_CC_EXIST': 6.9, 'GAS_CT_EXIST': 10.5, 'NEW_CC': 6.6, 'NEW_CT': 10.5, 'NEW_CT_NOVA': 10.5, 'FC_NOVA': 7.5, 'FC_VA': 7.5}
        rggi_cost = cp_y * (sum(CO2_ST_PER_MMBTU * h * annual(n) for n, h in gas_hr.items()) + 0.4 * 1.1 * annual('COAL'))
        import_charge = (cp_y * c.import_emis * sum(W[t] * x for t, x in enumerate(op.activity['TIE_PJM_VA']['forward']))) if c.carbon_on_imports else 0.0
        gen = {n: sum(W[t] * x for t, x in enumerate(s['output'])) / 1e6 for n, s in op.activity.items() if 'output' in s}
        curt_twh = sum(sum(W[t] * x for t, x in enumerate(r.get('curtail', []))) for r in op.flexibility.values()) / 1e6
        # ---- electricity balance (annual TWh, capacity factors, peak-hour supply)
        def ann(xs): return sum(W[t] * x for t, x in enumerate(xs)) / 1e6
        bal = {'generation': {}, 'capacity_factor': {}, 'storage': {}, 'peak_hour': {}}
        tp = max(range(NT), key=lambda t: sum(d.profile[t] for d in sc.demands))
        for n, ser in op.activity.items():
            if 'output' in ser:
                bal['generation'][n] = ann(ser['output'])
                if caps.get(n, 0) > 0:
                    bal['capacity_factor'][n] = ann(ser['output']) * 1e6 / (caps[n] * 8760)
                bal['peak_hour'][n] = ser['output'][tp]
            if 'charge' in ser:
                ch, dis = ann(ser['charge']), ann(ser['discharge'])
                bal['storage'][n] = {'charge_twh': ch, 'discharge_twh': dis, 'loss_twh': ch - dis}
                bal['peak_hour'][n] = ser['discharge'][tp] - ser['charge'][tp]
        bal['generation'].pop('PJM_ENERGY', None); bal['generation'].pop('PJM_CAPACITY', None)
        bal['capacity_factor'].pop('PJM_ENERGY', None); bal['capacity_factor'].pop('PJM_CAPACITY', None)
        for n, f in (('GAS_CC_EXIST', AVAIL), ('GAS_CT_EXIST', AVAIL), ('COAL', AVAIL), ('NUCLEAR', 3_350 / 3_600)):
            if n in bal['capacity_factor']:
                bal['capacity_factor'][n] *= f                     # report on nameplate, not on available capacity
        bal['imports_twh'] = ann(op.activity['TIE_PJM_VA']['forward'])
        bal['peak_hour']['IMPORTS'] = op.activity['TIE_PJM_VA']['forward'][tp]
        bal['load_twh'] = ann([sum(d.profile[t] for d in sc.demands) for t in range(NT)])
        rate_st = {'GAS_CC_EXIST': 6.9 * CO2_ST_PER_MMBTU, 'GAS_CT_EXIST': 10.5 * CO2_ST_PER_MMBTU, 'NEW_CC': 6.6 * CO2_ST_PER_MMBTU,
                   'NEW_CT': 10.5 * CO2_ST_PER_MMBTU, 'NEW_CT_NOVA': 10.5 * CO2_ST_PER_MMBTU, 'FC_NOVA': 7.5 * CO2_ST_PER_MMBTU,
                   'FC_VA': 7.5 * CO2_ST_PER_MMBTU, 'COAL': 1.1}
        bal['co2_mst'] = sum(bal['generation'].get(n, 0) * r for n, r in rate_st.items())     # million short tons (TWh x st/MWh)
        bal['peak_load_mw'] = sum(d.profile[tp] for d in sc.demands)
        bal['peak_hour_index'] = tp
        bal['curtailed_load_twh'] = ann([sum(r.get('curtail', [0.0] * NT)[t] for r in op.flexibility.values()) for t in range(NT)])
        avail = {n: ann([sc.profiles[sc.designs[n].profile][t] * caps.get(n, 0.0) for t in range(NT)]) for n in ('SOLAR', 'ONSHORE_WIND', 'OSW', 'ROOF_NOVA', 'ROOF_VA') if n in caps}
        bal['renewable_spill_twh'] = {n: avail[n] - bal['generation'].get(n, 0.0) for n in avail}
        wl = {}
        for d in sc.demands:
            if d.segment == 'data_center':
                key = d.name.split('_')[-1]
                wl.setdefault(key, {})[d.location] = wl.get(key, {}).get(d.location, 0.0) + max(d.profile) / 1000
        shift_twh = sum(sum(W[t] * x for t, x in enumerate(r.get('shift_down', []))) for r in op.flexibility.values()) / 1e6
        curt_peak_mw = max((sum(r.get('curtail', [0.0] * NT)[t] for r in op.flexibility.values()) for t in range(NT)), default=0.0)
        flex_cost = op.costs.get('flexibility', 0.0)
        solar_value = sum(W[t] * SOLAR[t] * 0.5 * (p_va[t] + p_nova[t]) for t in range(NT)) / sum(W[t] * SOLAR[t] for t in range(NT))
        # ---- attribution of costs to owners
        pk, en = shares(sc, 'owner', 'peak'), shares(sc, 'owner', 'energy')
        pooled_cap = cap_pooled + pjm_mw * c.pjm_cap + trans_new
        dom_only = c.embedded_dom + cap_mandated + compliance + der_cost_yr
        dva_in_dom = pk['dominion_va'] / (pk['dominion_va'] + pk['dominion_nc'])
        dva_cap = pk['dominion_va'] * pooled_cap + dva_in_dom * dom_only          # capacity-related, $/yr
        owner_cost = {o: pk[o] * pooled_cap + en[o] * ops_year for o in pk}
        owner_cost['dominion_va'] += dva_in_dom * dom_only
        owner_cost['dominion_nc'] += (1 - dva_in_dom) * dom_only
        # residential share of Dominion Virginia's peak responsibility
        dva_parts = [d for d in sc.demands if d.owner == 'dominion_va']
        tp = max(range(NT), key=lambda t: sum(d.profile[t] for d in sc.demands))
        res_share = sum(d.profile[tp] for d in dva_parts if d.segment == 'residential') / sum(d.profile[tp] for d in dva_parts)
        cap_cost = res_share * dva_cap if c.allocation == 'socialized' else c.assigned_baseline[k]
        energy_year = sum(W[t] * sum(d.profile[t] for d in sc.demands) for t in range(NT))
        avg_energy_cost = ops_year / energy_year
        res_kwh = c.homes * c.kwh_home
        solar_kwh = adopters * c.kw_sys * c.yield_kwh
        if c.export_rule == 'net_metering':
            net_kwh, export_credit = res_kwh - solar_kwh, 0.0
        else:
            net_kwh = res_kwh - c.self_use * solar_kwh
            export_credit = (1 - c.self_use) * solar_kwh * solar_value / 1000
        rate = 100 * (cap_cost + c.other_fixed + avg_energy_cost / 1000 * net_kwh + export_credit) / net_kwh
        capex = c.kw_sys * 1000 * c.cost_w * (1 - (0.30 if y == 2025 else 0.0))
        prod = c.kw_sys * c.yield_kwh
        credit = rate_prev / 100 if c.export_rule == 'net_metering' else (c.self_use * rate_prev / 100 + (1 - c.self_use) * solar_value / 1000)
        payback = capex / (prod * credit)
        uptake = c.uptake0 * math.exp(-c.beta * (payback - c.payback_ref))
        zone_peak = max(sum(d.profile[t] for d in sc.demands) for t in range(NT)) / 1000
        out.append(dict(year=y, zone_peak_gw=zone_peak, dc_dom_nova=dc_nova, dc_dom_va=dc_va, dc_novec=dc_nv,
                        backlog_dom=backlog_dom, backlog_novec=backlog_nv, builds=builds, pjm_mw=pjm_mw, corridor_new_mw=corridor_new,
                        capacity=caps, gen_twh=gen, institutions=ir, compliance_musd=compliance / 1e6, peak_share=pk, energy_share=en,
                        owner_cost_musd={o: v / 1e6 for o, v in owner_cost.items()}, res_share=res_share,
                        rate_c=rate, bill=10 * rate, res_cap_cost=cap_cost, adopters=adopters, roof_mw=roof_mw,
                        solar_value=solar_value, p_va=p_va, system_cost_musd=(pooled_cap + dom_only + ops_year) / 1e6,
                        unmet=sum(sum(v) for v in op.unmet_extra.values()), carbon_shadow=shadow,
                        transfers_musd=dict(rggi=rggi_cost / 1e6, import_charge=import_charge / 1e6, compliance=compliance / 1e6, shadow_removed=shadow_cost / 1e6),
                        resource_cost_musd=(pooled_cap + dom_only + ops_year - rggi_cost - import_charge - compliance) / 1e6,
                        cost_parts=dict(capital_by_design={n: v / 1e6 for n, v in cap_by_design.items()}, pjm_capacity=pjm_mw * c.pjm_cap / 1e6,
                                        corridor=trans_new / 1e6, ops=ops_year / 1e6, compliance=compliance / 1e6, der=der_cost_yr / 1e6,
                                        embedded=c.embedded_dom / 1e6, res_cap=cap_cost / 1e6, other_fixed=c.other_fixed / 1e6,
                                        energy_res=avg_energy_cost / 1000 * net_kwh / 1e6, net_kwh=net_kwh, avg_energy_cost=avg_energy_cost),
                        curtail_series=[sum(r.get('curtail', [0.0] * NT)[t] for r in op.flexibility.values()) for t in range(NT)],
                        shift_series=[sum(r.get('shift_down', [0.0] * NT)[t] - r.get('shift_up', [0.0] * NT)[t] for r in op.flexibility.values()) for t in range(NT)],
                        load_series=[sum(d.profile[t] for d in sc.demands) for t in range(NT)],
                        workload_gw=wl, balance=bal, curtail_twh=curt_twh, shift_twh=shift_twh, curtail_peak_mw=curt_peak_mw, flex_cost_musd=flex_cost / 1e6,
                        dc_energy_twh=8.76 * (dc_nova + dc_va + dc_nv)))
        for _ in range(2):
            adopters += uptake * max(0.0, c.eligible * c.homes - adopters)
        rate_prev = rate
    return out


if __name__ == '__main__':
    for e in run(Case()):
        ir = {n: (round(v['implicit_price']) if v['implicit_price'] is not None else None, round(v['shortfall'])) for n, v in e['institutions'].items()}
        print(e['year'], f"zone peak {e['zone_peak_gw']:.1f} | DC dom NOVA {e['dc_dom_nova']:.1f} VA {e['dc_dom_va']:.1f} NOVEC {e['dc_novec']:.1f} "
              f"backlog {e['backlog_dom']:.1f}/{e['backlog_novec']:.1f} | builds { {n: round(x) for n, x in e['builds'].items()} } PJM {e['pjm_mw']:.0f}"
              f" | {ir} | peak share DVA {e['peak_share']['dominion_va']:.2f} | rate {e['rate_c']:.2f} | unmet {e['unmet']:.0f}")


def stress(c, e, load_up=0.10, import_share=0.70, snap=(96, 168)):
    """Operate the capacity built in epoch record e through a harsher cold snap.

    Non-data-center load in the cold-snap block is raised by load_up; the intertie is limited to import_share of its
    capacity (PJM-wide stress). Returns unserved energy (MWh) and the largest hourly shortfall (MW) in the snap."""
    if c.nondc_growth_override >= 0:
        c = replace(c, nondc_growth=c.nondc_growth_override)
    y = e['year']
    sc = scenario(c, y, e['dc_dom_nova'], e['dc_dom_va'], e['dc_novec'])
    dem = []
    for d in sc.demands:
        if d.segment != 'data_center':
            prof = tuple(q * (1 + load_up) if snap[0] <= t < snap[1] else q for t, q in enumerate(d.profile))
            d = replace(d, profile=prof)
        dem.append(d)
    sc = replace(sc, demands=tuple(dem))
    caps = dict(e['capacity'])
    caps['TIE_PJM_VA'] = caps.get('TIE_PJM_VA', c.tie_mw) * import_share
    op = solve(sc, [], existing=caps, fixed=True, existing_fom_share=0.0)
    un = [sum(v[t] for v in op.unmet_extra.values()) for t in range(snap[0], snap[1])]
    cur = sum(sum(r.get('curtail', [0.0] * NT)[snap[0]:snap[1]]) for r in op.flexibility.values())
    return dict(unserved_mwh=sum(un), max_short_mw=max(un), curtailed_mwh=cur)
