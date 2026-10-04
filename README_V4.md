# Techgraph v4: opt-in realism mechanisms

This source tree extends the frozen demand-sweep v3 code. Every change is opt-in. With default settings the code reproduces the archived v3 histories: world 300 under constant demand gives the archived all-in objective exactly, and per-design throughputs and builds agree to within 1.3e-13. The test `tests/test_v4_realism.py::test_defaults_reproduce_frozen_v3_history` guards this.

## How to use

A demand-campaign spec takes an optional `realism` dictionary, whose keys are the fields of `techgraph.realism.RealismConfig`. For example:

```python
from run_demand_sweep import execute
execute(dict(seed=301, treatment='cycle16', epochs=72, horizon=4,
             realism=dict(bins=4, intra_amplitude=.3, corridors=True, switching_cost=.5, forecast='ar1')))
```

`run_v4.py specs.json outdir` runs a list of specs sequentially and resumably, in the v3 trace format. `analyze_v4.py` computes the diagnostics with the unchanged v3 metric code (`analyze_demand_sweep.extended_extract`).

## Mechanisms

| Field | Default | What it does | Where |
|---|---|---|---|
| `bins`, `intra_amplitude` | 1, 0 | Two clocks. Each decision period has several operating bins with a known, mean-preserving demand profile. Stocks are chronological within the period, so storage can resolve within-period mismatch. | `realism.apply_bins` |
| `lump_share`, `lump_reference`, `lump_scope` | 0, 1, all | Economies of scale through the core's lump binary. Total capital is unchanged at the reference capacity. `infrastructure` restricts lumps to corridors, which keeps windows tractable. Lump runs use a declared MIP gap of 0.2% and a 120 s window limit. | `realism.apply_lumps`, `backend.MIP_GAP` |
| `corridors`, `corridor_share`, `congestion_threshold`, `congestion_cost` | off | Shared transport. One corridor per edge direction carries a share of transport capital; all forms share its capacity in every bin. Flow above the threshold share pays a congestion charge. | `realism.add_corridors`, `dynamic._add_realism_terms` |
| `switching_cost` | 0 | Operating friction per unit of absolute change in a process's per-period throughput. Not charged in the first period of a history. | `dynamic._add_realism_terms`, `accounting._realism_replay` |
| `forecast` | none | `oracle` (window sees realized demand), `ar1` (fitted on the observed log path), `holt` (linear smoothing). `none` keeps the v3 static rule. | `realism.forecast_trajectory`, `vsr.run_vsr` |
| `use_bias` | 0 | Parent choice weighted 1 + use_bias for designs operated in the previous period. | `generative.RecipeSearch` |
| `learning_rate`, `learning_reference` | 0, 4 | Learning by doing: new-build cost multiplier (1 + cumulative throughput / q_ref)^(-b), floored at 0.3; descendants inherit the parent's multiplier. b = 0.234 is an 85% progress ratio. | `vsr.run_vsr` |
| `raw_forms` | 1 | Several raw resources; extra raw forms occur at random subsets of sites. The supply margin applies to each raw form. | `generative.make_generative_world`, `stateful.make_stateful_world` |
| treatment `resource_shift50` | — | Raw supply at the reference site declines to half over periods 8–55. | `demand_sweep.prepare` |
| `variant_share`, `adapter_cost` | 0 | Interface variants: a producer is copied to make an incompatible variant form (with cost drift), with adapters in both directions; consumers can later adopt the variant. | `generative.RecipeSearch._variant` |
| `capability_cost_scale`, `capability_domains` | 1, parity | Calibrated readiness costs; `function` domains separate processing from logistics. | `stateful.make_stateful_world` |
| `relocation_fix` | off | Relocated designs require readiness at their destination, not their origin. | `stateful.StatefulCandidates._site` |

## Verification

All existing audits apply unchanged. The independent cost ledger reprices switching and congestion from saved quantities. The flow audit checks resource use against the recorded effective limit and checks that this limit never exceeds the declared maximum.

The existing test suite gives the same result as the unmodified v3 source in this environment: 678 passed, 3 failed and 3 collection errors. All six failures come from scripts not included in the checkpoint (`run_network_vsr_probe`, `run_discovery_pilot`, `run_demand_sensitivity`, `stateful_replay`). The eight new tests pass.

## Not implemented

A full-horizon perfect-foresight benchmark and a staged-migration decision rule are not implemented. The `oracle` forecast is a rolling four-period oracle, not a full-horizon bound.
