# Techgraph handoff

*Mamadou Seck, PhD. State as of 4 October 2026.*

This note records the state of the framework, the two applied cases, the open threads and the lessons learned, so that
work can resume without reconstructing context.

## 1. Summary

Techgraph is a network model of technological change. Needs and resources are substances; technologies process,
transport and store them; institutions shape which responses are possible and who pays. Over the recent sessions the
framework gained a generic policy layer, a spatial layer, generic substances and rolling-horizon operation, all
verified against the existing tests, the GenX benchmarks and stored reference runs. Two applied cases now live in
`cases/`: Virginia data centers and power (including a replication of the 2026 Virginia Energy Plan), and the
Washington water supply (including a replication of ICPRB's 2025 water supply study).

Status in one line each:
- Framework: clean, tested, documented. Next core work is listed in Section 8.
- Virginia case: complete for version 9 (own assumptions) and version 10 (the plan's assumptions). Publication of the
  related articles is paused by the author.
- Potomac water case: a replication draft exists for discussion with ICPRB; the Techgraph version of the system runs
  and the convergence test is one step from complete.

## 2. Repository map

| Path | Content |
|:--|:--|
| `techgraph/` | The model package |
| `techgraph/policy.py` | Generic policy primitives: measures, Requirement, Adequacy, Charge, priority, lagged schedules |
| `techgraph/space.py` | Spatial layer: atoms, partitions, locations, geography |
| `techgraph/institutions.py` | Legacy rule classes, converted to primitives by `to_primitive`; window integration and audit |
| `techgraph/demands.py` | Demands with owner, segment, substance, flexibility and shortage cost |
| `techgraph/operation.py`, `model.py`, `dynamic.py`, `flows.py`, `catalog.py` | Core engine, with the changes in Section 3 |
| `tests/` | Test suite, including `test_institutions.py`, `test_space_policy.py`, `test_policy_primitives.py` |
| `genx_bench/` | GenX verification benchmarks (Stage A, Stage B, multi-day) |
| `cases/virginia_dc/` | Virginia case: models, experiment scripts, number derivation, reference check |
| `cases/potomac_water/` | Water case: data, rule-based simulator, Techgraph operation, scan, draft |
| `TECHGRAPH_SPACE_AND_POLICY_DESIGN.md` | Design of the spatial and policy layers, with implementation status |
| `INSTITUTIONS.md`, `REPRESENTATIVE_DAYS.md`, `DEMANDS.md` | Documentation of the v4 extensions |
| `Techgraph_Water_World_and_Benchmark_Spec.md` | The earlier spec for a stylized two-basin water world (not yet built) |
| `scratch/` | One-off scripts, not part of the package |

## 3. Core changes, in order

All additions are opt-in. With none of the new fields used, every equation is unchanged.

1. **Institutions** (`institutions.py`): portfolio shares with tiered escapes and owner or segment bases, capacity
   quantities, accredited capacity with locational scope and flexibility credit, emission caps, energy ceilings
   (share of demand or capacity factor). Each reports an implicit price and shortfall.
2. **Representative periods** (`catalog.py`, `operation.py`): period weights, variable-length cycling blocks (for
   example a 72-hour cold snap cycling as one block), and time-varying variable costs.
3. **Demands** (`demands.py`): owners, segments, curtailment and shifting with budgets, costs and daily limits; partial
   flexibility credit in adequacy rules.
4. **Weighted window outputs** (`dynamic.py`): planning windows report weighted annual energy and hourly activity by
   design, so energy balances can be taken from the solve in which all rules hold.
5. **Generic policy primitives** (`policy.py`): every rule is a Requirement, Adequacy or Charge on measures. Measures:
   flow, capacity, capacity-hours, demand (any substance), byproduct, stock level, boundary flow. Requirements can be
   annual or per period, with price escapes, share-limited tiers or quantity-limited escape steps (an outside pool as a
   supply curve). Every rule reports both sides of its constraint and its largest violation by the reported solution.
6. **Spatial layer** (`space.py`): atoms with attributes, overlapping partitions with fractional membership on a stated
   basis, locations as clusters of atoms, location and partition weights, aggregation to any partition, links crossing
   a partition, and `from_coords` for the point worlds of `spatial.py` and `geography.py`.
7. **Generic substances**: demands and renewable resources carry a substance (electricity by default); the engine builds
   balances for any substance referenced by designs or demands. Demands can carry a shortage cost, which expresses
   priority (`apply_priority`).
8. **Rolling-horizon operation** (`catalog.py`, `operation.py`): `store_initial` (a starting level; the store does not
   wrap around and its end level is a separate variable), `store_terminal_value` (value of what remains at the end), and
   `fixed_activity` (commitments, such as releases in transit).

## 4. Verification status

- **Test suite**: 725 passed. Three failures in `tests/test_network_worlds.py` predate this work and also occur on the
  unmodified handoff code. Run with
  `TECHGRAPH_BACKEND=scipy python3 -m pytest -q tests --ignore=tests/test_discovery.py --ignore=tests/test_measurement_spine.py --ignore=tests/test_stateful_replay.py`.
- **GenX benchmarks**: Stage A (12 single-period cases) and the multi-day cases agree with GenX to about 2e-16 relative.
  Stage B (six epochs, perfect foresight and myopic) agrees to the cent. Stage C (mechanism attribution) is not done.
- **Reference runs**: `cases/virginia_dc/check_reference.py` reruns two cases exercising every rule type and must print
  PASS with zero difference. It did after every core change in Section 3.

## 5. Virginia case

### Version 9: the case model under its own assumptions
Dominion zone calibrated to 2025, eight representative days with a cold snap, four demand owners, workload-based
data-center flexibility, the state's portfolio standard, storage mandates, RGGI, and a net-zero cap. Costs are reported
both in total and as resource cost, which excludes RGGI payments, carbon charges on imports and compliance payments
(transfers). Main results at moderate demand, 2026-2050:
- Current Policies $350 billion against No Policy $270 billion in total (ratio 1.29); $325 billion in resource cost
  (1.20). The plan's own ratio is 1.43.
- Net-zero pathways differ by a few percent; their ranking depends on whether transfers are counted.
- 2050 residential bill per 1,000 kWh: $265 under Current Policies, $240 without data-center growth, $313 with doubled
  small-reactor costs.
- Compute policies save $7-12 billion in total cost ($11-17 billion in resource cost) under high demand; crediting only
  half of flexible demand cuts savings by about a third. With a four-hour daily interruption limit, a harsher cold spell
  with reduced imports produced shortfalls up to 9 GW (without flexibility credit: 0, 0 and 6.4 GW by workload mix).

### Version 10: the Energy Plan's assumptions
Built after reading Appendix C of the plan. Key facts learned: the plan counts only in-state emissions (Mt Storm output
is an import); net zero is modeled through the RGGI allowance trajectory (27.2 million short tons in 2027, below 9.5 in
2037, zero in 2050); imports are capped at 30% of annual consumption; system costs include compliance costs; new
nuclear is limited to 600 MW every two years from 2035 and 4.8 GW in total, plus a required 400 MW fusion plant.

Results at moderate demand, strict RGGI cap:
| Pathway | Total cost | Ratio (plan) | In-state CO2 | Cap shortfall | 2050 bill |
|:--|--:|--:|--:|--:|--:|
| No Policy | $268B | 1.00 | 1,074 Mt | - | $186 |
| Current Policies | $483B | 1.80 (1.43) | 323 Mt | 49 Mt (2029-39) | $379 |
| Distributed Flexibility | $491B | 1.83 (1.31) | 362 Mt | 10 Mt | $386 |
| DF, In-State Priority | $521B | 1.94 | 405 Mt | 14 Mt | $404 |
| DF, No New Gas | $479B | 1.79 | 308 Mt | 34 Mt | $386 |

Other results: with the full state cap applied to the zone the shortfall is still 33 Mt; allowing allowance purchases at
$60 a ton cuts resource cost by about 28% and replaces most in-state decarbonization (about 400 Mt bought); new nuclear
reaches about 3.5 GW, offshore wind and imports about 21% and 30% of 2050 supply; leakage is bounded by the import cap
(4-13% of the in-state reduction); compute policies save 1-2%; stress tests show no shortfalls even with imports cut to
5 GW, because of the larger transmission and mandated storage.

**These divergences are not established findings.** They depend on assumptions the plan does not publish (its
financing rate, fixed costs and asset lives for annualizing capital costs), on the zone-versus-state scope, on eight
representative days and myopic planning, on load 3-9% above actual, on the omission of the plan's distributed-resource
growth under Current Policies, and on how distributed resources are valued. Agreements with the plan: Distributed
Flexibility emits more than Current Policies; the in-state variant is the most expensive; No New Gas is cheaper than
Current Policies; No Policy roughly triples in-state emissions; with the plan's health estimates, No Policy has the
highest total cost.

### Publication status
The LinkedIn article "Who Pays for AI Power" and the longer article "AI and the Grid" were finalized with version 9
numbers and corrected cost accounting. After the version 10 replication, the author paused publication. Any revival
must either restate results under the plan's assumptions or present the divergences as dependent on undocumented
assumptions, and should report results that cut both ways.

## 6. Potomac water case

### Sources
ICPRB, *2025 Washington Metropolitan Area Water Supply Study* (December 2025), with PRRISM results for 36 scenarios
(parsed into `data/wma_results.json`); USGS daily flows for the adjusted Little Falls series (01646502) and Point of
Rocks (01638500). The study's data-center analysis is led by Dr. Alimatou Seck, Director of Operations of CO-OP at ICPRB
(the author's sister), whom the author plans to contact with the draft.

### Stage W-A: data-center water demand
At the study's medium water use per power (800 gallons per MW-day average, 2,900 peak), the 2025 starting points agree
(about 5.0 GW implied by the study, 5.2 GW in the Virginia model). Growth differs by about a factor of two: the
Virginia model's paths under Energy Plan demand rates grow 2.1-3.0 times by 2049 (8.9-12.6 MGD average), the study's
medium scenario 5.5 times (22.2 MGD in 2050), because the study uses PJM's steeper forecast and because the Virginia
model sites some growth outside the basin under power constraints. The report's "2.7-fold" growth wording equals the
share ratio, while its results imply load-based growth; to be confirmed with CO-OP.

### Stage W-B: replication with the rule-based simulator
`prrism_lite.py` matches 2030 closely (minimum combined Little Seneca and Jennings Randolph storage 9.5 against 9.7 BG at
low demand, 3.8 against 3.5 at high) but is too optimistic for 2045 and 2050 at high demand (2.0-2.6 BG against 0 and
deficits). Results are highly sensitive to two details the report does not specify: the nine-day recession forecast
(Ahmed et al., 2015) and the Occoquan and Patuxent load-shift rules. No single setting fits all nine scenarios.

### Stage W-C: the cooling trade-off
Using the study's water use per power by cooling scenario and stated assumptions (air cooling adds 8% power on average,
15% at peak; marginal gas combined cycle at 200 gallons and 0.4 tons CO2 per MWh): under the study's growth path, moving
from 90% to 30% water-cooled facilities by 2050 cuts peak-day site water from about 145 to 58 MGD, adds about 1,300 MW
average and 2,500 MW peak electricity, about 6 MGD of power-plant water and about 4.7 million tons of CO2 a year. In the
drought of record it moves minimum storage between about 2.5 and 3.0 BG.

### The draft
`draft/Potomac_DC_Power_Water_Draft.md` presents W-A, W-B and W-C, with seven questions for CO-OP (recession equation,
load-shift rules and storage triggers, quarry operations, natural inflow series, the Jennings Randolph water quality
account and Savage Reservoir, the growth wording, and interest in a coupled analysis). It still uses the standalone
simulator for W-B; Section 7 below describes the replacement.

### The Techgraph version of the system
`tg_wma.py` represents the system with existing primitives: inflow passing through Jennings Randolph and water released
from its storage are separate substances, so only releases carry the nine-day delay; storage is split into upper and
lower zones with values that express operating priorities; each day a plan on forecast flows is followed by a
realization on actual flows with committed decisions fixed.

Convergence test (myopic optimization against the rule-based simulation), findings so far:
1. With free priorities, the optimization leans on the Occoquan and Patuxent more than the rules allow.
2. Applying the rules on forecast flows rather than actual flows changes the load shifts; with matched information they
   agree (Occoquan 31.2 against 31.6 BG, Patuxent 15.5 against 15.4 over the 1930 drought).
3. With matched rules and information, the stressed case converges (2045 high: 2.58 against 2.64 BG).
4. The remaining gap (2030 medium: 11.5 against 5.5 BG) is explained: Techgraph releases from Jennings Randolph almost
   exactly its upper zone (5.1 BG); after that, the higher value of the lower zone makes it plan Little Seneca for
   distant forecast gaps, which never materialize because the recession forecast is pessimistic. The simulation has no
   zones and keeps releasing (11.1 BG over 136 days). Both avoid deficits.

The background scan (`results/tg_scan.json`) is partial and its rule-matched entries still use zoned values.
Preliminary horizon results for 2030 low demand: 13.3 BG minimum storage with ten-day forecasts, 16.6 with ten days of
actual flows, no further gain at 30 days.

## 7. Next steps

**4 October follow-up:** The controlled single-priority comparison is documented in
`cases/potomac_water/CONVERGENCE.md`, with the runner `check_convergence.py` and results in
`results/convergence_single_zone.json`. This enables `same_info=True` as well as equal JR storage
values. All 18 runs completed: minimum-storage differences range from -0.951 to +0.588 BG,
with no deficit days in either model. Cross-scenario convergence is not established. Structural differences remain,
including release/transit accounting and the missing Vulcan quarry in Techgraph; equality of
minimum storage is not enough to establish convergence. Resolve those differences before treating
the full horizon scan as a controlled comparison of operating priorities and foresight.

**Water case, in order:**
1. Rerun the rule-matched variant with Jennings Randolph as a single zone (equal upper and lower values) and confirm
   convergence across all nine historic scenarios.
2. Rerun `run_tg_scan.py` in full: rule-matched, optimized priorities, and horizons from ten-day forecasts to 90 days
   of actual flows.
3. Update the draft so W-B uses the Techgraph version, with the convergence result and the horizon scan (the value of
   foresight and of operating priorities); keep `prrism_lite.py` as a cross-check.
4. After CO-OP's answers: the recession equation, load-shift rules and inflow series; then the altered-flow scenarios.
5. Couple the water system with the Virginia power model: cooling choice, siting under water and power constraints, and
   correlated heat and drought.

**Framework:**
1. Data adapters for real geographies (counties, utility territories, watersheds) on the spatial layer.
2. Spatial fields and stress events defined over atoms.
3. Petition and approval steps for process rules; endogenous rules (later).
4. The curated world builder and the stylized two-basin water world from the existing spec, as a hand-checkable
   regression test for water.
5. GenX Stage C (mechanism attribution); the static-forecast-equals-myopic test in the v4 campaigns.

**Virginia case:** only if publication resumes: test the cost-ratio divergence against alternative financing
assumptions, the plan's distributed-resource growth, and a load path matched to the plan's.

## 8. How to run

```
export TECHGRAPH_BACKEND=scipy
cd cases/virginia_dc && python3 check_reference.py            # must print PASS
python3 runs20.py && python3 plan_numbers.py                     # version 10 pathways and numbers
cd ../potomac_water && python3 run_tg_scan.py                    # water scan, about 25-40 minutes
```

## 9. Lessons and pitfalls

- **Replicate before extending.** Replicating an official model under its published assumptions was the most
  informative validation in both cases. Most divergences came from assumptions the documents do not spell out.
- **Single-solve consistency.** Three times, a rule enforced in planning was violated in a separate operating solve.
  Re-imposing a quantity rule as a price in a separate solve is inconsistent or knife-edge. Report quantities from the
  solve in which all rules hold.
- **Adding a constraint cannot lower the cost of a single solve.** Report the size, timing and causes of the increase,
  and separate resource costs from transfers.
- **Myopic optimization reproduces rules only with the same information and the same priorities.** Forecast versus
  actual inputs to a rule, and the ordering of storage values, each changed results by billions of gallons.
- **Do not name scripts after standard library modules.** A script called `numbers.py` shadowed Python's module and
  silently broke three experiment sets.
- **`pkill -f pattern` can kill its own shell** when the pattern appears in the command line; kill by process id.
- **The sandbox network is restricted.** USGS and state websites were not reachable; data came through uploads.
- **Escape prices and accounting.** A large escape price on a cap distorts dispatch and costs; decide explicitly
  whether a shortfall is a purchase (a transfer) or non-compliance (reported, not paid).

## 10. Not included

Raw inputs used once and not redistributable here: hourly Dominion load (`DOM_hourly.csv`), the GenX repository and
Julia environment, the ICPRB report and the Energy Plan PDF (both public from their publishers). Large experiment outputs
(`runs*.json`) are regenerated by the scripts.
