"""Central configuration for FitPulse.

Everything configurable lives here so that no analytical weight, threshold or
path is hard-coded inside the analytics or UI layers.

Secrets are never stored in this module: values are read from the process
environment, optionally seeded from a local ``.env`` file (which is
git-ignored). See ``.env.example`` for the full key list.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any, Dict, Optional

# --------------------------------------------------------------------------
# Paths
# --------------------------------------------------------------------------
PROJECT_ROOT = Path(__file__).resolve().parents[2]

DATA_DIR = PROJECT_ROOT / "data"
RAW_DIR = DATA_DIR / "raw"
INTERIM_DIR = DATA_DIR / "interim"
PROCESSED_DIR = DATA_DIR / "processed"
ARTIFACTS_DIR = PROJECT_ROOT / "artifacts"
LOGS_DIR = PROJECT_ROOT / "logs"
SQL_DIR = PROJECT_ROOT / "sql"

#: SQLite database produced by the SQL load stage.
DB_PATH = PROCESSED_DIR / "fitpulse.db"

#: Canonical raw file names expected in ``data/raw``.
ACTIVITY_RAW_FILENAME = "daily_gym_attendance_workout_data.csv"
MEMBERSHIP_RAW_FILENAME = "gym_members_dataset.csv"


def ensure_directories() -> None:
    """Create every runtime directory. Safe to call repeatedly."""
    for path in (DATA_DIR, RAW_DIR, INTERIM_DIR, PROCESSED_DIR, ARTIFACTS_DIR, LOGS_DIR):
        path.mkdir(parents=True, exist_ok=True)


# --------------------------------------------------------------------------
# Minimal .env loader (avoids a hard dependency on python-dotenv)
# --------------------------------------------------------------------------
def load_dotenv(path: Optional[Path] = None, override: bool = False) -> Dict[str, str]:
    """Load ``KEY=VALUE`` pairs from ``.env`` into ``os.environ``.

    Deliberately tiny and dependency-free so the ingestion/analytics layers can
    run in a bare environment. Values already present in the environment win
    unless ``override`` is set.
    """
    env_path = Path(path) if path else PROJECT_ROOT / ".env"
    loaded: Dict[str, str] = {}
    if not env_path.exists():
        return loaded

    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if not key:
            continue
        loaded[key] = value
        if override or key not in os.environ:
            os.environ[key] = value
    return loaded


# --------------------------------------------------------------------------
# Typed accessors
# --------------------------------------------------------------------------
def _env_str(key: str, default: Optional[str] = None) -> Optional[str]:
    value = os.environ.get(key)
    if value is None or value == "":
        return default
    return value


def _env_float(key: str, default: float) -> float:
    raw = _env_str(key)
    if raw is None:
        return default
    try:
        return float(raw)
    except (TypeError, ValueError):
        return default


def _env_int(key: str, default: int) -> int:
    raw = _env_str(key)
    if raw is None:
        return default
    try:
        return int(float(raw))
    except (TypeError, ValueError):
        return default


@dataclass
class EngagementWeights:
    """Weights of the composite engagement score.

    These are **product-design assumptions**, not empirically validated causal
    weights, and are configurable through the environment.
    """

    frequency: float = 0.30
    consistency: float = 0.25
    streak: float = 0.20
    recency: float = 0.15
    duration: float = 0.10

    def as_dict(self) -> Dict[str, float]:
        return asdict(self)

    def normalized(self) -> "EngagementWeights":
        """Return weights rescaled to sum to 1.0."""
        total = self.frequency + self.consistency + self.streak + self.recency + self.duration
        if total <= 0:
            return EngagementWeights()
        return EngagementWeights(
            frequency=self.frequency / total,
            consistency=self.consistency / total,
            streak=self.streak / total,
            recency=self.recency / total,
            duration=self.duration / total,
        )


@dataclass
class SegmentThresholds:
    """Engagement-score cut points for the four behavioural segments."""

    highly_engaged: float = 70.0
    regular: float = 45.0
    at_risk: float = 25.0

    def label_for(self, score: float) -> str:
        if score >= self.highly_engaged:
            return "A - Highly Engaged"
        if score >= self.regular:
            return "B - Regular"
        if score >= self.at_risk:
            return "C - At Risk"
        return "D - Dormant"

    def as_dict(self) -> Dict[str, float]:
        return asdict(self)


@dataclass
class AlertThresholds:
    """Operational alert thresholds (metric-specific, user-configurable)."""

    inactivity_days: int = 14
    engagement_drop_pct: float = 50.0
    churn_rate_pct: float = 30.0
    missing_data_pct: float = 10.0
    activity_drop_pct: float = 25.0

    def as_dict(self) -> Dict[str, float]:
        return asdict(self)


@dataclass
class Settings:
    """Aggregated runtime settings."""

    env: str = "local"
    log_level: str = "INFO"
    random_seed: int = 42
    as_of_date: Optional[str] = None
    db_path: Path = field(default_factory=lambda: DB_PATH)
    db_url: Optional[str] = None
    engagement_weights: EngagementWeights = field(default_factory=EngagementWeights)
    segment_thresholds: SegmentThresholds = field(default_factory=SegmentThresholds)
    alert_thresholds: AlertThresholds = field(default_factory=AlertThresholds)
    email: Dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> Dict[str, Any]:
        payload = asdict(self)
        payload["db_path"] = str(self.db_path)
        return payload


_settings: Optional[Settings] = None


def get_settings(reload: bool = False) -> Settings:
    """Return the process-wide :class:`Settings` singleton."""
    global _settings
    if _settings is not None and not reload:
        return _settings

    load_dotenv()
    ensure_directories()

    _settings = Settings(
        env=_env_str("FITPULSE_ENV", "local") or "local",
        log_level=(_env_str("FITPULSE_LOG_LEVEL", "INFO") or "INFO").upper(),
        random_seed=_env_int("FITPULSE_RANDOM_SEED", 42),
        as_of_date=_env_str("FITPULSE_AS_OF_DATE"),
        db_path=Path(_env_str("FITPULSE_DB_PATH", str(DB_PATH)) or str(DB_PATH)),
        db_url=_env_str("FITPULSE_DB_URL"),
        engagement_weights=EngagementWeights(
            frequency=_env_float("FITPULSE_W_FREQUENCY", 0.30),
            consistency=_env_float("FITPULSE_W_CONSISTENCY", 0.25),
            streak=_env_float("FITPULSE_W_STREAK", 0.20),
            recency=_env_float("FITPULSE_W_RECENCY", 0.15),
            duration=_env_float("FITPULSE_W_DURATION", 0.10),
        ),
        segment_thresholds=SegmentThresholds(
            highly_engaged=_env_float("FITPULSE_SEG_HIGHLY_ENGAGED", 70.0),
            regular=_env_float("FITPULSE_SEG_REGULAR", 45.0),
            at_risk=_env_float("FITPULSE_SEG_AT_RISK", 25.0),
        ),
        alert_thresholds=AlertThresholds(
            inactivity_days=_env_int("FITPULSE_ALERT_INACTIVITY_DAYS", 14),
            engagement_drop_pct=_env_float("FITPULSE_ALERT_ENGAGEMENT_DROP_PCT", 50.0),
            churn_rate_pct=_env_float("FITPULSE_ALERT_CHURN_RATE_PCT", 30.0),
            missing_data_pct=_env_float("FITPULSE_ALERT_MISSING_DATA_PCT", 10.0),
            activity_drop_pct=_env_float("FITPULSE_ALERT_ACTIVITY_DROP_PCT", 25.0),
        ),
        email={
            "smtp_host": _env_str("FITPULSE_SMTP_HOST"),
            "smtp_port": _env_int("FITPULSE_SMTP_PORT", 587),
            "smtp_user": _env_str("FITPULSE_SMTP_USER"),
            "smtp_password": _env_str("FITPULSE_SMTP_PASSWORD"),
            "sender": _env_str("FITPULSE_REPORT_FROM"),
            "recipients": [
                addr.strip()
                for addr in (_env_str("FITPULSE_REPORT_TO", "") or "").split(",")
                if addr.strip()
            ],
        },
    )
    return _settings


def reload_settings() -> Settings:
    """Force a re-read of environment configuration."""
    return get_settings(reload=True)
