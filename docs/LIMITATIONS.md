# FitPulse limitations

Everything below is disclosed in the product itself (Methodology page, *Source & methodology*
panels, capability lists and report methodology notes), not only in this document.

---

## 1. Scope exclusions

- **Subscription renewal is out of scope.** Renewal analysis requires renewal-event data.
  None of the supported sources contain it, so no renewal metric exists anywhere in FitPulse.
- **Revenue is out of scope** for the same reason: no payment or revenue field exists.
- **Churn is not predicted.** FitPulse analyses the relationship between engagement and the
  real churn label. It does not train or present a predictive churn model.
- **No causal claims.** All findings are associations observed in the loaded data.

## 2. Reference activity dataset

*Daily Gym Attendance and Workout Activity Dataset*

- **No repeatable member key.** `member_id` has 2,600 distinct values across 2,600 rows: it
  is a record sequence, not a member identity. Member-level event history — and therefore
  real per-member streaks — cannot be derived from this file. FitPulse preserves the value as
  `source_member_ref`, keeps the canonical `member_id` null, and reports streak analysis as
  unavailable for this source.
- **Nominal duration and calories.** Rows marked *Absent* still carry non-zero duration and
  calories whose distribution matches *Present* rows. Duration and calories are therefore
  scheduled values, not confirmed workout output. FitPulse keeps both a raw and an
  attendance-gated ("confirmed") measure and reports the difference rather than hiding it.
- **No outcome fields.** The file contains no churn, membership status, join date or payment
  information, so it cannot produce retention outcomes on its own.
- **Single calendar year and no member continuity**, so it supports platform-level trend and
  seasonality analysis only.

## 3. Reference membership dataset

*Churn Prediction Gym Members Dataset*

- **Direct identifiers are present** (`Name`, `Address`, `Phone_Number`). They are dropped
  during cleaning and are never written to the curated layer, the SQLite warehouse, the
  artifacts or the report.
- **`Last_Visit_Date` is weakly related to the churn label.** Values are spread over several
  years and show no meaningful association with churn, so date-derived recency behaves close
  to noise. FitPulse reports this instead of smoothing it over.
- **No subscription renewal events**, so renewal-rate analysis remains out of scope.
- **Publisher aggregates only.** `Avg_Workout_Duration_Min` and `Avg_Calories_Burned` are
  member-level averages; raw per-workout events are not provided for these members, so
  member-level activity depends on the documented synthetic calendar (§4).

## 4. Synthetic data disclosure

Where member-level dates are required, FitPulse generates a deterministic activity calendar
from each member's *real* visit rate (see `docs/METHODOLOGY.md` §6). Consequences:

- Streak, consistency and calendar-derived recency columns are **illustrative of the
  method**, not observed history, and are labelled *Synthetic calendar* throughout.
- Real and synthetic events are stored in separate tables (`fact_workout` vs
  `fact_workout_synthetic`) and can never be silently combined.
- The synthetic layer never changes the churn outcome, the visit rate, duration or calories.
- The share of synthetic events in the activity picture is shown on the Overview hero so it
  cannot be overlooked.

## 5. Integration limitations

- The two reference datasets **do not share a legitimate member identifier**. No join is
  performed; any apparent overlap of raw integers is coincidental (the key analysis reports
  the overlap count and the demographic agreement, which is near chance).
- Consequently there is **no validated cross-source member-level retention analysis** for the
  reference pair. Independent activity analysis, independent membership analysis, and the
  labelled synthetic bridge are the available options.
- When a user uploads two datasets that *do* share a validated key, the same integrity rules
  apply: the join is still not performed automatically, and the key analysis states whether
  one would be defensible.

## 6. Methodological limits

- **Engagement-score weights** are product-design assumptions, not empirically validated
  weights. Changing them changes segment membership.
- **Segment thresholds** are configuration, not statistically optimised cut points.
- **Alert thresholds** are business configuration, not model-derived limits.
- Small populations produce wide uncertainty: rates are shown with Wilson 95% intervals
  where the population is small, and the interval is quoted beside the headline figure.
- Median imputation is applied to some numeric member measures; every imputed value carries
  an explicit flag so figures can be recomputed on complete cases. The imputed share is
  reported on the Data Quality page.

## 7. Operational limits

- The dashboard is a **prototype build**, not a hardened production service: no
  authentication, no multi-tenant isolation and no scheduled execution are included.
- SQL support is SQLite for local operation. The SQL is written to remain portable to
  PostgreSQL, but no other backend is configured or tested.
- Report email delivery is optional and requires SMTP configuration; it is disabled by
  default and never sends anything without explicit configuration.
