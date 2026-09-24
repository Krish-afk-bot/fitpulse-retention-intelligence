# FitPulse methodology

This document describes how FitPulse produces a number. It is deliberately specific: the
canonical model, the mapping rules, the integrity constraints, the metric arithmetic, the
provenance vocabulary and the assumptions applied to each dataset.

---

## 1. Canonical data model

FitPulse works on two conceptual sources, mirroring how a real fitness business routes
separate operational systems into one analytics platform:

- **Activity source** — event rows (a scheduled or recorded session).
- **Membership source** — member rows (one per member, with the churn outcome).

Every dataset is mapped onto canonical fields before any analysis. The canonical model is
defined once in `src/ingestion/canonical.py` and covers identity (`member_id`), activity
(`activity_date`, `workout_type`, `duration_minutes`, `calories_burned`,
`attendance_status`, `check_in_time`), membership (`churn_status`, `membership_type`,
`join_date`, `last_visit_date`, `visits_per_month`, `avg_workout_duration_min`,
`avg_calories_burned`, `total_weight_lifted_kg`, `favorite_exercise`) and demographics
(`age`, `gender`).

Each field carries: a label, an expected value *shape*, an alias list, required/optional
status, the contract column name the cleaning layer uses, units, plausible ranges and a
business meaning. The generated `artifacts/DATA_DICTIONARY.md` and the in-app *Methodology*
page render this model.

**Why this matters:** the analytics layer never sees a raw header. `customer_id`,
`MemberID`, `user_id` and `client_id` all become `member_id`, so the same code path runs
regardless of which dataset is loaded.

---

## 2. Detection, mapping and capabilities

### 2.1 Role detection

Each file is scored against activity and membership field patterns. The result is a role
(`activity`, `membership` or `unknown`), a confidence and the matched evidence. A file that
matches neither is labelled *unknown*, given the closest role for a starting point, and
flagged for review.

### 2.2 Column mapping

For each canonical field, every column is scored on two independent signals:

- **Header similarity** — exact alias match, containment, token overlap, then fuzzy ratio.
  Matching ignores case, spaces, underscores and punctuation, and short aliases (such as
  `id`) match only exactly.
- **Value plausibility** — the column's values are profiled (date-parse ratio, numeric
  ratio, distinct count, two-state vocabulary) and checked against the field's expected
  shape. A right-sounding header with impossible values is penalised heavily, so a numeric
  `revenue` column can never be mapped onto a date field.

The combined score becomes a confidence (`high`, `medium`, `low`). Two candidates within a
small margin make the mapping **ambiguous**, which forces confirmation instead of guessing.

### 2.3 Two-state outcomes

Churn and attendance flags are translated into an explicit `Yes`/`No` vocabulary using
field-aware word lists (`churn`, `cancelled`, `inactive` → Yes; `retained`, `active`,
`stayed` → No; `absent`, `no-show`, `missed` → not attended). Headers that name the
*opposite* state (`active`, `is_active`, `retained`, `no_show`) are inverted. When the
vocabulary is unrecognisable, the minority-class heuristic is applied and the mapping is
flagged for the user to confirm — it is never silently assumed.

### 2.4 Manual override

Any field can be corrected by hand or declared unavailable on the Data sources page.
Overrides are recorded with the mapping (`confirmed by user`), take precedence over
detection, and re-run the compatibility assessment.

### 2.5 Capabilities

Capabilities are derived from the confirmed mapping, never from hope:

| Capability | Requires |
|---|---|
| Activity analysis, time series, engagement, attendance funnel | Activity source with a date column |
| Workout-type analysis | `workout_type` |
| Session duration analysis | `duration_minutes` / `avg_workout_duration_min` |
| Streak analysis | Dated events **plus** a repeatable member identifier (or the documented synthetic calendar) |
| Retention, churn | Membership source with a churn outcome |
| Segmentation | Churn outcome **and** an engagement measure |
| Integration, SQL validation | Both sources loaded together |
| Subscription renewal, revenue | Never — the sources contain no such events |

A capability that is unavailable is reported with its reason, and the pages that depend on
it render an explanation instead of an empty chart.

### 2.6 Compatibility score

A dataset's compatibility score combines required-field coverage (45%), optional-field
coverage (35%) and the plausibility of the fields that were matched (20%). Missing a
required field caps the score and returns `FAIL`.

---

## 3. Data quality and cleaning

Every cleaning step is measurable and recorded: placeholder strings become nulls, whitespace
and categories are normalised, types are converted (with failure counts), duplicates are
removed, outliers are **classified but never deleted**, and numeric gaps are median-imputed
with an explicit `<column>_imputed` flag so KPIs can be recomputed on complete cases.

