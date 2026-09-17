"""Normalized complexity index and migration effort estimate.

The old model summed arbitrary weighted counts into an unbounded score. This
model instead:

1. groups the incidence variables into five **dimensions**;
2. normalizes each dimension to ``0..1`` with a saturating function, so no single
   dimension can explode the result;
3. combines them with configurable weights into a **0-100 complexity index**;
4. derives a **migration effort** estimate (person-days, min / likely / max) from
   one of two interchangeable models: an ``itemized`` per-feature cost model
   (default) or a ``parametric`` formula with diminishing returns.

Every coefficient lives in :class:`ComplexityConfig`, :class:`EffortConfig` or
:class:`ParametricEffortConfig` and can be overridden, so the model is tunable
without touching the logic.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Dict, List, Tuple

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
    custom_queries: int = 0
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
    # Level thresholds on the 0-100 index (upper bound inclusive).
    thresholds: List[Tuple[float, str]] = field(default_factory=lambda: [
        (25.0, LEVEL_LOW),
        (50.0, LEVEL_MEDIUM),
        (75.0, LEVEL_HIGH),
    ])

    def load_breadth(self, f: Features) -> float:
        return f.pages * 1.0 + f.total_visuals * 0.25 + f.text_areas * 0.5

    def load_data_model(self, f: Features) -> float:
        return f.source_tables * 1.0 + f.custom_queries * 1.5 + f.calculated_columns * 0.4 + f.data_functions * 2.0

    def load_custom_code(self, f: Features) -> float:
        return f.ironpython_scripts * 1.0 + f.javascript_scripts * 1.2 + f.total_script_lines / 80.0

    def load_interactivity(self, f: Features) -> float:
        return f.text_area_controls * 0.6 + f.user_properties * 0.5 + f.workaround_visuals * 0.4

    def load_migration_gap(self, f: Features) -> float:
        return (f.non_native_features * 2.0 + f.non_native_visuals * 1.5
                + f.workaround_features * 0.8 + f.adapted_columns * 0.5)


@dataclass
class EffortConfig:
    """Per-feature cost model for the effort estimate (person-days)."""

    setup: float = 2.0                    # base project setup (model, theme, publish)
    per_page: float = 0.5
    per_native_visual: float = 0.1
    per_workaround_visual: float = 0.4
    per_non_native_visual: float = 0.8
    per_text_area: float = 0.5
    per_text_area_control: float = 0.2
    per_user_property: float = 0.15
    per_script_base: float = 0.5          # per script, plus a line-based term
    per_script_100_lines: float = 0.5     # extra days per 100 lines of script
    script_line_cap: float = 3.0          # cap of the line-based term per script
    per_data_function: float = 3.0
    per_query: float = 0.5
    per_source_table: float = 0.3
    per_calculated_column: float = 0.15
    per_adapted_column: float = 0.4       # extra on top for columns needing rework
    per_workaround_feature: float = 0.5
    per_non_native_feature: float = 1.5
    # Uncertainty band around the "likely" estimate.
    low_factor: float = 0.8
    high_factor: float = 1.6
    round_to: float = 0.5


# Effort model machine keys.
EFFORT_ITEMIZED = "itemized"
EFFORT_PARAMETRIC = "parametric"


@dataclass
class ParametricEffortConfig:
    """Top-down parametric effort model (person-days).

    ``effort = base + score_coeff * index + Σ coeff_i * ln(1 + n_i)``

    The ``ln`` (natural log) gives diminishing returns: the 10th script costs
    less than the 1st. ``log_coeffs`` maps a driver name to its coefficient; a
    driver with coefficient 0 (or absent) is ignored. Driver names must be keys
    of :meth:`ComplexityModel._effort_drivers`.
    """

    base: float = 0.5
    score_coeff: float = 0.05
    log_coeffs: Dict[str, float] = field(default_factory=lambda: {
        "scripts": 0.5,
        "queries": 0.7,
        "data_functions": 0.9,
        "non_native_features": 1.2,
        "pages": 0.0,
    })
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
    """Compute the complexity index and effort estimate for a set of features.

    Two interchangeable effort models are available (``effort_model``):

    - ``"itemized"`` (default): bottom-up sum of per-feature costs; yields a full
      breakdown table. Configured by :class:`EffortConfig`.
    - ``"parametric"``: top-down formula ``base + a*index + Σ c_i*ln(1+n_i)`` with
      diminishing returns. Configured by :class:`ParametricEffortConfig`.
    """

    def __init__(self, complexity: ComplexityConfig | None = None, effort: EffortConfig | None = None,
                 parametric_effort: ParametricEffortConfig | None = None, effort_model: str = EFFORT_ITEMIZED):
        self.complexity = complexity or ComplexityConfig()
        self.effort = effort or EffortConfig()
        self.parametric_effort = parametric_effort or ParametricEffortConfig()
        self.effort_model = effort_model

    # -- complexity -------------------------------------------------------------

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

    def _round(self, value: float) -> float:
        return self._round_step(value, self.effort.round_to)

    @staticmethod
    def _effort_drivers(f: Features) -> Dict[str, int]:
        """Named counts the effort models can reference."""
        return {
            "scripts": f.ironpython_scripts + f.javascript_scripts,
            "queries": f.custom_queries,
            "data_functions": f.data_functions,
            "non_native_features": f.non_native_features,
            "workaround_features": f.workaround_features,
            "pages": f.pages,
            "source_tables": f.source_tables,
            "calculated_columns": f.calculated_columns,
        }

    def effort_estimate(self, f: Features) -> EffortEstimate:
        if self.effort_model == EFFORT_PARAMETRIC:
            return self._effort_parametric(f)
        return self._effort_itemized(f)

    def _effort_parametric(self, f: Features) -> EffortEstimate:
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
        likely = sum(c for _, _, c in contributions)
        breakdown = [(k, q, round(c, 2)) for k, q, c in contributions if c > 0 or k == "base"]
        return EffortEstimate(
            min_days=self._round_step(likely * cfg.low_factor, cfg.round_to),
            likely_days=self._round_step(likely, cfg.round_to),
            max_days=self._round_step(likely * cfg.high_factor, cfg.round_to),
            breakdown=breakdown,
        )

    def _effort_itemized(self, f: Features) -> EffortEstimate:
        e = self.effort
        script_count = f.ironpython_scripts + f.javascript_scripts
        script_lines = f.total_script_lines
        script_days = script_count * e.per_script_base + min(
            script_count * e.script_line_cap,
            script_lines / 100.0 * e.per_script_100_lines,
        )
        items: List[Tuple[str, float, float]] = [
            ("setup", 1, e.setup),
            ("pages", f.pages, f.pages * e.per_page),
            ("visuals_native", f.native_visuals, f.native_visuals * e.per_native_visual),
            ("visuals_workaround", f.workaround_visuals, f.workaround_visuals * e.per_workaround_visual),
            ("visuals_non_native", f.non_native_visuals, f.non_native_visuals * e.per_non_native_visual),
            ("text_areas", f.text_areas, f.text_areas * e.per_text_area),
            ("text_area_controls", f.text_area_controls, f.text_area_controls * e.per_text_area_control),
            ("user_properties", f.user_properties, f.user_properties * e.per_user_property),
            ("scripts", script_count, script_days),
            ("data_functions", f.data_functions, f.data_functions * e.per_data_function),
            ("queries", f.custom_queries, f.custom_queries * e.per_query),
            ("source_tables", f.source_tables, f.source_tables * e.per_source_table),
            ("calculated_columns", f.calculated_columns, f.calculated_columns * e.per_calculated_column),
            ("adapted_columns", f.adapted_columns, f.adapted_columns * e.per_adapted_column),
            ("workaround_features", f.workaround_features, f.workaround_features * e.per_workaround_feature),
            ("non_native_features", f.non_native_features, f.non_native_features * e.per_non_native_feature),
        ]
        items = [(key, qty, self._round(days)) for key, qty, days in items if days > 0 or key == "setup"]
        likely = sum(days for _, _, days in items)
        return EffortEstimate(
            min_days=self._round(likely * e.low_factor),
            likely_days=self._round(likely),
            max_days=self._round(likely * e.high_factor),
            breakdown=items,
        )
