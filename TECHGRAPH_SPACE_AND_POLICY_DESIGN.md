# Techgraph: Space and Policy Layers

*Design note. Mamadou Seck, PhD. October 2026. Status: proposal.*

## 1. Purpose

This note proposes two layers for Techgraph: a spatial layer that can represent real geographies, and a policy layer of generic rules defined over the technology network. Both must stay true to the generic framing of the framework. Needs and resources are substances. Technologies perform three functions on them: processing, transport and storage. Institutions shape which responses are possible and who pays for them. Nothing in either layer should be specific to electricity or to water.

The note draws on the Virginia data-center case, the first application of Techgraph to a real geography and a real policy regime. That case worked, but it showed where the current design is shaped by electricity and where abstract worlds hide what real geographies reveal.

## 2. What the Virginia case showed

Six lessons motivate the design.

1. **Boundaries rarely coincide.** The PJM Dominion zone, the state of Virginia and Dominion's service territory are three different boundaries. A plant in West Virginia served Virginia customers and was counted as an import by the state's own plan. A cooperative shared Dominion's transmission but none of its mandates.
2. **Data comes in its own boundaries.** Generation data existed by state, load data by zone, sales data by utility. Calibration required reconciling them by hand.
3. **Rules need scope.** Almost every rule applied to a jurisdiction or an owner, not to a model node. The portfolio standard covered one utility's retail sales. The emission cap covered in-state plants.
4. **Boundary permeability is a first-order variable.** Whether a cap could be met by buying allowances elsewhere changed resource costs by about 28%. Whether imports were capped changed the estimated leakage by a factor of two to three.
5. **Accounting choices change conclusions.** Counting or excluding imported emissions, transfers and health damages changed which pathway looked cheapest.
6. **Rules must hold where results are reported.** Three times, a rule enforced in planning was violated in the separate dispatch used for reporting. Re-imposing a quantity rule as a price in a separate optimization proved either inconsistent or knife-edge.

The first five lessons point to the spatial layer and to the attributes rules need. The last points to a consistency principle.

## 3. Design principles

1. **Generic primitives.** Rules and spatial objects are defined over substances, functions, locations, periods and actors. Domain terms such as capacity credit, safe yield, portfolio standard or water right appear only as parameters of a case.
2. **Separate the physical, institutional and data geographies.** The network that moves substances, the jurisdictions that make rules and the units in which data arrive are distinct objects, related by explicit mappings.
3. **Abstract worlds are a special case.** Synthetic worlds use the same code path as real ones. They differ only in where atoms and their attributes come from.
4. **Single-solve consistency.** Every active rule holds in the same solution that produces the reported flows, costs and emissions.
5. **Honest accounting.** Every payment is classified as a resource cost or a transfer. Dispatch signals, such as the implicit price of a binding cap used to steer operations, never appear as costs.
6. **Report on any boundary.** Results can be reported on any partition, so a model can be compared with data on the data's own boundary.

## 4. The spatial layer

### 4.1 Atoms

Atoms are the finest spatial units. Each atom has a geometry, or at least a centroid and an area, and a set of attributes. Typical attributes are population, demand by segment, land use, resource potential, climate and hydrology.

Two kinds of atom are useful. Administrative atoms, such as counties, match how most data are published. Grid atoms, such as H3 hexagons, give uniform resolution and make synthetic worlds a special case. A study chooses one atom set. Mappings between atom sets are computed by area or population overlap.

### 4.2 Partitions

A partition groups atoms. Partitions overlap freely. Examples:

- jurisdictions: states, counties, municipalities;
- service territories: utilities, cooperatives, water districts;
- physical systems: balancing zones, watersheds, aquifers, river basins;
- data units: the boundaries in which a source publishes, such as states for generation data or zones for load data.

Where a boundary cuts through an atom, membership is fractional. The weight depends on what is being divided. Area suits land and resources. Population suits households. Demand suits load. A partition therefore stores membership shares by weighting basis, not a single assignment.

### 4.3 Model locations

Model locations are the nodes of the technology network. Each is a cluster of atoms chosen for a study. The clustering is explicit and stored with the case. Resolution becomes a modeling choice that can be varied and tested, rather than a fixed property of the world.

From the atom memberships, the layer derives three mappings:

- each location's share of each partition, by weighting basis;
- each partition's share of each location;
- the boundary between any partition and the rest of the network, as the set of links that cross it.

The Virginia case used three hand-chosen locations: Northern Virginia, the rest of the zone, and an external market node. In this design, those become clusters of counties, and the zone, the state and each utility territory become partitions over the same counties.

