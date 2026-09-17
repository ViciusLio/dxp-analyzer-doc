"""dxp-analyzer-doc: analyze TIBCO Spotfire ``.dxp`` dashboards and assess their
migration to Power BI.

Quick start::

    from dxp_analyzer_doc import analyze, assess

    result = analyze("dashboard.dxp")          # structured inventory
    assessment = assess("dashboard.dxp")        # + complexity, effort, mapping
    print(assessment.score.index, assessment.effort.likely_days)
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from .analyzer import DxpAnalyzer
from .model import AnalysisResult
from .migration import (
    ComplexityConfig,
    ComplexityModel,
    ComplexityScore,
    DashboardAssessment,
    EffortConfig,
    EffortEstimate,
    Features,
    ParametricEffortConfig,
    build_report,
)

__version__ = "0.1.0"

__all__ = [
    "DxpAnalyzer",
    "AnalysisResult",
    "DashboardAssessment",
    "ComplexityModel",
    "ComplexityScore",
    "ComplexityConfig",
    "EffortConfig",
    "ParametricEffortConfig",
    "EffortEstimate",
    "Features",
    "analyze",
    "assess",
    "build_report",
    "__version__",
]


def analyze(path) -> AnalysisResult:
    """Analyze a ``.dxp`` file and return its structured :class:`AnalysisResult`."""
    return DxpAnalyzer(path).analyze()


def assess(path, model: Optional[ComplexityModel] = None) -> DashboardAssessment:
    """Analyze a ``.dxp`` file and return a migration :class:`DashboardAssessment`."""
    result = DxpAnalyzer(path).analyze()
    return DashboardAssessment(result, model=model)
