"""Schema detection, column mapping and capability assessment.

FitPulse is not tied to one dataset. This module answers three questions *before*
any analysis runs:

1. **What is this file?** — :func:`detect_role` classifies a frame as an
   activity/event table, a membership/member table, or unknown, with a score and
   the reasons behind the decision.
2. **Which column is which?** — :func:`suggest_mapping` matches headers onto the
   canonical fields in :mod:`src.ingestion.canonical` and attaches a confidence
   to every match. A header alone is never trusted: the *values* in the column
   must also be plausible for the field (a numeric revenue column can never be
   mapped onto a date field). Ambiguous matches are flagged so the UI can ask
   the user to confirm instead of guessing.
3. **What can be analysed?** — :func:`assess_compatibility` produces the
   compatibility score and the capability list (activity, engagement, retention,
   churn, segmentation, streaks, funnel, SQL validation …). Missing fields
   remove capabilities; they never invent data.

The adapter :func:`build_loaded_source` then renames mapped columns onto the
contract names the cleaning layer already understands, so the curated model and
every downstream metric stay identical regardless of which dataset was loaded.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from difflib import SequenceMatcher
from typing import Any, Dict, List, Optional, Sequence, Tuple

import numpy as np
import pandas as pd

from ..common.logging_utils import get_logger
from .canonical import (
    KIND_BOOLEAN,
    KIND_CATEGORICAL,
    KIND_DATE,
    KIND_IDENTIFIER,
    KIND_NUMERIC,
    KIND_TIME,
    ROLE_ACTIVITY,
    ROLE_MEMBERSHIP,
    ROLES,
    CanonicalField,
    contract_names,
    fields_for_role,
    get_field,
    required_fields_for_role,
)

logger = get_logger("mapping")

#: Confidence vocabulary, ordered.
HIGH, MEDIUM, LOW, NONE = "high", "medium", "low", "none"
CONFIDENCE_ORDER = {NONE: 0, LOW: 1, MEDIUM: 2, HIGH: 3}
CONFIDENCE_LABEL = {
    HIGH: "High confidence",
    MEDIUM: "Medium confidence",
    LOW: "Low confidence — confirm before running",
    NONE: "Not detected",
}

#: Minimum score for a column to be proposed for a canonical field at all.
MIN_MATCH_SCORE = 0.35
#: Two candidates within this margin make the mapping ambiguous.
AMBIGUITY_MARGIN = 0.08

# --- value vocabularies (field-aware: "absent" means the opposite of churn) ---
CHURN_TRUE = {
    "yes", "y", "true", "t", "1", "1.0", "churn", "churned", "churn yes", "churnyes",
    "cancelled", "canceled", "cancel", "cancellation", "inactive", "left", "left gym",
    "terminated", "exited", "lost", "lapsed", "expired", "deactivated", "closed",
    "unsubscribed", "attrited", "not retained", "not active", "member churn", "high risk",
}
CHURN_FALSE = {
    "no", "n", "false", "f", "0", "0.0", "not churned", "no churn", "retained", "retain",
    "active", "stayed", "staying", "current", "member", "subscribed", "renewed",
    "continuing", "loyal", "onboard", "enrolled", "in good standing", "low risk",
}
ATTEND_TRUE = {
    "yes", "y", "true", "t", "1", "1.0", "present", "attended", "attend", "showed up",
    "show", "checked in", "on time", "completed", "complete", "joined", "in",
}
ATTEND_FALSE = {
    "no", "n", "false", "f", "0", "0.0", "absent", "not present", "missed", "no show",
    "noshow", "cancelled", "canceled", "skipped", "declined", "not attended", "out",
    "did not attend",
}

#: Headers that name the *opposite* of the boolean field they carry.
INVERTED_HEADERS: Dict[str, set] = {
    "churn_status": {
        "active", "is_active", "active_flag", "retained", "is_retained", "retention",
        "retention_status", "stayed", "current", "loyal", "not_churned",
    },
    "attendance_status": {
        "no_show", "noshow", "absent", "missed", "skipped", "not_present", "did_not_attend",
    },
}

BOOLEAN_TRUE_WORDS = CHURN_TRUE | ATTEND_TRUE
BOOLEAN_FALSE_WORDS = CHURN_FALSE | ATTEND_FALSE

_DATE_SHAPE = re.compile(r"^\s*\d{1,4}[-/.]\d{1,2}[-/.]\d{1,4}([ T]\d{1,2}:\d{2}(:\d{2})?)?")
_TIME_SHAPE = re.compile(r"^\s*\d{1,2}:\d{2}(:\d{2})?\s*(am|pm)?\s*$", re.IGNORECASE)
_ID_SHAPE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.\-/]{0,40}$")


# ---------------------------------------------------------------------------
# Header normalisation and similarity
# ---------------------------------------------------------------------------
def normalize_key(name: Any) -> str:
    """Case/space/punctuation-insensitive key used for all header matching."""
    decomposed = unicodedata.normalize("NFKD", str(name))
    ascii_only = "".join(ch for ch in decomposed if not unicodedata.combining(ch))
    lowered = ascii_only.strip().lower()
    slug = re.sub(r"[^a-z0-9]+", "_", lowered)
    return re.sub(r"_+", "_", slug).strip("_")


def _tokens(key: str) -> set:
    return {token for token in key.split("_") if token}


def header_similarity(normalized_column: str, alias: str) -> float:
    """How well a normalised header matches one alias (0-1)."""
    alias_key = normalize_key(alias)
    if not alias_key or not normalized_column:
        return 0.0
    if normalized_column == alias_key:
        return 1.0
    # Short aliases ("id") only match exactly, otherwise every column containing
    # those letters would compete for the identifier field.
    if len(alias_key) < 5 or len(normalized_column) < 5:
        return 0.0
    if alias_key in normalized_column or normalized_column in alias_key:
        return 0.80
    col_tokens, alias_tokens = _tokens(normalized_column), _tokens(alias_key)
    if col_tokens and alias_tokens:
        overlap = len(col_tokens & alias_tokens) / len(col_tokens | alias_tokens)
        if overlap >= 0.5:
            return 0.55 + 0.35 * overlap
    ratio = SequenceMatcher(None, normalized_column, alias_key).ratio()
    if ratio >= 0.72:
        return 0.85 * ratio
    return 0.0


def field_header_score(normalized_column: str, canonical: CanonicalField) -> Tuple[float, str]:
    """Best header match across a field's aliases, with the alias that matched."""
    best, matched_alias = 0.0, ""
    for alias in canonical.aliases:
        score = header_similarity(normalized_column, alias)
        if score > best:
            best, matched_alias = score, alias
    return best, matched_alias