### 4.4 Topology

Links connect locations. Each link carries a substance and a function, which is usually transport. It has a direction, a capacity, a loss rate and a length. Links come from one of two sources:

- **real infrastructure:** transmission corridors, pipelines, rivers, canals and roads, with their actual capacities where known;
- **adjacency and distance,** where infrastructure is not represented explicitly.

Direction matters more for some substances than others. Water in a river flows downstream without help, and moving it upstream requires pumping. Topology should therefore support links that are free in one direction and costly in the other. It should also support couplings between substances. Pumping water uphill consumes energy, and that energy demand belongs to the energy network at the pump's location.

### 4.5 Spatial fields and stress events

Resources and weather are fields over atoms and time: solar irradiance, wind, temperature, rainfall and streamflow. They are aggregated to locations along with everything else.

Stress events must be defined spatially. In Virginia, the cold snap mattered because it affected the whole regional market at once. Imports were least available exactly when they were most needed. A drought plays the same role in water. A stress event is therefore a set of atoms and a period, with the fields altered over both. Its spatial correlation is then represented rather than assumed.

### 4.6 Stocks with geography

Some stores belong to geography rather than to a technology. An aquifer underlies several counties and jurisdictions. A reservoir sits in one basin but serves several districts. Such stocks are attached to a physical partition. Rules on their levels are scoped by that partition, while the demands drawing on them belong to other partitions. The separation of partitions makes this straightforward. A purely node-based model would have to force the aquifer, the counties and the users into the same nodes.

### 4.7 Data adapters and reporting

Adapters load atoms, attributes, partitions and infrastructure from public sources, and record the source and boundary of each. Reporting functions aggregate any result to any partition. A generation balance can then be reported on the state boundary for comparison with state data, and on the zone boundary for comparison with zone data, from the same solution.

### 4.8 Sketch

```python
Atom(id, geometry, attributes: dict)
Partition(name, kind, members: dict[atom_id -> dict[basis -> share]])
Location(name, atoms: list[atom_id])
Link(name, substance, src, dst, capacity, loss, length, directional_cost)
Field(name, unit, values: dict[atom_id -> series])
StressEvent(name, atoms, periods, field_changes)
Geography(atoms, partitions, locations, links, fields)
    .share(location, partition, basis)      # location's share of a partition
    .boundary(partition)                    # links crossing the partition's boundary
    .report(result, partition)              # aggregate any result to a partition
```

## 5. The policy layer

### 5.1 Measures

A measure is a weighted sum over network quantities, selected by filters. Every rule is defined on one or two measures.

| Measure kind | Examples |
|:--|:--|
| Flow | Output of a set of designs; demand of a set of owners |
| Stock | Level of a store or a geographic stock |
| Capacity | Installed capacity of a set of designs |
| Byproduct | Emissions or pollutant loads, as flows of a byproduct substance |
| Boundary crossing | Flows on links that cross a partition's boundary |

Filters select by substance, design, function, location, period, partition, owner and segment. Weights scale contributions, for example to count only part of an aggregated resource. A measure's scope is its partition filter, so rules defined on measures inherit jurisdiction directly from the spatial layer.

### 5.2 Requirement

A requirement compares a measure with a bound or with another measure.

- **Floor:** measure is at least a bound. Examples: a procurement target, a minimum flow.
- **Ceiling:** measure is at most a bound. Examples: an import limit, a withdrawal permit, a capacity-factor limit.
- **Share:** one measure is at least or at most a fraction of another. Examples: a portfolio standard, a reuse mandate.

Each requirement has a schedule of bounds over time and an escape structure:

- **none:** the requirement is strict, and a shortfall is reported as non-compliance;
- **a price:** a shortfall is allowed at a stated price per unit, such as a compliance payment;
- **tiers:** cheaper escapes up to stated limits, such as out-of-state credits up to a share;
- **a tradable pool:** the shortfall can be covered from an outside pool at a market price, such as allowances from other states.

The escape structure determines a boundary's permeability. It is a first-order variable, so it must always be stated explicitly, never left to a default.

### 5.3 Adequacy

Adequacy requires that the contributions of resources under a stress condition cover demand under that condition, plus a margin.

- **Contributions** are ratings per design, possibly partial and possibly location-specific.
- **The stress condition** is a set of periods, possibly tied to a spatial stress event.
- **Demand under stress** can exclude the credited part of flexible demand. Credit is a stated fraction, and it should account for how long demand can be interrupted.

In electricity, the stress condition is the winter peak and the contributions are capacity credits. In water, the stress condition is the drought of record and the contributions are safe yields. The structure is the same.

