# Techgraph: a stylized water world and an electricity benchmark

Specification, 30 September 2026

## 1. Purpose

This note specifies two extensions. The first is a stylized water world, which tests the theory in a domain where process, storage and transport are all central and where conservation holds physically. The second is a benchmark against established electricity capacity-expansion models. It checks whether the Techgraph optimizer reaches the answers that a mature planning model reaches when both solve the same problem.

The two serve different purposes. The water world asks whether the theory explains a real pattern of technological choice. The benchmark asks whether the machinery is sound. The benchmark should come first, because a discrepancy there would undermine any domain result.

## 2. The two-basin water world

### 2.1 Geography

There are three locations. Basin U is an upland basin with surface water and a dam site. Basin A is an aquifer basin with groundwater. City C is a coastal city with all of the demand. U is far from C, and A is at an intermediate distance. Seawater is available only at C.

### 2.2 Forms

The forms are surface water, groundwater, seawater, potable water, wastewater and recycled water. A seventh form, water service, is the demanded output. All quantities are in millions of cubic metres per period. Electricity enters as a purchased input with a price, not as a modeled system.

### 2.3 Catalog

The world uses a fixed, curated catalog instead of the random recipe generator. This matches the v0.2 framework's original commitment to a catalog of recognizable technology classes. The catalog is in the table below. Lifetimes and leads are stated in decision periods of one year.

| Design | Function | Location | Life | Lead |
|---|---|---|---|---|
| Surface intake | Surface water to conveyance | U | 40 | 2 |
| Dam and reservoir | Stores surface water; loses some to evaporation | U | 80 | 8 |
| Aqueduct U–C | Moves surface water; shared and lumpy | U to C | 60 | 6 |
| Wellfield | Extracts groundwater from the aquifer stock | A | 30 | 1 |
| Pipeline A–C | Moves groundwater; shared and lumpy | A to C | 50 | 3 |
| Conventional treatment | Surface or groundwater to potable, with a small loss | C | 30 | 2 |
| Desalination | Seawater and electricity to potable water plus brine | C | 25 | 4 |
| Urban use | Potable water to water service plus wastewater | C | 40 | 0 |
| Non-potable reuse | Wastewater to recycled water, which substitutes for part of the service | C | 25 | 2 |
| Potable reuse | Wastewater and electricity to potable water | C | 25 | 3 |
| Discharge | Wastewater released to the environment, with an impact record | C | — | 0 |
| Treated-water storage | Short-term potable storage | C | 30 | 1 |

Urban use converts potable water into service and returns a declared share as wastewater. This makes reuse a genuine recycling loop, not an extra supply.

### 2.4 Two clocks

A decision period is one year. Each year has four seasonal operating bins. Demand peaks in the dry season, while surface inflow peaks in the wet season. The resulting temporal mismatch is the reservoir's whole economic purpose. The v4 bins mechanism supports this directly.

### 2.5 Resources and stocks

Surface inflow at U is a seasonal resource with a year-to-year multiplier, so that drought years can be scheduled. Groundwater is a natural stock at A with a large initial level and a small annual recharge. Overdraft is possible, and the stock can run down. Seawater at C is unlimited but expensive to treat.

### 2.6 Demand

Water service at C starts at a level the initial system can meet, and grows by about 1% a year. The dry-season peak is about 30% above the annual mean.

### 2.7 Costs

Costs must be calibrated before the world is used for substantive claims. The first version should rely only on the widely reported cost ordering of water sources. Local surface and groundwater are cheapest. Imported water costs more, and the cost rises with distance. Reuse comes next, and seawater desalination is usually the most expensive and the most energy-intensive. Every number should be declared as an assumption, with its source recorded once calibration begins. Desalination and reuse should carry learning curves. Dams and aqueducts should carry lumpy costs.

### 2.8 Treatments

1. Baseline: growth, with ordinary inflow variation.
2. Drought: inflow at U falls by 40% for five consecutive years, starting at period 30.
3. Aquifer decline: recharge at A falls by half over periods 10–50.
4. Cheaper desalination: a faster learning rate for desalination.
5. Environmental flow: a minimum release requirement at U, which reduces divertible inflow.
6. Early aqueduct: the aqueduct is built in period 0 as part of the inherited system.

### 2.9 Questions and expected patterns

The world is built to ask three questions.

1. Does the order of adoption follow cost and lead time? The expected order is local supply, then storage, then import, then reuse, then desalination. A different order would signal either a cost assumption or a mechanism worth explaining.
2. Does drought timing change the path? A drought that arrives while the aqueduct is under construction should push the system toward faster options, such as reuse or desalination. Under the static forecast, the planner should react late. Under the oracle it should prepare.
3. Does early transport infrastructure lock out reuse? Compare treatment 6 with the baseline. If an inherited aqueduct delays reuse by many years, that is entrenchment through sunk shared infrastructure. A functional-exclusion run, which removes the aqueduct in a later period, would measure the cost of that dependence.