# ---------------------------------------------------------------------------
# Value evidence
# ---------------------------------------------------------------------------
@dataclass
class ColumnEvidence:
    """What the values in a column actually look like."""

    name: str
    total: int = 0
    non_null: int = 0
    distinct: int = 0
    kind: str = "empty"
    date_ratio: float = 0.0
    numeric_ratio: float = 0.0
    time_ratio: float = 0.0
    bool_like: bool = False
    mean_length: float = 0.0
    examples: List[str] = field(default_factory=list)

    @property
    def uniqueness(self) -> float:
        return float(self.distinct / self.non_null) if self.non_null else 0.0

    @property
    def null_ratio(self) -> float:
        return float(1 - self.non_null / self.total) if self.total else 1.0

    def distinct_values(self) -> List[str]:
        return list(self.examples)


def column_evidence(series: pd.Series, name: Optional[str] = None) -> ColumnEvidence:
    """Profile one raw (string) column into shape evidence."""
    label = name or str(series.name)
    text = series.astype("string")
    non_null = text.dropna().astype(str).str.strip()
    non_null = non_null[non_null != ""]
    evidence = ColumnEvidence(
        name=label,
        total=int(len(series)),
        non_null=int(len(non_null)),
    )
    if non_null.empty:
        return evidence

    distinct = non_null.drop_duplicates()
    evidence.distinct = int(len(distinct))
    evidence.mean_length = float(non_null.str.len().mean())
    evidence.examples = [str(v) for v in distinct.head(80).tolist()]

    shaped_dates = non_null[non_null.str.match(_DATE_SHAPE)]
    evidence.date_ratio = float(len(shaped_dates) / len(non_null))
    evidence.time_ratio = float(non_null.str.match(_TIME_SHAPE).mean())
    evidence.numeric_ratio = float(pd.to_numeric(non_null, errors="coerce").notna().mean())

    lowered = {v.strip().lower().replace("_", " ") for v in distinct.tolist()}
    evidence.bool_like = bool(
        len(lowered) <= 6 and lowered <= (BOOLEAN_TRUE_WORDS | BOOLEAN_FALSE_WORDS | {"", "0", "1"})
    )

    if evidence.date_ratio >= 0.8:
        evidence.kind = KIND_DATE
    elif evidence.time_ratio >= 0.8:
        evidence.kind = KIND_TIME
    elif evidence.bool_like:
        evidence.kind = KIND_BOOLEAN
    elif evidence.numeric_ratio >= 0.95:
        evidence.kind = KIND_NUMERIC
    elif evidence.distinct <= max(50, int(0.3 * max(len(non_null), 1))) and evidence.mean_length <= 40:
        evidence.kind = KIND_CATEGORICAL
    else:
        evidence.kind = "text"
    return evidence


def kind_support(evidence: ColumnEvidence, canonical: CanonicalField) -> Tuple[float, List[str]]:
    """How plausible are `evidence`'s values for `canonical` (0-1 + notes)."""
    kind = canonical.kind
    notes: List[str] = []

    if kind == KIND_DATE:
        if evidence.date_ratio >= 0.8:
            return 1.0, ["values parse as dates"]
        if evidence.date_ratio >= 0.5:
            notes.append(f"only {evidence.date_ratio:.0%} of values look like dates")
            return 0.45, notes
        return 0.0, ["values do not look like dates"]

    if kind == KIND_TIME:
        if evidence.time_ratio >= 0.8:
            return 1.0, ["values look like clock times"]
        if evidence.date_ratio >= 0.8 and evidence.numeric_ratio < 0.9:
            return 0.4, ["values look like timestamps rather than times"]
        return 0.0, ["values do not look like clock times"]

    if kind == KIND_NUMERIC:
        if evidence.numeric_ratio >= 0.95:
            if canonical.expected_min is not None:
                numeric = pd.to_numeric(pd.Series(evidence.examples), errors="coerce").dropna()
                if not numeric.empty and canonical.expected_min is not None and canonical.expected_max:
                    if (numeric > canonical.expected_max * 20).any():
                        notes.append(
                            f"values exceed the plausible {canonical.label.lower()} range "
                            f"({canonical.expected_min:g}-{canonical.expected_max:g} {canonical.unit})".strip()
                        )
                        return 0.5, notes
            return 1.0, ["values are numeric"]
        if evidence.numeric_ratio >= 0.7:
            notes.append(f"only {evidence.numeric_ratio:.0%} of values are numeric")
            return 0.45, notes
        return 0.0, ["values are mostly non-numeric"]

    if kind == KIND_BOOLEAN:
        lowered = {v.strip().lower().replace("_", " ") for v in evidence.examples}
        vocabulary = CHURN_TRUE | CHURN_FALSE if canonical.name == "churn_status" else ATTEND_TRUE | ATTEND_FALSE
        known = lowered & vocabulary
        if evidence.bool_like and known:
            notes.append(f"two-state values recognised ({len(known)} vocabulary matches)")
            return 1.0, notes
        if evidence.distinct == 2:
            notes.append("exactly two distinct values")
            return 0.9, notes
        if evidence.distinct <= 6:
            return 0.4, ["more than two states — value mapping will need confirmation"]
        return 0.0, ["too many distinct values to be a flag"]

    if kind == KIND_CATEGORICAL:
        if evidence.distinct <= 50:
            return 1.0, [f"{evidence.distinct} distinct values"]
        if evidence.distinct <= 200:
            return 0.6, [f"{evidence.distinct} distinct values — high cardinality"]
        if evidence.numeric_ratio >= 0.95:
            notes.append("numeric column used as a category code")
            return 0.3, notes
        return 0.2, [f"{evidence.distinct} distinct values — too granular for a category"]

    if kind == KIND_IDENTIFIER:
        score = 0.5
        if evidence.uniqueness >= 0.8:
            score += 0.4
            notes.append("near-unique values")
        elif evidence.uniqueness >= 0.3:
            score += 0.2
            notes.append("repeating values (repeatable member key)")
        if evidence.mean_length <= 40:
            score += 0.1
        return min(score, 1.0), notes

    return 0.3, notes


