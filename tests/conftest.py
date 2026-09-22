"""Shared fixtures.

Two families of fixtures are provided:

* **Small hand-built fixtures** that reproduce every defect the real sources
  contain (whitespace, placeholder strings, duplicated records, unparseable
  dates, negative measures, missing values, PII). Unit tests assert on these so
  they never depend on the bundled Kaggle files being present.
* **Session-scoped fixtures** that load the real bundled sources when they exist
  and are skipped otherwise, so data and integration tests exercise the actual
  production path without making the suite unrunnable offline.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.cleaning import clean_activity_source, clean_membership_source  # noqa: E402
from src.common.config import ARTIFACTS_DIR, DB_PATH, RAW_DIR  # noqa: E402
from src.features import (  # noqa: E402
    build_member_features,
    build_platform_activity,
    build_real_member_features,
)
from src.ingestion import (  # noqa: E402
    ACTIVITY_SOURCE,
    MEMBERSHIP_SOURCE,
    get_source_schema,
    inspect_source_schema,
)
from src.ingestion.loader import LoadedSource  # noqa: E402
from src.integration import integrate_sources  # noqa: E402

OBSERVATION_DATE = pd.Timestamp("2025-07-10")

ACTIVITY_COLUMNS = list(ACTIVITY_SOURCE.expected_columns)
MEMBERSHIP_COLUMNS = list(MEMBERSHIP_SOURCE.expected_columns)


# ---------------------------------------------------------------------------
# Raw frames
# ---------------------------------------------------------------------------
@pytest.fixture
def dirty_activity_frame() -> pd.DataFrame:
    """Activity source rows containing every documented defect class."""
    rows = [
        # member_id, visit_date, age, gender, membership_type, workout_type,
        # duration, calories, check_in_time, attendance
        (1, "2024-01-05", 29, "Male", "Monthly", "Cardio", 60, 400, "07:30", "Present"),
        (2, "2024-01-05", 41, "Female", "Annual", "Yoga", 45, 210, "18:05", "Present"),
        (3, "2024-01-06", 35, "male", " monthly ", "cardio", 30, 150, "06:15", "present"),
        (4, "2024-01-06", 28, "Female", "Quarterly", "HIIT", 50, 520, "09:00", "Absent"),
        (5, "2024-01-07", 52, "Male", "Monthly", "Strength Training", 75, 610, "19:20", "Present"),
        (6, "2024-01-08", 33, "Female", "Annual", "Yoga", 40, None, "12:00", "Present"),
        (7, "2024-01-08", 24, "Male", "Monthly", "CrossFit", 90, 700, "17:45", "Present"),
        # negative duration — must be a validation finding, never silently dropped
        (8, "2024-01-09", 47, "Female", "Quarterly", "Cardio", -15, 100, "08:30", "Absent"),
        # unparseable date
        (9, "not-a-date", 31, "Male", "Monthly", "Yoga", 55, 240, "07:00", "Present"),
        # exact duplicate of member_id 1 (same workout_id)
        (1, "2024-01-05", 29, "Male", "Monthly", "Cardio", 60, 400, "07:30", "Present"),
        (10, "2024-02-01", None, "Female", "Annual", "HIIT", 65, 480, "20:10", "Present"),
        (11, "2024-02-02", 38, "Male", "N/A", "Strength Training", 80, 640, "06:45", "Present"),
    ]
    return pd.DataFrame(rows, columns=ACTIVITY_COLUMNS)


@pytest.fixture
def dirty_membership_frame() -> pd.DataFrame:
    """Membership source rows with PII, duplicates and a broken date order."""
    rows = [
        # id, name, age, gender, address, phone, type, join, last_visit,
        # favourite, avg_dur, avg_calories, weight, visits_per_month, churn
        (1, "Ana Ruiz", 29, "Female", "1 Main St", "555-0001", "Monthly", "2023-01-10", "2024-05-02", "Yoga", 45, 210, 12000, 12, "No"),
        (2, "Ben Cole", 41, "Male", "2 Oak Ave", "555-0002", "Annual", "2022-06-01", "2024-06-11", "Cardio", 60, 400, 18000, 18, "No"),
        (3, "Cara Diaz", 35, "female", "3 Elm Rd", "555-0003", " quarterly ", "2023-03-15", "2024-04-01", "HIIT", 50, 520, 15000, 9, "yes"),
        (4, "Dan Fox", 28, "Male", "4 Pine Ln", "555-0004", "Monthly", "2024-03-20", "2024-02-20", "CrossFit", 90, 700, 22000, 15, "Yes"),
        (5, "Eve Gray", 52, "Female", "5 Birch Way", "555-0005", "Annual", "2021-11-05", None, "Yoga", 40, 180, 9000, None, "No"),
        (6, "Finn Hale", None, "Male", "6 Cedar St", "555-0006", "Monthly", "2023-09-09", "2024-01-15", "Cardio", 55, 240, 11000, 4, "Yes"),
        (7, "Gia Ibarra", 24, "Female", "7 Ash Ct", "555-0007", "Quarterly", "2023-05-02", "2024-06-30", "Strength Training", 80, 640, 26000, 21, "No"),
        # duplicate member_id
        (1, "Ana Ruiz", 29, "Female", "1 Main St", "555-0001", "Monthly", "2023-01-10", "2024-05-02", "Yoga", 45, 210, 12000, 12, "No"),
    ]
    return pd.DataFrame(rows, columns=MEMBERSHIP_COLUMNS)


# ---------------------------------------------------------------------------
# Loaded sources
# ---------------------------------------------------------------------------
def _loaded(frame: pd.DataFrame, source) -> LoadedSource:
    return LoadedSource(
        name=source.name,
        path=None,
        frame=frame,
        schema_report=inspect_source_schema(frame, source),
        encoding="utf-8",
        delimiter=",",
        dataset_label=source.label,
        dataset_url=source.url,
        dataset_license=source.license,
        origin="test fixture",
    )


@pytest.fixture
def loaded_activity(dirty_activity_frame: pd.DataFrame) -> LoadedSource:
    return _loaded(dirty_activity_frame, ACTIVITY_SOURCE)


@pytest.fixture
def loaded_membership(dirty_membership_frame: pd.DataFrame) -> LoadedSource:
    return _loaded(dirty_membership_frame, MEMBERSHIP_SOURCE)


# ---------------------------------------------------------------------------
# Cleaned models
# ---------------------------------------------------------------------------
@pytest.fixture
def cleaned_activity(loaded_activity: LoadedSource):
    return clean_activity_source(loaded_activity)


@pytest.fixture
def cleaned_membership(loaded_membership: LoadedSource):
    return clean_membership_source(loaded_membership, observation_date=OBSERVATION_DATE)


# ---------------------------------------------------------------------------
# Integrated + engineered model
# ---------------------------------------------------------------------------
@pytest.fixture
def integration(loaded_activity: LoadedSource, loaded_membership: LoadedSource, cleaned_activity, cleaned_membership):
    return integrate_sources(
        activity_raw=loaded_activity.frame,
        membership_raw=loaded_membership.frame,
        activity_clean=cleaned_activity,
        dim_member_result=cleaned_membership["dim_member"],
        fact_membership_result=cleaned_membership["fact_membership"],
        seed=7,
    )


@pytest.fixture
def member_features(integration):
    real_features = build_real_member_features(integration.dim_member, integration.fact_membership)
    features, _ = build_member_features(
        real_features,
        integration.fact_workout_synthetic,
        reference_date=OBSERVATION_DATE,
    )
    return features


@pytest.fixture
def platform_tables(integration) -> dict:
    return build_platform_activity(integration.fact_workout)


# ---------------------------------------------------------------------------
# Real bundled sources (skipped when absent)
# ---------------------------------------------------------------------------
def _raw_sources_present() -> bool:
    return all((RAW_DIR / get_source_schema(name).filename).exists() for name in ("activity", "membership"))


requires_raw_sources = pytest.mark.skipif(
    not _raw_sources_present(),
    reason="bundled Kaggle sources are not present in data/raw; run `python scripts/ingest.py`",
)


@pytest.fixture(scope="session")
def real_pipeline_result():
    """Run the full pipeline once per session on the bundled sources."""
    if not _raw_sources_present():
        pytest.skip("bundled Kaggle sources are not present in data/raw")
    from src.pipeline import run_pipeline

    return run_pipeline(write_artifacts=False, build_database=False)


@pytest.fixture(scope="session")
def artifacts_dir() -> Path:
    return ARTIFACTS_DIR


@pytest.fixture(scope="session")
def sqlite_path() -> Path:
    if not DB_PATH.exists():
        pytest.skip(f"SQLite warehouse not built yet at {DB_PATH}")
    return DB_PATH
