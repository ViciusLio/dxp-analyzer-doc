import math

from dxp_analyzer_doc.migration.complexity import (
    ComplexityModel,
    Features,
    LEVEL_LOW,
    LEVEL_VERY_HIGH,
    ParametricEffortConfig,
    saturate,
)
from dxp_analyzer_doc.migration.query_complexity import (
    QueryComplexityConfig,
    Q_COMPLEX,
    Q_EASY,
    classify_query,
)


def test_saturate_bounds():
    assert saturate(0, 5) == 0.0
    assert saturate(5, 5) == 0.5
    assert saturate(1e9, 5) < 1.0
    assert 0.99 < saturate(1e6, 5) < 1.0


def test_empty_dashboard_is_low():
    model = ComplexityModel()
    score = model.score(Features())
    assert score.index == 0
    assert score.level == LEVEL_LOW


def test_index_is_bounded_0_100():
    model = ComplexityModel()
    huge = Features(pages=1000, non_native_visuals=1000, non_native_features=1000,
                    ironpython_scripts=500, ironpython_lines=100000, data_functions=200)
    score = model.score(huge)
    assert 0 <= score.index <= 100
    assert score.level == LEVEL_VERY_HIGH


def test_features_custom_queries_property():
    f = Features(queries_easy=2, queries_medium=1, queries_complex=3)
    assert f.custom_queries == 6


def test_effort_increases_and_has_band():
    model = ComplexityModel()
    small = model.effort_estimate(Features(pages=1))
    big = model.effort_estimate(Features(pages=20, data_functions=5, non_native_features=10,
                                         ironpython_scripts=10, ironpython_lines=5000, queries_complex=4))
    assert big.likely_days > small.likely_days
    assert small.min_days <= small.likely_days <= small.max_days
    # breakdown always includes the base term
    assert any(k == "base" for k, _, _ in small.breakdown)


def test_parametric_effort_matches_formula():
    cfg = ParametricEffortConfig(base=0.5, score_coeff=0.0, log_coeffs={"scripts": 0.5},
                                 query_easy_coeff=0.4, round_to=0.01)
    model = ComplexityModel(parametric_effort=cfg)
    f = Features(ironpython_scripts=2, queries_easy=3)
    e = model.effort_estimate(f)
    expected = 0.5 + 0.5 * math.log1p(2) + 0.4 * math.log1p(3)
    assert e.likely_days == round(expected, 2)
    assert any(k == "base" for k, _, _ in e.breakdown)
    assert e.min_days <= e.likely_days <= e.max_days


def test_complex_queries_are_linear_in_effort():
    cfg = ParametricEffortConfig(base=0.5, score_coeff=0.0, log_coeffs={}, query_complex_coeff=1.5, round_to=0.01)
    model = ComplexityModel(parametric_effort=cfg)
    # base (0.5) + 1.5 * 2 complex queries = 3.5 (easy/medium ln(1)=0)
    assert model.effort_estimate(Features(queries_complex=2)).likely_days == 3.5


def test_query_difficulty_raises_index():
    model = ComplexityModel()
    complex_idx = model.score(Features(queries_complex=5)).index
    easy_idx = model.score(Features(queries_easy=5)).index
    assert complex_idx > easy_idx


def test_parametric_score_term_contributes():
    heavy = Features(non_native_features=50, non_native_visuals=50, data_functions=20)
    light = Features()
    cfg = ParametricEffortConfig(score_coeff=0.1, log_coeffs={})
    model = ComplexityModel(parametric_effort=cfg)
    assert model.effort_estimate(heavy).likely_days > model.effort_estimate(light).likely_days


def test_query_classifier_easy_vs_complex():
    level_easy, _, _ = classify_query("SELECT a, b FROM t WHERE x = 1")
    assert level_easy == Q_EASY

    hard = """
        WITH cte AS (SELECT id, SUM(v) OVER (PARTITION BY id) AS s FROM t1)
        SELECT a.id, b.name, COUNT(*)
        FROM a
        JOIN b ON a.id = b.id
        JOIN c ON c.id = a.id
        JOIN d ON d.x = a.x
        WHERE a.x > 1 AND b.y < 2 OR c.z = 3
        GROUP BY a.id, b.name
    """
    level_hard, score_hard, metrics = classify_query(hard)
    assert level_hard == Q_COMPLEX
    assert metrics["joins"] == 3
    assert metrics["windows"] == 1
    assert score_hard > classify_query("SELECT a FROM t")[1]


def test_query_config_is_tunable():
    # make everything classify as complex by lowering the thresholds
    cfg = QueryComplexityConfig(easy_max=-1, medium_max=-1)
    level, _, _ = classify_query("SELECT 1", cfg)
    assert level == Q_COMPLEX