# ---------------------------------------------------------------------------
# Boolean value mapping
# ---------------------------------------------------------------------------
@dataclass
class ValueMapping:
    """How a two-state column's raw values were translated to ``Yes``/``No``."""

    series: pd.Series
    confidence: str = HIGH
    inverted: bool = False
    needs_confirmation: bool = False
    notes: List[str] = field(default_factory=list)

    def as_dict(self) -> Dict[str, Any]:
        return {
            "confidence": self.confidence,
            "inverted": self.inverted,
            "needs_confirmation": self.needs_confirmation,
            "notes": self.notes,
        }


def _looks_inverted(field_name: str, alias: str) -> bool:
    return normalize_key(alias) in INVERTED_HEADERS.get(field_name, set())


def resolve_boolean(series: pd.Series, canonical: CanonicalField, alias: str) -> ValueMapping:
    """Translate a two-state column into ``Yes``/``No``.

    Resolution order:

    1. Explicit vocabulary for the field (``churn``/``cancelled`` -> Yes,
       ``retained``/``active`` -> No; ``absent``/``no-show`` -> No for attendance).
    2. ``0``/``1`` (and ``true``/``false``) with the header inversion hint applied.
    3. Two arbitrary labels with no recognisable vocabulary: the *minority* class
       is treated as the event and the user is asked to confirm.
    """
    text = series.astype("string").str.strip()
    distinct = [v for v in text.dropna().unique().tolist() if str(v).strip() != ""]
    mapping: Dict[str, Optional[bool]] = {}
    notes: List[str] = []
    inverted = False
    confidence = HIGH
    needs_confirmation = False

    true_words = CHURN_TRUE if canonical.name == "churn_status" else ATTEND_TRUE
    false_words = CHURN_FALSE if canonical.name == "churn_status" else ATTEND_FALSE

    unrecognised: List[str] = []
    for value in distinct:
        key = str(value).strip().lower()
        key = re.sub(r"[_\-]+", " ", key)
        if key in true_words:
            mapping[str(value)] = True
        elif key in false_words:
            mapping[str(value)] = False
        elif key in {"1", "1.0"}:
            mapping[str(value)] = True
        elif key in {"0", "0.0"}:
            mapping[str(value)] = False
        else:
            unrecognised.append(str(value))

    if unrecognised and len(distinct) == 2 and len(mapping) == 1:
        # One label is known and one is not: treat the unknown label as the other
        # state and say so rather than silently inventing a vocabulary.
        known_value, known_state = next((k, v) for k, v in mapping.items() if k in {"1", "1.0", "0", "0.0"})
        unknown = next(v for v in distinct if str(v) not in mapping)
        mapping[str(unknown)] = not known_state
        confidence = LOW
        needs_confirmation = True
        notes.append(
            f"'{unknown}' was not recognised; treated as the opposite of the recognised value "
            f"'{known_value}' and flagged for confirmation."
        )
    elif unrecognised and len(distinct) == 2 and not mapping:
        # No vocabulary at all: fall back to the minority-class heuristic.
        counts = text.value_counts()
        minority = [v for v in counts.index if str(v) in unrecognised]
        if len(minority) == 2:
            minority_value = str(counts.idxmin())
            mapping = {str(v): (str(v) == minority_value) for v in distinct}
            confidence = LOW
            needs_confirmation = True
            notes.append(
                "Values carry no recognisable vocabulary; the minority class "
                f"('{minority_value}', {counts.min() / counts.sum():.0%} of rows) is assumed to be the event."
            )
    elif unrecognised and len(distinct) > 2:
        mapping = {k: v for k, v in mapping.items()}
        confidence = LOW
        needs_confirmation = True
        notes.append(f"Unrecognised states ignored in the flag mapping: {unrecognised[:5]}")

    if _looks_inverted(canonical.name, alias) and not notes:
        inverted = True
        mapping = {k: (not v if v is not None else None) for k, v in mapping.items()}
        notes.append(
            f"Header '{alias}' names the opposite state, so values were inverted to express "
            f"{canonical.label.lower()}."
        )
        if confidence == HIGH:
            confidence = MEDIUM

    normalised = text.map(lambda v: mapping.get(str(v)) if pd.notna(v) else None)
    normalised = normalised.map({True: "Yes", False: "No", None: pd.NA})
    return ValueMapping(
        series=normalised.astype("string"),
        confidence=confidence,
        inverted=inverted,
        needs_confirmation=needs_confirmation,
        notes=notes,
    )


# ---------------------------------------------------------------------------
# Matches, mappings, detections
# ---------------------------------------------------------------------------
@dataclass
class ColumnMatch:
    """One canonical field matched (or explicitly not matched) to a column."""

    canonical: str
    label: str
    column: Optional[str]
    confidence: str
    score: float
    matched_by: str
    value_kind: str = ""
    inverted: bool = False
    needs_confirmation: bool = False
    notes: List[str] = field(default_factory=list)

    def as_dict(self) -> Dict[str, Any]:
        return {
            "canonical": self.canonical,
            "label": self.label,
            "column": self.column,
            "confidence": self.confidence,
            "score": round(float(self.score), 3),
            "matched_by": self.matched_by,
            "value_kind": self.value_kind,
            "inverted": self.inverted,
            "needs_confirmation": self.needs_confirmation,
            "notes": self.notes,
        }


