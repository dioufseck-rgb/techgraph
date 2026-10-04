# Techgraph: model review against the theory, and assumptions that limit realism

29 September 2026

## 1. Scope and summary

This review compares the code of the demand-sweep v3 checkpoint (the frozen stateful-v2 core plus the demand coordinates) with two texts. The first is the revised paper, "Mismatches, Modules and Entrenchment in Technological Change". The second is the conceptual framework v0.2. I read the world generator, recipe search, stateful adapter, capability layer and rolling-horizon optimizer. I also ran several checks on the 480 main demand histories in the resolved cohort, using periods 8–67. No campaign was rerun.

The main conclusion is as follows. The model implements its declared primitives carefully, and the paper states most of its limits honestly. However, several assumptions do more than limit generality. They plausibly produce some of the reported findings. Four matter most. First, the planner's static forecast leaves storage almost unused, and it probably drives the temporal-ordering result. Second, fulfillment losses under growth and pulses are almost entirely set by the raw-supply margin, not by technology. Third, operation has no switching cost and the catalog is full of near-duplicate designs, so part of the measured churn reflects near-ties. Fourth, linear divisible costs and dedicated per-form transport remove the economies of scale and shared infrastructure through which much real entrenchment and geography operate.

These concerns do not invalidate the audited findings as statements about the model. They do change which findings can reasonably be read as statements about technological change. Section 6 proposes diagnostics that would separate the two readings. Most of them reuse existing worlds.

## 2. What the model represents faithfully

Several parts of the theory are well implemented. Material states are form–location pairs, and the balance equations are audited. Processes are genuine hyperedges with joint inputs and coproducts. Equipment is tracked by vintage, with sunk capital, age-dependent operating cost and fractional retirement. Construction leads create real work in progress that can be canceled. Documented knowledge is kept separate from readiness to build or operate. Proposal generation is blind to the realized outcome, which matches Campbell's separation of variation from selection. The experiments prescribe external conditions and never prescribe technological responses.

The paper's own limits section already names the small worlds, the single planner, fixed search effort, free archiving, weak capability constraints and the factorization sensitivity of summed capacity. This review does not repeat those points except where the code or the data add something new.

## 3. Gaps between the theory and the model

The table lists places where the implemented model departs from the framework it is meant to study. Some are deliberate simplifications. A few contradict explicit commitments in v0.2.

| Theory commitment (v0.2 or paper) | Implementation | Consequence |
|---|---|---|
| Two clocks: operational time within a decision epoch, and decision time between epochs (§3.1) | One clock. Each period is a single steady-state operating snapshot. Storage carries material only between decision periods. | Short-cycle temporal mismatches, which storage usually resolves, cannot occur. Storage becomes a strategic buffer across investment periods. |
| The feasibility space is a curated catalog of recognizable technology classes, "not an arbitrary generator of edges" (§3.3) | Random recipes over abstract forms, with generated intermediates that have no physical referent | The paper now embraces this. The departure should be stated as a revision of the theory, not left implicit. |
| Ports carry standards, versions and behavioral contracts; adapters convert between them (§3.6) | Ports carry only form, location and coefficient | Any producer of a form substitutes perfectly for any other. Dependence on an interface reduces to dependence on a material form. |
| Transition plans include interruption, adapters, dependent reconstruction and service-continuity costs, under period budgets (§6.3) | Operating routes change at zero cost. There is no budget or finance constraint. | Migration is cheaper than the theory assumes, which weakens entrenchment. |
| Several transparent policies compared, with a perfect-foresight bound (§6.4) | One policy: a four-period rolling horizon with static expectations | Every finding is conditional on one forecast rule. Section 4.2 shows this matters. |
| Invention directed by opportunity, proximity and unresolved need, compared with random emergence (§6.5, §10) | Undirected search with fixed effort, and parents drawn uniformly from the whole archive | Consistent with blind variation, but the comparison the theory calls for is missing. |
| Private and wider consequences kept in separate ledgers (§5) | Disposal is charged privately. No externality ledger is active in the campaigns. | The externality-shock experiments cannot yet be posed. |
| Maturity, support and withdrawal of designs (§3.7, §6.1) | Not active in the campaigns | Obsolescence arises only from equipment lifetimes. |
| Entrenchment measured by functional exclusion (§7.1; paper §2.5) | Not run | The paper acknowledges this. |

## 4. Assumptions that limit the realism of findings

Each subsection states what the code does, why it matters, and which findings it affects. Where I could test a concern against the archived histories, I report the result.

### 4.1 Static expectations leave storage almost unused

The planner assumes that current demand persists over its four-period window. It therefore never sees a future need for material, and it has little reason to store ahead of a rise. Storage enters mainly to absorb imbalances that are already present.