These questions map onto real cases. Southern California relied on long-distance imports and later adopted large-scale potable reuse. Singapore diversified into reuse and desalination with few local sources. Israel shifted toward desalination after prolonged aquifer stress. Cape Town faced near-exhaustion of its reservoirs in 2018. The stylized world cannot reproduce any of these, but it can show whether the mechanisms that seem to drive them arise in the model.

### 2.10 Model changes needed

Most of what the world needs exists in v4: bins, stocks with retention, corridors, lumps, resource paths, learning and forecast rules. Four additions are needed.

1. A world builder for curated catalogs, so that a world can be declared by hand.
2. Stocks with exogenous inflow and outflow, so that an aquifer can be recharged and drawn.
3. A minimum-release constraint on a resource, for environmental flows.
4. Resource paths that can rise as well as fall. The flow audit currently requires every resource multiplier to be at most one. Declaring the maximum as the wettest year and scaling down from it is a simple workaround.

### 2.11 First experiments

1. Hand-check: one year, no growth and no drought. The cheapest feasible system should be chosen, and it can be computed by hand.
2. Seasonal amplitude sweep: dry-season peaks of 0%, 30% and 60%. Reservoir and treated-water storage should grow with amplitude.
3. Drought timing: the drought starting at periods 10, 30 and 50, under the static and oracle forecasts.
4. Lock-in: the baseline against the early-aqueduct world, comparing the year reuse is first adopted.

## 3. The electricity benchmark

### 3.1 Choice of benchmark model

GenX is the better primary benchmark. It is an open-source electricity capacity-expansion model written in Julia and JuMP. It ships with example systems, such as a small New England case in one-zone and three-zone versions, and it runs with free solvers including HiGHS, the solver Techgraph also uses. It supports two multi-stage modes. One solves the whole investment path with perfect foresight. The other solves stages in sequence, with earlier decisions fixed, which GenX calls myopic. This pair matches the forecast question raised by the ordering result. It also supplies the full-horizon perfect-foresight bound that Techgraph lacks.

ReEDS is harder to use directly. Its source is freely available, but it requires a commercial GAMS license, and NREL's documentation says the open-source solver route is not actively maintained. It is also a national-scale model, much larger than any Techgraph world. It is better used as a qualitative benchmark: compare Techgraph's build order under stylized scenarios with the patterns in published ReEDS scenario results.

Julia cannot be installed in my current environment, because its download servers are not on the allowed network list. GenX would therefore need to run on your machine. Alternatively, the network settings can be extended to allow it.

### 3.2 Stage A: single-stage equivalence

Build one small case that both models can express exactly.

- Three zones, connected by transmission lines with losses.
- Technologies: a gas combined cycle and a gas turbine (fuel to electricity), wind and solar (availability profiles), and batteries (storage with a duration and round-trip efficiency).
- Time: one representative day of 24 hours, weighted to a year. Both models use the identical series.
- Greenfield: no existing capacity.
- Switched off in GenX: unit commitment, reserve requirements and policy constraints.
- Costs: GenX annualized investment and fixed O&M mapped onto Techgraph's annual capital charge and O&M share.

Techgraph's legacy energy design kinds (conversion, renewable, transport and store) appear to cover these technologies. Whether the legacy core supports three zones with zone-specific demand and availability profiles needs to be checked first.

**Acceptance criteria.** The objectives should agree within 0.1%. Built capacities should agree within 1% for each technology and zone, except where the LP has alternative optima with equal cost. Such ties should be identified explicitly, not hidden. Hourly dispatch should agree where capacities agree.

### 3.3 Stage B: multi-stage comparison

Extend the case to about six investment stages, with demand growth and falling wind, solar and battery costs. Run GenX in both perfect-foresight and myopic modes. Run Techgraph with the rolling oracle at a horizon covering all stages, which is its own perfect-foresight solve. Also run it at shorter horizons with the static forecast.

**What this tests.** First, Techgraph's full-horizon solve should match GenX's perfect-foresight mode within the Stage A tolerances. Second, the gap between myopic and perfect-foresight paths should be similar in both models. If it is, the forecast and ordering results rest on standard planning behavior. If it is not, the difference needs explaining before those results are published.

### 3.4 Stage C: mechanisms Techgraph adds

Once Stages A and B agree, compare runs with Techgraph's added mechanisms switched on: construction leads, lumpy transmission corridors and switching costs. GenX's results serve as the reference without those frictions. This shows how much of Techgraph's behavior comes from mechanisms a standard planning model omits. That is the comparison a reviewer will ask for.

## 4. Sequence and effort

| Step | Work | Rough effort |
|---|---|---|
| 1 | GenX Stage A case, both models | 2–3 days, mostly input mapping |
| 2 | GenX Stage B multi-stage comparison | 2 days |
| 3 | Curated-catalog world builder and stock inflows | 2 days |
| 4 | Water world, first four experiments | 2–3 days |
| 5 | Water treatments and lock-in tests | 3–4 days |
| 6 | GenX Stage C and a ReEDS qualitative comparison | 2–3 days |

The benchmark comes first because it protects every later result. The water world then reuses the v4 mechanisms that the benchmark has checked.