@dataclass
class RoleDetection:
    """Which conceptual source a file represents."""

    role: str
    confidence: str
    score: float
    reasons: List[str] = field(default_factory=list)
    scores: Dict[str, float] = field(default_factory=dict)

    @property
    def label(self) -> str:
        return role_label(self.role)

    def as_dict(self) -> Dict[str, Any]:
        return {
            "role": self.role,
            "label": self.label,
            "confidence": self.confidence,
            "score": round(float(self.score), 3),
            "scores": {k: round(float(v), 3) for k, v in self.scores.items()},
            "reasons": self.reasons,
        }


@dataclass
class CanonicalMapping:
    """The mapping proposed for one dataset, before or after user confirmation."""

    role: str
    matches: Dict[str, ColumnMatch] = field(default_factory=dict)
    detection: Optional[RoleDetection] = None
    unmatched_columns: List[str] = field(default_factory=list)
    notes: List[str] = field(default_factory=list)
    confirmed: bool = False

    def column_for(self, canonical: str) -> Optional[str]:
        match = self.matches.get(canonical)
        return match.column if match else None

    def supplied(self) -> List[str]:
        return sorted(name for name, match in self.matches.items() if match.column)

    def missing(self, required_only: bool = False) -> List[str]:
        out = []
        for canonical in fields_for_role(self.role):
            match = self.matches.get(canonical.name)
            if match and match.column:
                continue
            if required_only and not canonical.required:
                continue
            out.append(canonical.name)
        return out

    def requires_confirmation(self) -> bool:
        if self.confirmed:
            return False
        return any(
            match.needs_confirmation or match.confidence == LOW
            for match in self.matches.values()
        )

    def as_dict(self) -> Dict[str, Any]:
        return {
            "role": self.role,
            "role_label": role_label(self.role),
            "confirmed": self.confirmed,
            "detection": self.detection.as_dict() if self.detection else None,
            "matches": {name: match.as_dict() for name, match in self.matches.items()},
            "unmatched_columns": self.unmatched_columns,
            "notes": self.notes,
        }

    def as_frame(self) -> pd.DataFrame:
        """Tabular view used by the mapping review UI."""
        rows = []
        for canonical in fields_for_role(self.role):
            match = self.matches.get(canonical.name)
            rows.append(
                {
                    "canonical": canonical.name,
                    "field": canonical.label,
                    "required": "required" if canonical.required else "optional",
                    "detected": (match.column or "—") if match else "—",
                    "confidence": CONFIDENCE_LABEL[match.confidence] if match else CONFIDENCE_LABEL[NONE],
                    "value_kind": match.value_kind if match else "",
                    "detail": "; ".join(match.notes) if match else "",
                    "needs_confirmation": bool(match and match.needs_confirmation),
                }
            )
        return pd.DataFrame(rows)

    def overrides(self) -> Dict[str, Optional[str]]:
        """Flatten to ``{canonical: column}`` for re-applying a confirmed mapping."""
        return {name: match.column for name, match in self.matches.items() if match.column}


def role_label(role: str) -> str:
    return {
        ROLE_ACTIVITY: "Activity / attendance",
        ROLE_MEMBERSHIP: "Membership / member",
        "unknown": "Unknown",
    }.get(role, role)


# ---------------------------------------------------------------------------
# Role detection
# ---------------------------------------------------------------------------
#: Header evidence weights used to classify a file. Churn and join/last-visit
#: fields point at membership; attendance/date/duration fields point at activity.
ROLE_WEIGHTS: Dict[str, Dict[str, float]] = {
    ROLE_ACTIVITY: {
        "activity_date": 3.0,
        "attendance_status": 2.0,
        "workout_type": 1.5,
        "duration_minutes": 1.5,
        "calories_burned": 1.0,
        "check_in_time": 0.5,
    },
    ROLE_MEMBERSHIP: {
        "churn_status": 3.0,
        "last_visit_date": 2.0,
        "visits_per_month": 2.0,
        "join_date": 1.5,
        "membership_type": 1.5,
        "avg_workout_duration_min": 1.0,
        "avg_calories_burned": 1.0,
        "favorite_exercise": 0.5,
        "total_weight_lifted_kg": 0.5,
    },
}


def detect_role(frame: pd.DataFrame) -> RoleDetection:
    """Classify a frame as an activity table, a membership table, or unknown."""
    keys = [normalize_key(column) for column in frame.columns]
    scores: Dict[str, float] = {}
    reasons: Dict[str, List[str]] = {}

    for role, weights in ROLE_WEIGHTS.items():
        total_weight = sum(weights.values())
        earned = 0.0
        reasons[role] = []
        for field_name, weight in weights.items():
            canonical = get_field(field_name)
            best, alias = 0.0, ""
            for key in keys:
                score, matched = field_header_score(key, canonical)
                if score > best:
                    best, alias = score, matched
            if best >= 0.5:
                earned += weight * best
                reasons[role].append(f"{canonical.label} ← '{alias}'")
        scores[role] = earned / total_weight

    best_role = max(scores, key=lambda role: scores[role])
    best_score = scores[best_role]
    ordered = sorted(scores.values(), reverse=True)
    margin = ordered[0] - ordered[1] if len(ordered) > 1 else ordered[0]

    if best_score < 0.18:
        return RoleDetection(
            role="unknown",
            confidence=NONE,
            score=best_score,
            reasons=["no recognised activity or membership fields were found"],
            scores=scores,
        )

    if best_score >= 0.55 and margin >= 0.25:
        confidence = HIGH
    elif best_score >= 0.3 and margin >= 0.1:
        confidence = MEDIUM
    else:
        confidence = LOW

    return RoleDetection(
        role=best_role,
        confidence=confidence,
        score=best_score,
        reasons=reasons[best_role],
        scores=scores,
    )


# ---------------------------------------------------------------------------
# Mapping suggestion
# ---------------------------------------------------------------------------
def _candidate_score(
    evidence: ColumnEvidence,
    canonical: CanonicalField,
) -> Tuple[float, str, List[str], bool]:
    """Score one column for one canonical field, with the alias that matched."""
    header, alias = field_header_score(evidence.name, canonical)
    if header <= 0:
        return 0.0, "", [], False
    support, notes = kind_support(evidence, canonical)
    score = 0.68 * header + 0.32 * support
    if support == 0.0:
        # A right-sounding header with impossible values is almost certainly wrong.
        notes.append("values are incompatible with this field")
        score *= 0.35
    return score, alias, notes, support > 0