The data confirm this. Aggregate inventory capacity is large, between about 7 and 29 periods of baseline demand across worlds. Yet the mean closing stock is only 0.08 to 0.23 periods of demand in every treatment. Withdrawals supply 1.4% of deliveries under constant demand, 5.1% under the 16-period cycle and 8.9% under the weakly persistent irregular sequence.

This matters for the theory. Storage is one of van Wyk's three functions, and temporal mismatch is one of the framework's three mismatch types. In the current campaigns, the temporal branch is represented mostly by shortfall and by spare capacity, not by storage. The inventory finding in paper §5.4 should be read in that light. Its median service gain of about one percentage point reflects a storage function that the planner barely uses.

### 4.2 The ordering result may be mainly a forecasting result

Paper §6.1 reports that persistent ordering improves fulfillment in all 24 worlds, relative to the same demand levels in weakly persistent order. The paper notes that this holds "under one fixed planning rule". The concern is stronger than that caveat suggests.

A static forecast is a random-walk forecast. Its errors are small when demand is persistent and large when demand changes from period to period. Construction leads of up to two periods make forecast errors costly, and storage does not compensate (4.1). So persistent demand should help this planner almost by construction. Two observations support that reading. Worlds with a supply margin above 1.4 could meet peak demand from flow alone, yet they still lose 2–6% of service under the cycles. And under the cycles and irregular sequences, only 34–59% of unmet demand occurs when raw supply is saturated. The rest arises when capacity or its timing, not the resource, is the limit.

The finding may still express something real. Real organizations often forecast adaptively, and persistence genuinely helps them. But the result currently shows how a myopic forecaster interacts with demand ordering. It does not yet show how technological structure does. A replay under perfect foresight, or under a forecast that knows the persistence parameter, would separate these readings. If the effect largely disappears, the finding belongs to decision rules, not to technology.

### 4.3 Service shortfalls are mostly set by the raw-supply margin

All service ultimately comes from a single raw form, F0. Generated processes conserve mass, and there are no other inputs such as energy or labor. No technology can therefore deliver more service than the raw supply allows. Supply at each site is a fixed rate, and the total supply margin is sampled between 0.95 and 1.65 times initial demand.

This dominates the fulfillment results for scale treatments. Under growth40, 98% of unmet demand occurs when raw supply is fully used. Under pulse40 the figure is 93%. Fulfillment rises almost monotonically with the supply margin. It ranges from 0.79 to 0.94 when the margin is below 1.21, and it exceeds 0.99 when the margin is above 1.45. Under constant demand, only world 318 has any shortfall, and its margin is 0.98.

The shortfall penalty adds to this effect. The median direct cost per delivered unit is 4.7 synthetic units, so a penalty of 100 is about 21 times the cost of service. Demand is therefore almost a hard constraint. Shortfall occurs mainly when service is physically impossible.

Two consequences follow. First, fulfillment comparisons across scale treatments mostly measure resource scarcity, not technological response. Second, the model cannot represent technologies that relieve a resource mismatch by using less resource, by substituting another resource, or by expanding supply. The theory lists changing raw resources as a central question, yet the resource side is fixed and nearly uniform in kind.

### 4.4 Frictionless operation and near-duplicate designs inflate churn

Operating routes can change every period at no cost. Mutation also produces many close variants: costs are perturbed by a lognormal factor with a standard deviation of 0.2 in logs. A linear program with many near-tied alternatives will switch among them in response to small differences, such as aging costs or a new marginally cheaper variant.

The data are consistent with this. Under constant demand, the substantial process set changes in about 20% of periods. The median change shifts only 2.7% of activity, and 23% of changes shift less than 1%. Under cycles and irregular demand, changes are larger. Their median shift is 6–10% of activity, and fewer than 2% of changes are under 1%. So the demand-driven churn findings look substantive, but the baseline churn against which they are measured contains many small reshuffles.

Real operations carry switching costs, qualification and ramp-up time, and contractual commitments. These produce hysteresis, which the model lacks. Several findings compare churn across conditions: preparation delays (§5.3), inventory (§5.4), cycles (§6.2), decline (§6.3) and returns (§6.4). They should be checked under a modest switching or ramping cost, and reported with activity-weighted change alongside set change.

### 4.5 Linear divisible costs remove economies of scale

Generated processes have no fixed or lumpy cost. Capital, operating and variable costs are all linear in capacity or activity, and capacity is fully divisible. The only integer decisions concern capability readiness.

This removes a mechanism that the literature treats as central to technological change. Arthur's increasing returns, hub formation, dominant designs and bow-tie architectures all depend on some advantage of concentration or reuse. In the current model, concentrating production has no advantage beyond cost differences between sites. Sharing an intermediate between services creates no saving. The theory's hourglass hypothesis (§7.3) and its modularity hypothesis (§7.4) cannot be tested properly without such economies. Linear costs also make each planning problem prefer the cheapest route outright, so adoption is abrupt rather than gradual. Vintage turnover provides some gradualism, but not the heterogeneity that produces diffusion curves.

