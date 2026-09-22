"""FitPulse — Fitness Retention Intelligence Platform.

Top-level package. Sub-packages:

``common``       shared config, logging, IO
``ingestion``    source loading, source->canonical schema mapping
``validation``   profiling, rule-based validation, Python<->SQL KPI cross-check
``cleaning``     type/string/date/duplicate/outlier normalisation
``integration``  multi-source key analysis + documented synthetic bridge
``features``     frequency / recency / duration / consistency / streak / score
``analytics``    retention, engagement, correlation, time-series, funnel, ...
``alerts``       threshold-driven alert engine
``reporting``    business report rendering + optional email delivery
"""

__version__ = "1.0.0"