def suggest_mapping(
    frame: pd.DataFrame,
    role: Optional[str] = None,
    overrides: Optional[Dict[str, Optional[str]]] = None,
) -> CanonicalMapping:
    """Propose a canonical mapping for ``frame``, optionally user-corrected.

    ``overrides`` maps canonical field -> the user's chosen column (or ``None``
    to state that the field is genuinely unavailable in this dataset).
    """
    detection = detect_role(frame)
    resolved_role = role or detection.role
    if resolved_role not in ROLES:
        resolved_role = detection.role if detection.role in ROLES else ROLE_ACTIVITY

    evidence = {str(column): column_evidence(frame[column], str(column)) for column in frame.columns}
    normalised = {column: normalize_key(column) for column in frame.columns}

    candidates: List[Tuple[float, str, str, str, List[str], bool]] = []
    for canonical in fields_for_role(resolved_role):
        for column, ev in evidence.items():
            score, alias, notes, plausible = _candidate_score(
                ColumnEvidence(name=normalised[column], **{k: v for k, v in ev.__dict__.items() if k != "name"}),
                canonical,
            )
            if score >= MIN_MATCH_SCORE:
                candidates.append((score, canonical.name, column, alias, notes, plausible))

    candidates.sort(key=lambda item: (-item[0], item[1], item[2]))
    taken_fields: set = set()
    taken_columns: set = set()
    matches: Dict[str, ColumnMatch] = {}

    for score, canonical_name, column, alias, notes, plausible in candidates:
        if canonical_name in taken_fields or column in taken_columns:
            continue
        canonical = get_field(canonical_name)
        runner_up = max(
            (
                other_score
                for other_score, other_field, other_column, *_rest in candidates
                if other_field == canonical_name and other_column != column
            ),
            default=0.0,
        )
        ambiguous = runner_up >= score - AMBIGUITY_MARGIN and runner_up > 0
        if score >= 0.88 and not ambiguous:
            confidence = HIGH
        elif score >= 0.68:
            confidence = MEDIUM
        else:
            confidence = LOW

        match = ColumnMatch(
            canonical=canonical_name,
            label=canonical.label,
            column=column,
            confidence=confidence,
            score=score,
            matched_by=f"header '{normalised[column]}' ≈ alias '{alias}'",
            value_kind=evidence[column].kind,
            needs_confirmation=ambiguous,
            notes=list(notes),
        )
        if ambiguous:
            match.notes.append("more than one column matches this field — please confirm")
        if canonical.kind == KIND_BOOLEAN:
            value_map = resolve_boolean(frame[column], canonical, alias)
            match.inverted = value_map.inverted
            match.confidence = _weaken(match.confidence, value_map.confidence)
            match.needs_confirmation = match.needs_confirmation or value_map.needs_confirmation
            match.notes.extend(value_map.notes)
        matches[canonical_name] = match
        taken_fields.add(canonical_name)
        taken_columns.add(column)

    mapping = CanonicalMapping(
        role=resolved_role,
        matches=matches,
        detection=detection,
        unmatched_columns=[str(c) for c in frame.columns if str(c) not in taken_columns],
        notes=[],
    )

    if overrides:
        _apply_overrides(mapping, frame, overrides)

    for canonical in required_fields_for_role(resolved_role):
        match = mapping.matches.get(canonical.name)
        if match is None or not match.column:
            mapping.notes.append(
                f"Required field '{canonical.label}' was not detected — "
                f"{role_label(resolved_role)} analysis is unavailable without it."
            )
    if detection.role not in ROLES:
        mapping.notes.append(
            "Dataset type could not be determined confidently; the mapping below is a best guess "
            "and should be reviewed before running the pipeline."
        )
    return mapping


def _weaken(a: str, b: str) -> str:
    """Return the weaker of two confidences."""
    return a if CONFIDENCE_ORDER[a] <= CONFIDENCE_ORDER[b] else b


def _apply_overrides(
    mapping: CanonicalMapping,
    frame: pd.DataFrame,
    overrides: Dict[str, Optional[str]],
) -> None:
    columns = {str(column): str(column) for column in frame.columns}
    for canonical_name, chosen in overrides.items():
        if canonical_name not in {f.name for f in fields_for_role(mapping.role)}:
            continue
        canonical = get_field(canonical_name)
        if chosen in (None, "", "(not available)"):
            mapping.matches.pop(canonical_name, None)
            continue
        if str(chosen) not in columns:
            mapping.notes.append(
                f"Manual mapping for '{canonical.label}' ignored: column '{chosen}' is not in the file."
            )
            continue
        evidence = column_evidence(frame[chosen], str(chosen))
        support, notes = kind_support(evidence, canonical)
        match = ColumnMatch(
            canonical=canonical_name,
            label=canonical.label,
            column=str(chosen),
            confidence=HIGH,
            score=1.0,
            matched_by="confirmed by user",
            value_kind=evidence.kind,
            notes=[f"manually mapped to '{chosen}'"],
        )
        if support == 0.0:
            match.notes.append("values do not look like this field's expected shape — overridden by user")
        match.notes.extend(notes)
        if canonical.kind == KIND_BOOLEAN:
            value_map = resolve_boolean(frame[chosen], canonical, str(chosen))
            match.inverted = value_map.inverted
            match.needs_confirmation = value_map.needs_confirmation
            match.notes.extend(value_map.notes)
        mapping.matches[canonical_name] = match
    mapping.confirmed = True


# ---------------------------------------------------------------------------
# Capabilities
# ---------------------------------------------------------------------------
@dataclass
class Capability:
    """One analysis the loaded data can (or cannot) support."""

    key: str
    label: str
    available: bool
    reason: str = ""

    def as_dict(self) -> Dict[str, Any]:
        return {"key": self.key, "label": self.label, "available": self.available, "reason": self.reason}