The Virginia case showed two cautions. A credit is valid only if the scarcity it replaces is rare enough for the credited flexibility to cover it. And resources can be built for their rating alone, never used in the modeled conditions. Both should be visible in results.

### 5.4 Charge

A charge places a price on a measure: a carbon price, a water tariff, an extraction fee, a pollution fee. Each charge is classified as a resource cost or a transfer. Most charges are transfers: they raise users' costs without consuming resources.

### 5.5 Priority

Priority sets the order in which demands are curtailed under shortage. It is defined on owners and segments. In electricity, it was not needed in the Virginia case. In water, it is central: prior appropriation, seniority, and drought curtailment tiers that protect municipal use before agricultural use. Priority can be represented as a ranking of curtailment costs, or as explicit sequencing constraints.

### 5.6 Process rules

Process rules govern designs over time: earliest availability, maximum build rates, permitting lags, and schedules with contingencies. The Virginia storage law set petition deadlines, not installation dates, and part of it depended on a future regulatory finding. Process rules should express petition, approval and installation as separate steps with stated lags.

### 5.7 Exemptions

An exemption removes designs or owners from a rule's scope. Exemptions must be explicit members of a rule's definition. In Virginia, non-combustion gas was exempt from the emission cap. That one exemption explained why a lower-cost pathway had higher emissions.

### 5.8 Attributes every rule carries

| Attribute | Meaning |
|:--|:--|
| Scope | The partition, owners and segments the rule covers |
| Boundary treatment | Whether and how flows crossing the scope's boundary count |
| Escape | None, price, tiers or tradable pool, with prices and limits |
| Accounting class | Whether payments under the rule are resource costs or transfers |
| Timing | Schedule of bounds, lags and contingencies |
| Exemptions | Designs or owners explicitly excluded |
| Implicit price | Reported for every rule, with its interpretation |

A rule's implicit price needs interpretation. When a requirement is met by building, its price reflects a construction cost. When it is met by rationing, its price reflects the value of the rationed demand. When it binds at its escape, its price equals the escape price. Results should say which case applies.

## 6. Consistency and accounting

### 6.1 Single-solve consistency

Every active rule must hold in the solution that produces reported quantities. The Virginia work violated this three times. A planning model enforced a cap or an import limit, and a separate operating model, used for the energy balance, ignored it. Re-imposing a quantity limit as a price in the separate model either failed to reproduce the limit or produced extreme, knife-edge dispatch.

The design therefore requires that reported flows, costs and emissions come from the solve in which all rules are active. Separate operating solves may still be used for detail, such as hourly prices, but never for quantities that rules constrain.

### 6.2 Cost reporting

Every result reports two costs:

- **Total cost,** including transfers. This is what users pay.
- **Resource cost,** excluding transfers. This is what the system consumes.

Implicit prices used only as dispatch signals are excluded from both.

### 6.3 Emissions and other byproducts

Byproducts are reported on several boundaries at once:

- on the rule's own boundary, such as in-state plants;
- including flows crossing the boundary, such as imported electricity, at stated emission factors;
- on any other partition requested.

Displacement across a boundary then becomes measurable. That connects to a regularity suggested by the Virginia case: a mismatch can be resolved, or merely displaced across a boundary, and rules defined on boundaries create incentives to displace.

## 7. Generality test

The primitives should express both the Virginia electricity case and the planned water world without domain-specific classes.

| Primitive | Electricity (Virginia) | Water |
|:--|:--|:--|
| Floor | Storage procurement | Minimum instream flow |
| Share | Renewable portfolio standard | Conservation or reuse mandate |
| Ceiling | Import reliance cap; capacity-factor limit | Withdrawal permit; groundwater pumping cap |
| Tradable cap | RGGI allowances | Water rights market; nutrient trading |
| Byproduct requirement | CO₂ cap | Pollutant load limit |
| Stock requirement | Not used | Minimum reservoir or aquifer level |
| Adequacy | Capacity credit at the winter peak | Safe yield in the drought of record |
| Charge | Carbon price | Tiered tariffs; extraction fees |
| Priority | Load-shedding order | Prior appropriation; drought curtailment tiers |
| Process | Petitions, permitting, build rates | Dam and desalination permitting |
| Exemption | Non-combustion gas outside the cap | Exempt wells; senior rights outside a restriction |

The water world exercises four features the Virginia case barely used:

1. **Stocks as primary objects,** with rules on levels and geography of their own.
2. **Directional topology,** with downstream flow and costly upstream pumping.
3. **Priority** as a central rule, not an edge case.
4. **Coupling across substances,** since pumping and desalination draw on the energy network and hydropower supplies it.