Direct personal identifiers (`Name`, `Address`, `Phone_Number`, email) are dropped during
cleaning and never reach the curated layer, the SQLite warehouse or the report.

Validation returns structured results (`status`, `checks`, `warnings`, `errors`) across
schema, numeric ranges, dates, categories, missingness, duplicates and business rules, plus
a canonical-model validation after cleaning.

---

## 4. Integration integrity

The two sources are never joined. Instead:

1. **Key analysis** — candidate keys are tested for uniqueness, overlap and the row
   multiplication a naive join would cause. The verdict and recommendation are recorded.
2. **No fabricated join** — the curated layer contains the two models side by side.
3. **Namespace separation** — membership identifiers become `M-…`; a repeatable activity
   identifier becomes `A-…`. An unrelated integer can therefore never match, and the two
   sets are provably disjoint.
4. **Synthetic bridge** — where member-level activity is required, a separate, clearly
   labelled table is produced (see §6). Real and synthetic events are never co-mingled.
5. **Row accounting** — source rows, cleaned rows, synthetic rows and unified rows are all
   reported so the effect of every stage is visible.

---

## 5. Metric definitions

- **Retention rate** — retained members ÷ members with a *recorded* churn outcome. Members
  without an outcome are excluded from numerator and denominator; the coverage is stated.
- **Churn rate** — churned members ÷ members with a recorded churn outcome.
- **At-risk members** — members in the `At Risk` or `Dormant` engagement segments. This is a
  behavioural flag, **not** a churn prediction.
- **Platform attendance rate** — sessions with an attendance outcome of *Present* ÷ recorded
  sessions. Because the reference activity source records nominal duration for absent
  sessions, an attendance-gated *confirmed* duration/calorie measure is reported beside every
  total.
- **Engagement score** (0–100) — weighted composite of frequency (0.30), consistency (0.25),
  streak (0.20), recency (0.15) and duration (0.10), each scaled against the observed cohort.
  Configurable through environment variables. These are product-design weights, **not**
  validated causal weights.
- **Segments** — engagement-score bands: `A - Highly Engaged`, `B - Regular`, `C - At Risk`
  and below the lowest threshold `D - Dormant`. Thresholds are configurable.
- **Behavioural drop-off and lifecycle funnel** — staged counts from registration through
  first workout, repeat activity and consistent activity, using real membership attributes
  and (where labelled) synthetic-calendar event counts.

Statistical helpers used in the product: Wilson score intervals for rates on small samples,
Cohen's d for standardised group differences, and IQR/domain-based outlier classification.

---

## 6. The synthetic analytical calendar

**What it is.** The reference membership dataset publishes member-level aggregates (visit
rate, average duration, calories) but not the individual visits. To demonstrate multi-source
integration — and to compute streak behaviour — FitPulse rebuilds a visit calendar for each
member from that member's *real* visit rate, deterministically (fixed seed from
configuration).

**What is generated:** the dates of each member's visits.
**What is unchanged:** the visit rate that drives them, every duration and calorie measure,
every membership attribute, and the churn outcome.
**Consequence:** consistency, streak and calendar-derived recency columns depend on date
placement. They are labelled *Synthetic calendar* in every card, chart, table and report,
and are described as illustrative of the method rather than observed history.
**Not used for outcomes:** retention and churn always come from the real churn label.

---

## 7. Provenance vocabulary

| Marker | Meaning |
|---|---|
| **Real source** | A field present in the loaded dataset, used unchanged |
| **Derived** | Calculated from real source fields by documented arithmetic |
| **Synthetic calendar** | Depends on the documented synthetic date placement described above |

Every KPI card, chart and table carries one of these markers, and the report states them in
its methodology note.

---

## 8. Python ↔ SQL validation

The pipeline builds a SQLite warehouse from the curated tables and independently
recomputes the critical KPIs in SQL. Python and SQL values are compared with declared
tolerances (exact agreement for counts; per-KPI absolute tolerance for rates and averages),
and the difference and status are shown on the SQL Validation page and in the report. A
validation stage that never ran is reported as `NOT_APPLICABLE`, never as `PASS`.

---

## 9. Alerts

Alerts are threshold evaluations, not model outputs. Each alert carries the metric, the
current value, the threshold, the severity, the affected population, a timestamp and a
plain-language explanation. Thresholds are configuration (inactivity days, churn-rate
ceiling, engagement/activity drop percentages, missing-data share) and re-evaluate
immediately when changed.

---

## 10. Language rules

The product reports **associations**: *"associated with"*, *"observed among"*,
*"correlated with"*. It does not claim causation, and it does not claim prediction. Every
finding is computed from the loaded data at the moment it is displayed — no number in the
interface is written by hand.