CAPABILITY_LABELS: Dict[str, str] = {
    "activity_analysis": "Activity analysis",
    "engagement_analysis": "Engagement analysis",
    "time_series": "Time-series trends",
    "funnel_analysis": "Attendance funnel",
    "workout_type_analysis": "Workout-type analysis",
    "duration_analysis": "Session duration analysis",
    "streak_analysis": "Streak analysis",
    "retention_analysis": "Retention analysis",
    "churn_analysis": "Churn analysis",
    "segmentation": "Behavioural segmentation",
    "member_level_analysis": "Member-level analysis",
    "integration": "Cross-source integration",
    "sql_validation": "SQL validation",
    "subscription_analysis": "Subscription renewal",
    "revenue_analysis": "Revenue analysis",
}

#: Capabilities that need both conceptual sources present.
DUAL_SOURCE_CAPABILITIES = ("integration", "sql_validation")


def _cap(
    key: str,
    available: bool,
    reason: str = "",
) -> Capability:
    return Capability(key=key, label=CAPABILITY_LABELS.get(key, key), available=available, reason=reason)


def capabilities_for(
    frame: pd.DataFrame,
    mapping: CanonicalMapping,
    capability_overrides: Optional[Dict[str, str]] = None,
) -> List[Capability]:
    """Derive the capability list for one mapped dataset."""
    overrides = capability_overrides or {}
    supplied = set(mapping.supplied())
    role = mapping.role
    repeats = (
        member_key_repeatable(frame, mapping.column_for("member_id"))
        if mapping.column_for("member_id")
        else False
    )

    caps: List[Capability] = []

    def add(key: str, available: bool, reason: str = "") -> None:
        if key in overrides:
            caps.append(_cap(key, True, overrides[key]))
            return
        caps.append(_cap(key, available, reason))

    if role == ROLE_ACTIVITY:
        has_date = "activity_date" in supplied
        add("activity_analysis", has_date, "" if has_date else "no activity date column was detected")
        add(
            "time_series",
            has_date,
            "" if has_date else "trends need a parseable activity date",
        )
        add(
            "engagement_analysis",
            has_date,
            "" if has_date else "engagement needs dated activity records",
        )
        add(
            "funnel_analysis",
            has_date and "attendance_status" in supplied,
            ""
            if "attendance_status" in supplied
            else "no attendance outcome column, so drop-off cannot be measured",
        )
        add(
            "workout_type_analysis",
            "workout_type" in supplied,
            "" if "workout_type" in supplied else "no workout/activity type column",
        )
        add(
            "duration_analysis",
            "duration_minutes" in supplied,
            "" if "duration_minutes" in supplied else "no session duration column",
        )
        add(
            "streak_analysis",
            has_date and repeats,
            ""
            if repeats
            else "streaks need a repeatable member identifier plus dated events",
        )
        add(
            "member_level_analysis",
            bool(mapping.column_for("member_id")) and repeats,
            "" if repeats else "the dataset's identifier is unique per row, so it is not a member key",
        )
        add("retention_analysis", False, "no churn or membership outcome in this dataset")
        add("churn_analysis", False, "no churn field in this dataset")
        add("segmentation", False, "segments are built from member-level retention data")
        add("integration", False, "only one of the two sources was provided")
        add("sql_validation", False, "the SQL warehouse is built when both sources are available")
    else:
        has_churn = "churn_status" in supplied
        has_visits = "visits_per_month" in supplied
        add(
            "retention_analysis",
            has_churn,
            "" if has_churn else "the dataset contains no churn/retention outcome",
        )
        add("churn_analysis", has_churn, "" if has_churn else "no churn field was detected")
        add(
            "segmentation",
            has_churn and (has_visits or "avg_workout_duration_min" in supplied),
            ""
            if has_churn
            else "segmentation ranks members by engagement and outcome, which needs a churn field",
        )
        add(
            "engagement_analysis",
            has_visits,
            "" if has_visits else "no visit-frequency or effort measures were detected",
        )
        add(
            "member_level_analysis",
            True,
            "",
        )
        add(
            "streak_analysis",
            True,
            "",
        )
        add("activity_analysis", False, "no event-level activity records in this dataset")
        add("time_series", False, "no event-level activity dates in this dataset")
        add("funnel_analysis", False, "attendance drop-off needs event-level activity records")
        add("workout_type_analysis", "workout_type" in supplied or "favorite_exercise" in supplied,
            "no workout-type column was detected")
        add("duration_analysis", "avg_workout_duration_min" in supplied, "no duration measure was detected")
        add("integration", False, "only one of the two sources was provided")
        add("sql_validation", False, "the SQL warehouse is built when both sources are available")

    # Capabilities that are structurally out of scope for the project.
    for key, reason in (
        ("subscription_analysis", "requires renewal-event data the sources do not provide"),
        ("revenue_analysis", "requires payment or revenue fields the sources do not provide"),
    ):
        caps.append(_cap(key, key in overrides, overrides.get(key, reason)))
    return caps


def member_key_repeatable(frame: pd.DataFrame, column: Optional[str]) -> bool:
    """Is this identifier a *repeatable* member key or a per-row sequence?"""
    if not column or column not in frame.columns:
        return False
    values = frame[column].astype("string").dropna()
    if values.empty:
        return False
    uniqueness = values.nunique() / len(values)
    return uniqueness < 0.95


def merge_capabilities(capability_lists: Sequence[Sequence[Capability]]) -> List[Capability]:
    """Combine per-dataset capabilities into one product-level list."""
    merged: Dict[str, Capability] = {}
    reasons: Dict[str, List[str]] = {}
    for capabilities in capability_lists:
        for capability in capabilities:
            existing = merged.get(capability.key)
            if existing is None or (capability.available and not existing.available):
                merged[capability.key] = capability
            if not capability.available and capability.reason:
                reasons.setdefault(capability.key, []).append(capability.reason)
    for key, capability in merged.items():
        if not capability.available:
            unique = list(dict.fromkeys(reasons.get(key, [])))
            capability.reason = "; ".join(unique)
    order = list(CAPABILITY_LABELS)
    return sorted(merged.values(), key=lambda c: order.index(c.key) if c.key in order else 99)


