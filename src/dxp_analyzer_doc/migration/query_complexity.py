"""Heuristic complexity classification of a SQL custom query.

A custom query behind a Spotfire data table hints at how much the underlying
semantic model must be decomposed when migrating: a heavy query (many joins,
subqueries, window functions, grouping) usually means real modelling work in
Power BI / Databricks, while a flat ``SELECT ... FROM one_table`` is trivial.

The classifier is dependency-free (regex heuristics) and returns one of three
levels: ``easy`` / ``medium`` / ``complex``. Every weight and threshold lives in
:class:`QueryComplexityConfig` and can be overridden.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Dict, Tuple

# Query complexity level machine keys (localized via i18n "qlevel.*").
Q_EASY = "easy"
Q_MEDIUM = "medium"
Q_COMPLEX = "complex"
QUERY_LEVELS = (Q_EASY, Q_MEDIUM, Q_COMPLEX)

_AGG = r"\b(?:SUM|AVG|COUNT|MIN|MAX|STDDEV|STDEV|VARIANCE|VAR|MEDIAN|PERCENTILE\w*)\s*\("


def query_metrics(sql: str) -> Dict[str, int]:
    """Extract the raw structural metrics used to score a query."""
    sql = sql or ""
    from_count = len(re.findall(r"\bFROM\b", sql, re.I))
    joins = len(re.findall(r"\bJOIN\b", sql, re.I))
    selects = len(re.findall(r"\bSELECT\b", sql, re.I))
    where = 1 if re.search(r"\bWHERE\b", sql, re.I) else 0
    group = re.search(r"\bGROUP\s+BY\s+(.*?)(?:\bORDER\s+BY\b|\bHAVING\b|\bLIMIT\b|$)", sql, re.I | re.S)
    group_cols = (group.group(1).count(",") + 1) if group else 0
    return {
        "tables": from_count + joins,          # rough table count (FROM + each JOIN)
        "joins": joins,
        "subqueries": max(0, selects - 1),     # nested SELECTs
        "ctes": len(re.findall(r"\bWITH\b", sql, re.I)),
        "windows": len(re.findall(r"\bOVER\s*\(", sql, re.I)),
        "set_ops": len(re.findall(r"\b(?:UNION|INTERSECT|EXCEPT)\b", sql, re.I)),
        "conditions": len(re.findall(r"\b(?:AND|OR)\b", sql, re.I)) + where,
        "group_cols": group_cols,
        "aggregations": len(re.findall(_AGG, sql, re.I)),
        "case": len(re.findall(r"\bCASE\b", sql, re.I)),
        "distinct": 1 if re.search(r"\bDISTINCT\b", sql, re.I) else 0,
        "length": len(sql),
    }


@dataclass
class QueryComplexityConfig:
    """Weights and thresholds for SQL query classification (all tunable)."""

    weights: Dict[str, float] = field(default_factory=lambda: {
        "joins": 1.2,
        "subqueries": 0.8,
        "ctes": 1.0,
        "windows": 2.0,
        "set_ops": 1.0,
        "conditions": 0.4,
        "group_cols": 0.6,
        "aggregations": 0.3,
        "case": 0.5,
        "distinct": 0.3,
    })
    # Extra points per N characters of SQL text.
    length_per_chars: float = 800.0
    length_weight: float = 1.0
    # Score thresholds (upper bound inclusive) for easy and medium.
    easy_max: float = 3.0
    medium_max: float = 7.0

    def score(self, metrics: Dict[str, int]) -> float:
        total = sum(self.weights.get(k, 0.0) * metrics.get(k, 0) for k in self.weights)
        if self.length_per_chars:
            total += self.length_weight * (metrics.get("length", 0) / self.length_per_chars)
        return round(total, 2)

    def level(self, score: float) -> str:
        if score <= self.easy_max:
            return Q_EASY
        if score <= self.medium_max:
            return Q_MEDIUM
        return Q_COMPLEX


def classify_query(sql: str, config: QueryComplexityConfig | None = None) -> Tuple[str, float, Dict[str, int]]:
    """Return ``(level, score, metrics)`` for a SQL query."""
    config = config or QueryComplexityConfig()
    metrics = query_metrics(sql)
    score = config.score(metrics)
    return config.level(score), score, metrics
