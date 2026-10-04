"""Scenario and technology catalog for the Stage 1 electricity-service world.

Units
-----
Energy: MWh (electric) or MWh_th (fuel). Power / capacity: MW, or MWh for storage energy.
Costs: annual costs are in $/unit-year and are converted to $/day in the model.
Time: one representative day split into operational periods of equal length.
"""
from dataclasses import dataclass, field, replace
from typing import Dict, List, Optional, Tuple
from .flows import Port, FlowSystem
from .needs import NeedSystem
from .attributes import AttributeSystem

FORMS = ("fuel", "elec", "h2")
LOCATIONS = ("R", "H", "D")  # remote resource site, hub, demand center


@dataclass(frozen=True)
class Design:
    """A technology design (module). Kinds:

    convert   : in (form_in, loc) -> out (form_out, loc) with efficiency eff.
                Capacity is output MW.
    renewable : produces (form_out, loc) up to capacity * availability profile; form_out defaults to elec.
    transport : moves form between loc_from and loc_to with fractional loss.
                Capacity is MW (or MW_th) of flow sent; optionally bidirectional.
    store     : stores form at loc. Capacity is energy (MWh); power = energy / duration_h.
    """
    name: str
    kind: str
    annual_cost: float                 # $/unit-yr for capacity (annuity + fixed O&M)
    fixed_cost: float = 0.0            # $/yr lump cost if any new capacity is built
    var_cost: float = 0.0              # $/MWh of output (convert/renewable) or of flow sent (transport)
    var_cost_profile: Optional[str] = None  # optional Scenario.profiles key: var_cost is multiplied by profile[t]
    form_in: Optional[str] = None
    form_out: Optional[str] = None
    loc: Optional[str] = None
    eff: float = 1.0
    emis: float = 0.0                  # tCO2 per MWh of input (residual, recorded only)
    profile: Optional[str] = None      # availability profile key for renewables
    loc_from: Optional[str] = None
    loc_to: Optional[str] = None
    loss: float = 0.0
    bidirectional: bool = False
    form: Optional[str] = None         # for transport / store
    duration_h: float = 4.0
    eta_c: float = 1.0
    eta_d: float = 1.0
    max_cap: float = 5000.0

    input_ports: Tuple[Port, ...] = ()
    output_ports: Tuple[Port, ...] = ()
    activity_unit: str = "MW"  # canonical process/sink/withdraw activity; mass uses tonne/h
    destination: Optional[str] = None
    conserve_energy: bool = False
    conserve_mass: bool = False

    interface_role: str = "implementation"  # adapter uses ordinary explicit process equations

    # ports, for readability and later composition work
    def inputs(self) -> List[Tuple[str, str]]:
        if self.kind == "process":
            return [(p.form, p.location) for p in self.input_ports]
        if self.kind == "sink":
            return [(self.form, self.loc)]
        if self.kind == "convert":
            return [(self.form_in, self.loc)]
        if self.kind == "transport":
            ins = [(self.form, self.loc_from)]
            if self.bidirectional:
                ins.append((self.form, self.loc_to))
            return ins
        if self.kind == "store":
            return [(self.form, self.loc)]
        return []

    def outputs(self) -> List[Tuple[str, str]]:
        if self.kind == "process":
            return [(p.form, p.location) for p in self.output_ports]
        if self.kind == "withdraw":
            return [(self.form, self.loc)]
        if self.kind == "sink":
            return []
        if self.kind in ("convert", "renewable"):
            return [(self.form_out or "elec", self.loc)]
        if self.kind == "transport":
            outs = [(self.form, self.loc_to)]
            if self.bidirectional:
                outs.append((self.form, self.loc_from))
            return outs
        if self.kind == "store":
            return [(self.form, self.loc)]
        return []