def apply_dual_source_capabilities(
    capabilities: Sequence[Capability], both_sources: bool
) -> List[Capability]:
    """Grant the two-source capabilities only when both sources are loaded."""
    out: List[Capability] = []
    for capability in capabilities:
        if capability.key in DUAL_SOURCE_CAPABILITIES and both_sources:
            out.append(
                _cap(
                    capability.key,
                    True,
                    "both sources loaded" if capability.key == "integration"
                    else "SQL warehouse built from both sources",
                )
            )
        elif capability.key in DUAL_SOURCE_CAPABILITIES and not both_sources:
            out.append(_cap(capability.key, False, "requires both an activity and a membership source"))
        else:
            out.append(capability)
    return out


def unavailable_capabilities(capabilities: Sequence[Capability]) -> List[Capability]:
    return [c for c in capabilities if not c.available]


def capability_map(capabilities: Sequence[Capability]) -> Dict[str, bool]:
    return {c.key: c.available for c in capabilities}


def capability_frame(capabilities: Sequence[Capability]) -> pd.DataFrame:
    """Tabular capability view for the UI."""
    return pd.DataFrame(
        [
            {
                "capability": cap.label,
                "status": "Available" if cap.available else "Unavailable",
                "reason": cap.reason or "supported by the loaded data",
            }
            for cap in capabilities
        ]
    )


# ---------------------------------------------------------------------------
# Compatibility
# ---------------------------------------------------------------------------
@dataclass
class CompatibilityReport:
    """Compatibility score plus the capability consequences of a mapping."""

    role: str
    score: float
    matched: List[str] = field(default_factory=list)
    missing_required: List[str] = field(default_factory=list)
    missing_optional: List[str] = field(default_factory=list)
    capabilities: List[Capability] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    assumptions: List[str] = field(default_factory=list)
    rows: int = 0
    columns: int = 0

    @property
    def status(self) -> str:
        if self.missing_required:
            return "FAIL"
        if self.score >= 80:
            return "PASS"
        if self.score >= 55:
            return "WARNING"
        return "FAIL"

    @property
    def available_capabilities(self) -> List[str]:
        return [c.label for c in self.capabilities if c.available]

    @property
    def unavailable_capabilities(self) -> List[str]:
        return [c.label for c in self.capabilities if not c.available]

    def as_dict(self) -> Dict[str, Any]:
        return {
            "role": self.role,
            "role_label": role_label(self.role),
            "score": round(float(self.score), 1),
            "status": self.status,
            "rows": self.rows,
            "columns": self.columns,
            "matched": self.matched,
            "missing_required": self.missing_required,
            "missing_optional": self.missing_optional,
            "capabilities": [c.as_dict() for c in self.capabilities],
            "warnings": self.warnings,
            "assumptions": self.assumptions,
        }

    def as_frame(self) -> pd.DataFrame:
        rows = []
        for canonical in fields_for_role(self.role):
            present = canonical.name in self.matched
            rows.append(
                {
                    "field": canonical.label,
                    "canonical_name": canonical.name,
                    "status": "Detected" if present else ("Required — missing" if canonical.required else "Optional — absent"),
                    "impact": canonical.business_meaning,
                }
            )
        return pd.DataFrame(rows)


def assess_compatibility(
    frame: pd.DataFrame,
    mapping: CanonicalMapping,
    capability_overrides: Optional[Dict[str, str]] = None,
) -> CompatibilityReport:
    """Score how well a dataset supports the product, and what it enables."""
    role = mapping.role
    all_fields = fields_for_role(role)
    required = [f for f in all_fields if f.required]
    optional = [f for f in all_fields if not f.required]

    matched = [f.name for f in all_fields if mapping.column_for(f.name)]
    missing_required = [f.name for f in required if not mapping.column_for(f.name)]
    missing_optional = [f.name for f in optional if not mapping.column_for(f.name)]

    required_score = (
        sum(1 for f in required if mapping.column_for(f.name)) / len(required) if required else 1.0
    )
    optional_score = (
        sum(1 for f in optional if mapping.column_for(f.name)) / len(optional) if optional else 1.0
    )

    plausibility = [
        min(mapping.matches[f.name].score, 1.0)
        for f in all_fields
        if mapping.column_for(f.name) and f.name in mapping.matches
    ]
    shape_score = float(np.mean(plausibility)) if plausibility else 0.0

    score = 100.0 * (0.45 * required_score + 0.35 * optional_score + 0.20 * shape_score)
    if missing_required:
        score = min(score, 40.0)

    warnings: List[str] = []
    assumptions: List[str] = []

    for field_name in ("churn_status", "attendance_status"):
        match = mapping.matches.get(field_name)
        if match and match.needs_confirmation:
            warnings.append(
                f"{match.label}: the value mapping is ambiguous — confirm it before relying on the result."
            )
        if match and match.inverted:
            assumptions.append(
                f"{match.label} was inverted because the source header names the opposite state."
            )

    if role == ROLE_ACTIVITY and not member_key_repeatable(frame, mapping.column_for("member_id")):
        assumptions.append(
            "The activity identifier is unique per row, so records cannot be attributed to members: "
            "member-level streaks are unavailable from this source."
        )
    if "attendance_status" not in matched and role == ROLE_ACTIVITY:
        assumptions.append(
            "No attendance outcome was found; every recorded session is treated as attended and the "
            "attendance funnel is reported as unavailable."
        )
    if role == ROLE_MEMBERSHIP and "churn_status" not in matched:
        warnings.append(
            "No churn/retention outcome was detected, so retention, churn and segmentation are "
            "unavailable for this dataset. FitPulse does not synthesise an outcome."
        )
    if mapping.requires_confirmation():
        warnings.append("Some column matches are low-confidence or ambiguous and need confirmation.")

    report = CompatibilityReport(
        role=role,
        score=score,
        matched=matched,
        missing_required=missing_required,
        missing_optional=missing_optional,
        capabilities=capabilities_for(frame, mapping, capability_overrides),
        warnings=warnings,
        assumptions=assumptions,
        rows=int(len(frame)),
        columns=int(frame.shape[1]),
    )
    logger.info(
        "Compatibility %s | score=%.1f | status=%s | capabilities=%s",
        role_label(role),
        score,
        report.status,
        [c.key for c in report.capabilities if c.available],
    )
    return report