### 4.6 Transport is dedicated, per-form and uncongested

Every initial form has its own transport process on each spatial edge, in each direction. Cost is linear in capacity and scales with one plus distance. There is no shared corridor, no congestion, no economy of density and no transit time within a period. Generated intermediate forms cannot be transported at all.

Under these assumptions, the geography results in paper §7 are close to accounting identities. Moving demand changes how many hops each service travels. Transport capacity is then summed per hop and per form. The finding that pure transport has the same sign as total capacity change in 23 of 24 worlds follows largely from this structure. The explanation of worlds 309, 322 and 306 remains correct and useful. It shows how aggregate measures can hide rearrangement. But it describes the model's bookkeeping more than it describes real spatial systems. In real networks, services A and B would often share infrastructure, so their changes would partly net out on the same link. Congestion and economies of density would also make capacity respond nonlinearly to rerouted flows.

This matters for the planned geography case study. The Amazon regionalization comparison in the research memorandum rests on shared fulfillment and transport networks, which is exactly what the model omits. The case study should state this difference directly.

### 4.7 Search is uniform over the archive, and costs follow a random walk

Parents for new designs are drawn uniformly from all documented processes. In the demand histories, only a median 7.3% of generated designs are ever used. A uniformly drawn generated parent is therefore unused with a probability of roughly 0.9. The finding that operated designs often have unused parents (paper §5.1) is thus close to what a structural null would predict. The replay experiment is the more informative part of that section, because it measures the economic contribution of the channel. The descriptive count should be compared with an explicit null before it is presented as a finding.

Real invention tends to build on what is in use, through attention, experience and learning by doing. The model has none of these. Design costs change only through symmetric random mutation within fixed bounds, from 0.25 to 4 times the original anchor. Apparent cost progress then comes from selecting the cheapest of many draws. Its pace depends on the number of attempts, not on use or cumulative production. Learning curves, which the theory treats as a core dynamic (§6.1), are absent.

### 4.8 Capabilities are cheap, arbitrary, and mislocated after relocation

Readiness costs between 0.3 and 2.5 synthetic units per capability. That is small compared with the service at stake. The median history makes 40 acquisitions, and installed equipment is blocked by missing readiness in at most three periods of any history. Readiness is therefore a routine renewal fee, not a constraint. The paper reports this. The assignment of forms to two capability domains by the parity of their index is also arbitrary, and it carries no technological meaning.

I also found an implementation defect. A generated design inherits the union of its parents' capability requirements, whatever the operator. For relocation, this means the new design requires readiness at the origin site, not at its new location. For example, in world 300, design G_083_00 was relocated from L0 to L1, yet it still requires skill_L0_0 and skill_L0_1. This contradicts the stated semantics of local technical readiness. Transferring a technology to a new site therefore never requires building capability there. Given how cheap capabilities are, the numerical impact is probably small. But the defect bears directly on the world 122 example in paper §5.1, whose operated descendant is a relocation. The defect should be fixed before any capability experiment is run.

### 4.9 Entrenchment can only operate through material forms

Ports identify only a form and a location. A downstream process cannot depend on a particular upstream implementation, standard or interface. It depends only on the availability of a form. Together with frictionless rerouting and free retirement, this leaves three sources of persistence: sunk capital, construction leads and readiness. Generative entrenchment in Wimsatt's sense requires that later structures come to depend on an earlier element, so that removing it is costly. That can happen here only when a generated intermediate form has a single producer. The planned functional-exclusion experiments will therefore measure a narrow form of entrenchment unless interface contracts or adaptation costs are introduced first.

### 4.10 Smaller points

The worlds have three or four sites, six forms and two services. Topological phenomena, such as hubs and bottleneck migration, need larger and more varied networks.

Every world starts from an optimum for its current demand. Real transitions usually start from legacy systems built for past conditions. A model that starts at an optimum understates inherited mismatch.

Demand is exogenous and has no price response. Requirements never grow from new capabilities. The paper states both points.

Period length is ambiguous. Lifetimes of 4–9 periods and leads of 0–2 periods suggest years. A single operating snapshot per period and storage between periods suggest much shorter periods. Any real-world interpretation needs one consistent reading.

## 5. Exposure of the main findings

The table summarizes how strongly each assumption bears on each finding. "High" means the assumption may produce much of the effect. "Moderate" means it changes magnitude or interpretation. "Low" means the finding is probably robust to it.