If a water rule cannot be expressed with these primitives, the primitives should be revised. A water-specific rule class would be a sign that the framing has failed.

## 8. Migration from the current code

The current institutions module already contains special cases of the primitives. Each existing class becomes a thin, backward-compatible constructor:

| Current class | Primitive |
|:--|:--|
| EnergyShare | Share requirement on output measures, with base filters and escape tiers |
| CapacityQuantity | Floor on a capacity measure |
| EnergyCeiling | Ceiling on a flow measure, against demand or installed capacity |
| EmissionCap | Ceiling on a byproduct measure, with an escape |
| AccreditedCapacity | Adequacy, with ratings, locations, owners and flexibility credit |
| Demand owners and segments | Measure filters on partitions |
| Demand flexibility | Adequacy credit and operational flexibility on demands |

Suggested steps:

1. Introduce measures and the spatial layer, with the current locations as trivial clusters.
2. Reimplement the existing rule classes on the primitives, and confirm that all existing tests pass unchanged.
3. Add charges, priority, stock requirements and tradable escapes.
4. Add the invariant tests in Section 9.
5. Rebuild the Virginia case on county atoms, as a regression test of the spatial layer.
6. Build the water world directly on the primitives.

## 9. Invariant tests

These tests would have caught most of the errors found during the Virginia work.

- Reported flows satisfy every active rule within tolerance.
- No dispatch-only price appears in any reported cost.
- Total cost minus transfers equals resource cost.
- Aggregating any result to the full world equals the sum over locations.
- Reporting on a partition that coincides with a location reproduces that location's results.
- Removing a rule never raises the optimal cost of a single cost-minimizing solve. This need not hold over a sequence of solves (see Section 10).
- A rule with an escape never reports a shortfall above its stated limits.
- Consumption-based byproducts on a partition equal its own byproducts plus those attributed to its net inflows, at the stated factors.

## 10. Open questions

1. **Atom choice.** Counties match most data. Hexagons give uniform resolution and continuity with synthetic worlds. A study may need both, with an explicit mapping.
2. **Fractional membership.** Area, population and demand weights give different answers for the same boundary. The basis should be chosen per quantity and recorded.
3. **Tradable pools.** Representing an outside pool as a fixed price is simple but static. A pool with its own supply curve would capture scarcity across a region.
4. **Endogenous rules.** All rules here are fixed. The framework's account of institutions responding to service deficits suggests rules that change when measures cross thresholds. The design should leave room for that, without implementing it yet.
5. **Sequential decisions.** A constraint imposed early can change later options. In a sequential model, adding a constraint does not always raise cumulative cost. That interaction between the policy layer and the dynamic engine deserves its own experiment.
6. **Data provenance.** Every attribute and partition should record its source and boundary, so that calibration mismatches can be traced to their origin.

## 11. Implementation status

Migration steps 1 to 3 are largely complete.

**Spatial layer** (`techgraph/space.py`): atoms, partitions with fractional membership on a stated basis, locations
as clusters of atoms, and a geography that resolves partitions into location weights, aggregates results to
partitions and identifies links crossing a partition. `from_coords` connects the point worlds of `spatial.py` and
`geography.py`. Abstract worlds are the trivial case of one atom per location.

**Policy primitives** (`techgraph/policy.py`):
- measures: flow, capacity, capacity-hours, demand (any substance), byproduct, stock levels (storage designs and
  residual stocks), and boundary flows (net inflow across a set of locations);
- Requirement: floors, ceilings and shares, annual or per period, with price escapes, share-limited tiers and
  quantity-limited escape steps (an outside pool as a supply curve), for floors and caps alike;
- Adequacy: ratings, margin, stress periods, owner and location scope, partial flexibility credit;
- Charge: a price on measures, classified as a resource cost or a transfer, with the amount reported;
- priority, through demand shortage costs and `apply_priority`;
- process rules, through `lagged` schedules.

Every rule reports both sides of its constraint and the largest violation by the reported solution, so the invariant
"reported results satisfy every rule" is tested directly.

**Generic substances.** Demands and renewable resources carry a substance, electricity by default. The engine
builds balances for any substance referenced by designs or demands. A water chain with no electricity solves and
balances.

**Verification.** The Virginia reference runs reproduce with zero difference, the GenX benchmarks still match to
about 2e-16, and the full suite passes with the same three pre-existing failures.

**Not yet implemented:** data adapters for real geographies, spatial fields and stress events, petition and
approval steps beyond lagged schedules, endogenous rules, and the curated world builder from the water-world
specification.