# ---------------------------------------------------------------------------
# Adapter: mapped dataset -> contract frame -> LoadedSource
# ---------------------------------------------------------------------------
def contract_frame(
    frame: pd.DataFrame,
    mapping: CanonicalMapping,
) -> Tuple[pd.DataFrame, List[str]]:
    """Rename mapped columns onto the contract names the cleaners expect.

    Returns ``(contract_frame, assumptions)``. Assumptions are recorded whenever
    the absence of an optional field forces an explicit, documented convention
    (never a fabricated value).
    """
    role = mapping.role
    names = contract_names(role)
    out = pd.DataFrame(index=frame.index)
    assumptions: List[str] = []

    for canonical_name, contract in names.items():
        column = mapping.column_for(canonical_name)
        if column is None:
            continue
        series = frame[column].astype("string").replace({"": pd.NA})
        if canonical_name in {"churn_status", "attendance_status"}:
            # Two-state fields are translated to an explicit Yes/No vocabulary so
            # the cleaning layer never has to guess what "active" or "no-show" means.
            canonical = get_field(canonical_name)
            series = resolve_boolean(frame[column], canonical, column).series
        out[contract] = series

    if role == ROLE_ACTIVITY:
        if "visit_date" not in out.columns:
            out["visit_date"] = pd.NA
        if "member_id" not in out.columns:
            # A record sequence number, exactly like the reference activity source.
            out["member_id"] = [str(i + 1) for i in range(len(out))]
            assumptions.append(
                "No member/record identifier was present; a sequential record number was added so "
                "records can be traced. It is not a member identity and is not used for joins."
            )
        if "attendance_status" not in out.columns:
            out["attendance_status"] = "Present"
            assumptions.append(
                "No attendance outcome column was present; recorded sessions are treated as attended."
            )
    else:
        if "Churn" not in out.columns:
            assumptions.append(
                "No churn/retention outcome was present; churn-dependent analyses stay unavailable."
            )
            out["Churn"] = pd.NA
        if "Membership_Type" not in out.columns:
            out["Membership_Type"] = pd.NA
        if "Age" not in out.columns:
            out["Age"] = pd.NA

    return out.reset_index(drop=True), assumptions


def build_loaded_source(
    frame: pd.DataFrame,
    mapping: CanonicalMapping,
    report: CompatibilityReport,
    *,
    label: str,
    origin: str,
    url: str = "",
    license: str = "",
) -> "LoadedSource":  # noqa: F821 - imported lazily to avoid a cycle
    """Wrap a mapped dataset as a :class:`LoadedSource` for the pipeline."""
    from .loader import LoadedSource, SchemaReport

    contract, assumptions = contract_frame(frame, mapping)
    names = contract_names(mapping.role)
    present = [contract_name for contract_name in names.values() if contract_name in contract.columns]
    missing_required = [
        names[field.name]
        for field in required_fields_for_role(mapping.role)
        if field.name in names and names[field.name] not in contract.columns
    ]
    missing_optional = [
        contract_name
        for contract_name in names.values()
        if contract_name not in contract.columns and contract_name not in missing_required
    ]

    schema_report = SchemaReport(
        source=mapping.role,
        present_expected=present,
        missing_required=missing_required,
        missing_optional=missing_optional,
        unexpected=list(mapping.unmatched_columns),
        inferred_types={str(column): column_evidence(contract[column], str(column)).kind for column in contract.columns},
        status="FAIL" if missing_required else ("WARNING" if missing_optional else "PASS"),
    )

    return LoadedSource(
        name=mapping.role,
        path=None,
        frame=contract,
        schema_report=schema_report,
        origin=origin,
        dataset_label=label,
        dataset_url=url,
        dataset_license=license,
        warnings=list(mapping.notes) + list(assumptions) + list(report.warnings),
        role=mapping.role,
        mapping=mapping.as_dict(),
        capabilities=[c.as_dict() for c in report.capabilities],
        compatibility=report.as_dict(),
        assumptions=list(assumptions) + list(report.assumptions),
        member_key_repeatable=member_key_repeatable(frame, mapping.column_for("member_id")),
        source_columns=[str(c) for c in frame.columns],
        rows_in_source=int(len(frame)),
    )


# ---------------------------------------------------------------------------
# Convenience: describe a file for the upload UI
# ---------------------------------------------------------------------------
def describe_dataset(frame: pd.DataFrame) -> Dict[str, Any]:
    """Everything the upload screen needs to show about a file before running."""
    detection = detect_role(frame)
    mapping = suggest_mapping(frame, detection.role if detection.role in ROLES else None)
    report = assess_compatibility(frame, mapping)
    return {
        "rows": int(len(frame)),
        "columns": int(frame.shape[1]),
        "column_names": [str(c) for c in frame.columns],
        "detection": detection.as_dict(),
        "mapping": mapping.as_dict(),
        "compatibility": report.as_dict(),
        "requires_confirmation": mapping.requires_confirmation(),
    }


__all__ = [
    "HIGH",
    "MEDIUM",
    "LOW",
    "NONE",
    "CONFIDENCE_LABEL",
    "ColumnEvidence",
    "ColumnMatch",
    "RoleDetection",
    "CanonicalMapping",
    "CompatibilityReport",
    "Capability",
    "ValueMapping",
    "normalize_key",
    "header_similarity",
    "field_header_score",
    "column_evidence",
    "kind_support",
    "resolve_boolean",
    "detect_role",
    "suggest_mapping",
    "assess_compatibility",
    "capabilities_for",
    "merge_capabilities",
    "apply_dual_source_capabilities",
    "capability_frame",
    "capability_map",
    "unavailable_capabilities",
    "member_key_repeatable",
    "contract_frame",
    "build_loaded_source",
    "describe_dataset",
    "role_label",
    "MIN_MATCH_SCORE",
    "AMBIGUITY_MARGIN",
]