| Finding (paper section) | Main exposure | Level |
|---|---|---|
| Unused knowledge contributes to later operation (§5.1) | Uniform parent selection; free archive; relocation defect | High for the descriptive count; moderate for the replay effect |
| Constant conditions do not imply a constant configuration (§5.2) | No switching cost; near-duplicate variants | Moderate |
| Preparation delays increase reconfiguration (§5.3) | No switching cost; static forecast | Moderate |
| Inventory improves service but increases churn (§5.4) | Static forecast leaves storage idle; no switching cost | Moderate to high |
| Optional invention can worsen a bounded policy (§5.5) | Single myopic policy | Low as a statement about bounded policies |
| Process return need not mean rebuilding (§5.6) | Free retirement; no restart cost | Moderate |
| Temporal ordering matters beyond variance (§6.1) | Static forecast with construction leads | High |
| Cycles induce churn without capacity expansion (§6.2) | Raw-supply cap; static forecast; no switching cost | Moderate |
| Decline and service mix produce different responses (§6.3) | Linear costs; per-form transport | Moderate |
| Return of demand does not ensure return of state (§6.4) | No switching cost; vintage accounting | Low to moderate |
| Opposite geographical capacity effects (§7) | Per-form dedicated transport; summed capacity | High for magnitudes; low for the cancellation argument |
| Factorization changes summed capacity (§7.3) | Measurement definition | Low; this is already a measurement finding |

## 6. Recommendations

The steps below are ordered by how much they clarify existing results for the least effort. The first group needs no model changes. These are new diagnostic runs on existing worlds, not reruns to restore the project.

### 6.1 Diagnostics on existing worlds

First, replay the irregular0 and irregular85 pair under perfect foresight and under a forecast that knows the persistence parameter. If the ordering effect largely disappears, the finding should be restated as a finding about myopic decision rules.

Second, rerun the constant, cycle16 and irregular treatments with a small switching or ramping cost on changes in process activity. Report the change in measured churn. In addition, report activity-weighted configuration change beside set change in all churn findings.

Third, compute a null expectation for unused ancestry. Under uniform parent selection, the null is the probability that an operated design with a generated parent has an unused parent, given the observed usage rate. Report the observed count against it.

Fourth, add the supply margin as a covariate in every fulfillment comparison. Alternatively, restrict the scale treatments to worlds whose margin exceeds peak demand. This separates resource scarcity from technological response.

Fifth, fix the relocation requirement so that relocated designs require readiness at their destination. Confirm that the world 122 example is unchanged.

### 6.2 Model changes that most improve realism

The following changes are listed in order of priority.

1. Introduce two clocks. Each decision period should contain several operating sub-periods with a demand profile. This would give storage a genuine temporal-mismatch role and bring the model into line with v0.2.
2. Add economies of scale through fixed or lumpy capacity costs. This is a prerequisite for studying hub formation, dominant designs, modularity benefits and the complementarity trap under realistic incentives.
3. Replace dedicated per-form transport with shared corridors. A link would carry any form up to a joint capacity, possibly with congestion. The geography findings should then be re-examined.
4. Make search attention depend on use. Parent selection could be weighted toward operated or recently operated designs, with learning-by-doing cost reductions for used designs. Retain uniform search as a comparison arm, as v0.2 proposes.
5. Diversify resources. Use more than one raw form, place different resources at different sites, and let resource availability change over time. This lets the model address the theory's questions about changing resources.
6. Add interface contracts and adaptation costs to ports before running the functional-exclusion experiments. Otherwise entrenchment can be measured only at the level of material forms.
7. Calibrate capability costs against service value, so that readiness can constrain decisions. Base capability domains on something meaningful, such as lineage families.
8. Compare several decision policies on the same worlds. The candidates are the static-forecast rolling horizon, an adaptive forecaster, a staged-migration rule and a perfect-foresight bound.

### 6.3 Implications for the planned geography case study

The geography case study can proceed with the existing traces. It should explain that the route mechanism in worlds 309, 322 and 306 is exact within the model because transport is dedicated per form and linear. It should present the real-world comparison as an analogy about offsetting flows and aggregate measures, not as evidence that real networks respond the same way. The strongest general lesson from the case is the measurement point. Aggregate capacity can hide large rearrangements, and that lesson does not depend on the transport assumptions.

## Appendix: checks run for this review

All checks used the resolved demand cohort: 480 main histories of 72 periods, restricted to periods 8–67. Unmet demand was counted as occurring at raw-supply saturation when resource use reached at least 99.9% of the world's total input rate. Stock measures were normalized by each world's baseline demand. Configuration changes used the analysis field for substantial process-set change, and the activity shift used the per-period total-variation distance of the activity mix. The relocation check generated proposals for world 300 with the campaign's search seed and applied the campaign's candidate adapter.
