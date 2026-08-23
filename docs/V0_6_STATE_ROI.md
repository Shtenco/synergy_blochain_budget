# SINERGY Blockchain Budget V0.6 — State ROI Simulator

V0.6 adds a deterministic/Monte-Carlo macroeconomic simulator for the synthetic public-finance universe created in V0.5.

The model compares the same synthetic economy in two regimes:

```text
BASELINE current digital controls
          vs
SINERGY blockchain budget + procurement + continuous audit
```

It does **not** assume that blockchain removes all losses. Each category is modeled as:

```text
exposure × latent loss rate × preventable share × prevention probability
```

The incremental state benefit is only:

```text
prevented_with_blockchain - prevented_in_baseline
```

Therefore a loss already prevented by existing Treasury/EIS controls is not counted again.

## Safety / interpretation

All amounts and probabilities in this module are synthetic policy assumptions. They are **not empirical claims about actual Russian corruption, losses, or savings**.

Default macro envelope is a scenario parameter:

- annual non-overlapping public-budget envelope: `62 trillion RUB`;
- annual procurement envelope: `13.6 trillion RUB`;
- 1 federal contour;
- 89 synthetic regional contours;
- 20 synthetic municipalities per region (`1780` municipal units);
- total modeled units: `1870`.

Synthetic regions are named `REGION_01 ... REGION_89`; the simulator intentionally does not assign synthetic risk scores to real named regions.

## Loss / inefficiency categories

V0.6 explicitly separates:

1. procurement overpricing;
2. cartel/coordinated procurement patterns;
3. procurement splitting / bypass of competition;
4. false/incomplete acceptance followed by payment;
5. unauthorized diversion / fictitious payment recipient;
6. duplicate, erroneous or unsupported payments;
7. KBK / transfer / inter-system reconciliation errors;
8. late-payment financing cost;
9. manual reconciliation, audit and administrative overhead.

Each category has triangular uncertainty ranges for latent loss rate, preventable share, baseline prevention and blockchain prevention, plus separate federal/regional/municipal bias coefficients.

## Cost model

Default real-term cost assumptions:

```text
platform build               55 bn RUB
integration / rollout        65 bn RUB
annual OPEX                  24 bn RUB
annual security / audit       4 bn RUB
10-year horizon
8% real discount rate
1% real budget growth
```

Rollout benefits ramp:

```text
year 1  22%
year 2  45%
year 3  68%
year 4  84%
year 5  94%
year 6+ 100%
```

## Base-mode result

At triangular modal assumptions:

```text
full-adoption incremental benefit   ~62.41 bn RUB/year
10-year NPV                         ~28.82 bn RUB
benefit/cost ratio                  ~1.094
IRR                                 ~11.52%
payback                             ~6.57 years
```

The NPV=0 break-even full-adoption benefit is approximately `57.03 bn RUB/year`, equal to about `0.09198%` of the synthetic 62 tn budget envelope or `0.41933%` of the 13.6 tn procurement envelope.

That is the central V0.6 result: under the default cost/ramp/discount assumptions, the system needs roughly one tenth of one percent of the modeled total budget envelope in incremental annual benefit to pay for itself over ten years.

## Benefit decomposition

Approximate modal incremental annual effect:

```text
overpricing                    18.69 bn RUB
cartel patterns                 9.12 bn RUB
duplicate/unsupported payments 10.19 bn RUB
KBK/transfer errors             5.93 bn RUB
manual reconciliation           5.82 bn RUB
late payment                    4.04 bn RUB
procurement splitting           3.98 bn RUB
false acceptance                2.62 bn RUB
fraud/diversion                 2.01 bn RUB
```

These are synthetic scenario outputs, not measured actual savings.

## Layer decomposition

```text
federal     ~25.38 bn RUB/year
regional    ~24.13 bn RUB/year
municipal   ~12.90 bn RUB/year
```

The municipal layer has a higher modeled benefit rate per budget RUB because the default risk and manual-reconciliation coefficients are intentionally more demanding there. This is an adjustable assumption.

## Monte Carlo

Default CLI uses 5000 runs and samples loss/prevention parameters plus implementation cost and benefit-realization uncertainty.

Typical default-seed result:

```text
annual full-adoption benefit
P10  ~49.2 bn RUB
P50  ~60.8 bn RUB
P90  ~74.7 bn RUB

10-year NPV
P10  ~-69.3 bn RUB
P50  ~ +5.6 bn RUB
P90  ~+87.8 bn RUB

probability(NPV > 0) ~54%
```

The base case is therefore economically plausible but deliberately not guaranteed.

## ROI sensitivity curve

V0.6 exports a grid over benefit scale `{0.50,0.75,1.00,1.25,1.50,2.00}` and cost scale `{0.75,1.00,1.25,1.50}`.

At unchanged costs:

```text
benefit 0.50× → NPV ≈ -138.3 bn RUB
benefit 0.75× → NPV ≈  -54.7 bn RUB
benefit 1.00× → NPV ≈  +28.8 bn RUB
benefit 1.25× → NPV ≈ +112.4 bn RUB
benefit 1.50× → NPV ≈ +195.9 bn RUB
benefit 2.00× → NPV ≈ +363.0 bn RUB
```

This is the state ROI curve: implementation cost is explicit, avoided-loss effectiveness is explicit, and no category is presented as guaranteed real-world recovery.

## CLI

```bash
synergy-budget-roi \
  --regions 89 \
  --municipalities-per-region 20 \
  --total-budget-rub 62000000000000 \
  --procurement-rub 13600000000000 \
  --horizon-years 10 \
  --runs 5000 \
  --seed 20260823 \
  --output data/mock/roi-v0.6
```

Output:

```text
STATE_ROI_RESULT.json
annual_cashflows.csv
benefit_by_category.csv
benefit_by_layer.csv
regions.csv
sensitivity.csv
```

## Key invariants

1. No claim that synthetic loss rates describe actual Russia.
2. Same economic exposure is compared before/after; blockchain does not create fake additional spending.
3. Existing baseline prevention is subtracted before benefit is counted.
4. Incremental benefit cannot exceed modeled latent loss.
5. Procurement for every synthetic unit is constrained below its modeled budget.
6. Named real regions are not assigned synthetic corruption/risk scores.
7. NPV/IRR/payback include rollout and operating costs.
8. Results are deterministic for a fixed seed.

## Next step

V0.7 should replace scenario priors with empirical calibration as real Treasury/EIS coverage is backfilled:

```text
real Treasury/EIS coverage
        ↓
empirical baseline rates
        ↓
calibrated detection uplift
        ↓
posterior ROI distribution
```

Until then V0.6 is a stress-test and policy laboratory, not an empirical fiscal forecast.
