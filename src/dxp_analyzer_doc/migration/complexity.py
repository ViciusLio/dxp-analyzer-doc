"""Normalized complexity index and migration effort estimate.

The old model summed arbitrary weighted counts into an unbounded score. This
model instead:

1. groups the incidence variables into five **dimensions**;
2. normalizes each dimension to ``0..1`` with a saturating function, so no single
   dimension can explode the result;
3. combines them with configurable weights into a **0-100 complexity index**;
4. derives a **migration effort** estimate (person-days, min / likely / max) from
   a single **parametric** formula with diminishing returns:

   ``effort = base + score_coeff * index + Σ coeff_i * ln(1 + n_i) + query terms``

Custom queries are classified (easy / medium / complex) and weighted separately:
easy and medium contribute with diminishing returns (``ln``), while every
**complex** query adds a roughly linear cost, because a complex query means the
underlying semantic model has to be decomposed. Query difficulty also feeds the
``data_model`` dimension of the index.

Every coefficient lives in :class:`ComplexityConfig`, :class:`ParametricEffortConfig`
or :class:`~dxp_analyzer_doc.migration.query_complexity.QueryComplexityConfig` and
can be overridden, so the model is tunable without touching the logic.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Dict, List, Tuple

from .query_complexity import QueryComplexityConfig

# Complexity level machine keys (localized via i18n "level.*").
LEVEL_LOW = "low"
LEVEL_MEDIUM = "medium"
LEVEL_HIGH = "high"
LEVEL_VERY_HIGH = "very_high"


def saturate(load: float, k: float) -> float:
    """Map an unbounded non-negative load to ``[0, 1)``; equals 0.5 when load == k."""
    if load <= 0:
        return 0.0
    return load / (load + k)


@dataclass
class Features:
    """Raw incidence variables extracted from a dashboard assessment."""

    pages: int = 0
    native_visuals: int = 0
    workaround_visuals: int = 0
    non_native_visuals: int = 0
    text_areas: int = 0
    text_area_controls: int = 0
    user_properties: int = 0
    ironpython_scripts: int = 0
    ironpython_lines: int = 0
    javascript_scripts: int = 0
    javascript_lines: int = 0
    data_functions: int = 0
    # Custom queries split by classified difficulty (see query_complexity).
    queries_easy: int = 0
    queries_medium: int = 0
    queries_complex: int = 0
    source_tables: int = 0
    calculated_columns: int = 0
    adapted_columns: int = 0
    workaround_features: int = 0
    non_native_features: int = 0

    @property
    def total_visuals(self) -> int:
        return self.native_visuals + self.workaround_visuals + self.non_native_visuals

    @property
    def total_script_lines(self) -> int:
        return self.ironpython_lines + self.javascript_lines

    @property
    def custom_queries(self) -> int:
        return self.queries_easy + self.queries_medium + self.queries_complex


@dataclass
class ComplexityConfig:
    """Weights and saturation constants for the complexity index (all tunable)."""

    # Per-dimension weight (must sum to ~1) and saturation constant k.
    dimension_weights: Dict[str, float] = field(default_factory=lambda: {
        "breadth": 0.15,
        "data_model": 0.20,
        "custom_code": 0.25,
        "interactivity": 0.15,
        "migration_gap": 0.25,
    })
    saturation: Dict[str, float] = field(default_factory=lambda: {
        "breadth": 8.0,
        "data_model": 6.0,
        "custom_code": 5.0,
        "interactivity": 6.0,
        "migration_gap": 5.0,
    })
    # Query difficulty weights feeding the data_model dimension.
    query_load_weights: Dict[str, float] = field(default_factory=lambda: {
        "easy": 1.0,
        "medium": 1.5,
        "complex": 2.5,
    })
    # Level thresholds on the 0-100 index (upper bound inclusive).
    thresholds: List[Tuple[float, str]] = field(default_factory=lambda: [
        (25.0, LEVEL_LOW),
        (50.0, LEVEL_MEDIUM),
        (75.0, LEVEL_HIGH),
    ])

    def load_breadth(self, f: Features) -> float:
        return f.pages * 1.0 + f.total_visuals * 0.25 + f.text_areas * 0.5

    def load_data_model(self, f: Features) -> float:
        qw = self.query_load_weights
        query_load = (f.queries_easy * qw.get("easy", 1.0)
                      + f.queries_medium * qw.get("medium", 1.5)
                      + f.queries_complex * qw.get("complex", 2.5))
        return f.source_tables * 1.0 + query_load + f.calculated_columns * 0.4 + f.data_functions * 2.0

    def load_custom_code(self, f: Features) -> float:
        return f.ironpython_scripts * 1.0 + f.javascript_scripts * 1.2 + f.total_script_lines / 80.0

    def load_interactivity(self, f: Features) -> float:
        return f.text_area_controls * 0.6 + f.user_properties * 0.5 + f.workaround_visuals * 0.4

    def load_migration_gap(self, f: Features) -> float:
        return (f.non_native_features * 2.0 + f.non_native_visuals * 1.5
                + f.workaround_features * 0.8 + f.adapted_columns * 0.5)


@dataclass
class ParametricEffortConfig:
    """Parametric effort model (person-days).

    ``effort = base + score_coeff * index
               + Σ coeff_i * ln(1 + n_i)                 # generic drivers
               + q_easy * ln(1 + n_easy)                 # easy queries (diminishing)
               + q_medium * ln(1 + n_medium)             # medium queries (diminishing)
               + q_complex * n_complex``                 # complex queries (linear)

    ``ln`` (natural log) gives diminishing returns. Complex queries are linear on
    purpose: each one implies decomposing the underlying semantic model, a cost
    that does not amortize. ``log_coeffs`` maps a generic driver name (a key of
    :meth:`ComplexityModel._effort_drivers`) to its coefficient; 0 disables it.
    """

    base: float = 0.5
    score_coeff: float = 0.05
    log_coeffs: Dict[str, float] = field(default_factory=lambda: {
        "scripts": 0.5,
        "data_functions": 0.9,
        "non_native_features": 1.2,
        "pages": 0.0,
    })
    query_easy_coeff: float = 0.4       # log term
    query_medium_coeff: float = 0.8     # log term
    query_complex_coeff: float = 1.5    # linear term (per complex query)
    low_factor: float = 0.8
    high_factor: float = 1.6
    round_to: float = 0.5


@dataclass
class ComplexityScore:
    index: float                          # 0-100
    level: str                            # machine key: low/medium/high/very_high
    dimensions: Dict[str, float]          # normalized 0-1 per dimension
    loads: Dict[str, float]               # raw loads per dimension (diagnostics)


@dataclass
class EffortEstimate:
    min_days: float
    likely_days: float
    max_days: float
    breakdown: List[Tuple[str, float, float]]  # (item_key, quantity, days)


class ComplexityModel:
    """Compute the complexity index and (parametric) effort for a set of features.

    Query classification thresholds live in ``query_config`` and are used by the
    assessment layer via :meth:`classify_query`.
    """

    def __init__(self, complexity: ComplexityConfig | None = None,
                 parametric_effort: ParametricEffortConfig | None = None,
                 query_config: QueryComplexityConfig | None = None):
        self.complexity = complexity or ComplexityConfig()
        self.parametric_effort = parametric_effort or ParametricEffortConfig()
        self.query_config = query_config or QueryComplexityConfig()

    # -- query classification ---------------------------------------------------

    def classify_query(self, sql: str):
        """Return ``(level, score, metrics)`` for a SQL query."""
        from .query_complexity import classify_query
        return classify_query(sql, self.query_config)

    # -- complexity index -------------------------------------------------------

    def level(self, index: float) -> str:
        for threshold, name in self.complexity.thresholds:
            if index <= threshold:
                return name
        return LEVEL_VERY_HIGH

    def score(self, f: Features) -> ComplexityScore:
        cfg = self.complexity
        loads = {
            "breadth": cfg.load_breadth(f),
            "data_model": cfg.load_data_model(f),
            "custom_code": cfg.load_custom_code(f),
            "interactivity": cfg.load_interactivity(f),
            "migration_gap": cfg.load_migration_gap(f),
        }
        dimensions = {name: saturate(load, cfg.saturation[name]) for name, load in loads.items()}
        total_weight = sum(cfg.dimension_weights.values()) or 1.0
        index = 100.0 * sum(cfg.dimension_weights.get(name, 0.0) * value for name, value in dimensions.items()) / total_weight
        index = round(index, 1)
        return ComplexityScore(index=index, level=self.level(index),
                               dimensions={k: round(v, 3) for k, v in dimensions.items()},
                               loads={k: round(v, 2) for k, v in loads.items()})

    # -- effort -----------------------------------------------------------------

    @staticmethod
    def _round_step(value: float, step: float) -> float:
        step = step or 0.5
        return round(round(value / step) * step, 2)

    @staticmethod
    def _effort_drivers(f: Features) -> Dict[str, int]:
        """Named counts the effort formula can reference (generic drivers only)."""
        return {
            "scripts": f.ironpython_scripts + f.javascript_scripts,
            "data_functions": f.data_functions,
            "non_native_features": f.non_native_features,
            "workaround_features": f.workaround_features,
            "pages": f.pages,
            "source_tables": f.source_tables,
            "calculated_columns": f.calculated_columns,
        }

    def effort_estimate(self, f: Features) -> EffortEstimate:
        cfg = self.parametric_effort
        index = self.score(f).index
        drivers = self._effort_drivers(f)
        contributions: List[Tuple[str, float, float]] = [
            ("base", 1, cfg.base),
            ("complexity_score", index, cfg.score_coeff * index),
        ]
        for key, coeff in cfg.log_coeffs.items():
            if not coeff:
                continue
            n = drivers.get(key, 0)
            contributions.append((key, n, coeff * math.log1p(n)))
        # custom queries by difficulty: easy/medium with diminishing returns,
        # complex linear (each complex query means decomposing the semantic model).
        contributions.append(("queries_easy", f.queries_easy, cfg.query_easy_coeff * math.log1p(f.queries_easy)))
        contributions.append(("queries_medium", f.queries_medium, cfg.query_medium_coeff * math.log1p(f.queries_medium)))
        contributions.append(("queries_complex", f.queries_complex, cfg.query_complex_coeff * f.queries_complex))
        likely = sum(c for _, _, c in contributions)
        breakdown = [(k, q, round(c, 2)) for k, q, c in contributions if c > 0 or k == "base"]
        return EffortEstimate(
            min_days=self._round_step(likely * cfg.low_factor, cfg.round_to),
            likely_days=self._round_step(likely, cfg.round_to),
            max_days=self._round_step(likely * cfg.high_factor, cfg.round_to),
            breakdown=breakdown,
        )