@dataclass
class Scenario:
    periods: int
    hours: float                                   # hours per period
    demand_D: List[float]                          # MW at the demand center, per period
    hub_energy: float                              # MWh/day flexible requirement at the hub
    hub_max_rate: float                            # MW
    profiles: Dict[str, List[float]]               # availability factors per period
    fuel_price_R: float                            # $/MWh_th at the remote site
    voll: float                                    # $/MWh penalty for unmet requirements
    designs: Dict[str, Design] = field(default_factory=dict)
    days: float = 1.0                              # days represented by the periods
    extra_demand: Dict[str, List[float]] = field(default_factory=dict)  # firm MW at R or H, per period
    locations: Tuple[str, ...] = LOCATIONS                               # location names
    fuel_sites: Tuple[str, ...] = ("R",)                                 # where fuel can be bought
    hub_loc: str = "H"                                                   # location of the flexible load
    coords: Dict[str, Tuple[float, float]] = field(default_factory=dict) # km, for spatial worlds

    flow_system: Optional[FlowSystem] = None
    need_system: Optional[NeedSystem] = None  # opt-in: old worlds retain their spill convention
    attribute_system: Optional[AttributeSystem] = None

    interface_system: object | None = None  # InterfaceSystem, imported lazily to avoid cycles

    # Optional representative-day structure (legacy designs only). period_weights[t] multiplies the
    # operating cost and emissions of period t, e.g. the number of days that period's representative
    # day stands for (use with days=365 for annual costs). cycle_length makes storage cyclic within
    # each block of that many periods (one representative day) instead of over the whole horizon.
    period_weights: Optional[Tuple[float, ...]] = None
    cycle_length: Optional[int] = None
    # Alternative to cycle_length: explicit (start, length) blocks, so representative periods of different lengths
    # (e.g. 24-hour days and a 72-hour cold snap) each cycle on their own. Blocks must cover all periods.
    cycle_blocks: Optional[Tuple[Tuple[int, int], ...]] = None
    # Rolling-horizon operation (all off by default). store_initial: starting level per store; such stores do not wrap
    # around, and their end-of-horizon level is a separate variable. store_terminal_value: value per unit of level left
    # at the end of the horizon. fixed_activity: {(design, series): {period: value}} commitments, e.g. releases in transit.
    store_initial: Optional[Dict[str, float]] = None
    store_terminal_value: Optional[Dict[str, float]] = None
    fixed_activity: Optional[Dict[Tuple[str, str], Dict[int, float]]] = None

    # Optional demands associated with actors (techgraph.demands.Demand). They add to extra_demand in the
    # physical balance and carry an owner and a segment for institutions and cost accounting.
    demands: Tuple[object, ...] = ()

    def with_designs(self, **updates) -> "Scenario":
        """Return a copy with some designs replaced by modified versions."""
        new = replace(self, designs=dict(self.designs))
        for name, kw in updates.items():
            new.designs[name] = replace(new.designs[name], **kw)
        return new


def default_designs() -> Dict[str, Design]:
    d = [
        Design("GEN_D", "convert", annual_cost=90_000, var_cost=3.0,
               form_in="fuel", form_out="elec", loc="D", eff=0.38, emis=0.20),
        Design("GEN_R", "convert", annual_cost=80_000, fixed_cost=1_000_000, var_cost=2.0,
               form_in="fuel", form_out="elec", loc="R", eff=0.45, emis=0.20),
        Design("SOLAR_R", "renewable", annual_cost=55_000, loc="R", profile="solar_R"),
        Design("SOLAR_D", "renewable", annual_cost=75_000, loc="D", profile="solar_D"),
        Design("WIND_R", "renewable", annual_cost=110_000, loc="R", profile="wind_R"),
        Design("FUEL_TRANS", "transport", annual_cost=8_000, fixed_cost=1_500_000, var_cost=1.0,
               form="fuel", loc_from="R", loc_to="D", loss=0.01),
        Design("LINE_RH", "transport", annual_cost=40_000, fixed_cost=4_000_000,
               form="elec", loc_from="R", loc_to="H", loss=0.03, bidirectional=True),
        Design("LINE_HD", "transport", annual_cost=15_000, fixed_cost=1_000_000,
               form="elec", loc_from="H", loc_to="D", loss=0.02, bidirectional=True),
        Design("BATT_H", "store", annual_cost=30_000, form="elec", loc="H",
               duration_h=4.0, eta_c=0.95, eta_d=0.95),
        Design("FUEL_STORE_D", "store", annual_cost=500, form="fuel", loc="D",
               duration_h=12.0, max_cap=5000.0),
    ]
    return {x.name: x for x in d}


def default_scenario() -> Scenario:
    return Scenario(
        periods=4,
        hours=6.0,
        # night, morning, afternoon, evening
        demand_D=[80.0, 110.0, 120.0, 140.0],
        hub_energy=360.0,
        hub_max_rate=40.0,
        profiles={
            "solar_R": [0.00, 0.45, 0.55, 0.00],
            "solar_D": [0.00, 0.35, 0.42, 0.00],
            "wind_R":  [0.50, 0.20, 0.12, 0.08],
        },
        fuel_price_R=25.0,
        voll=3000.0,
        designs=default_designs(),
    )
