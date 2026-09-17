import math

from dxp_analyzer_doc.migration.complexity import (
    ComplexityModel,
    Features,
    LEVEL_LOW,
    LEVEL_VERY_HIGH,
    ParametricEffortConfig,
    saturate,
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


def test_effort_increases_and_has_band():
    model = ComplexityModel()
    small = model.effort_estimate(Features(pages=1))
    big = model.effort_estimate(Features(pages=20, data_functions=5, non_native_features=10, ironpython_scripts=10, ironpython_lines=5000))
    assert big.likely_days > small.likely_days
    assert small.min_days <= small.likely_days <= small.max_days
    # breakdown always includes project setup
    assert any(k == "setup" for k, _, _ in small.breakdown)


def test_config_is_tunable():
    model = ComplexityModel()
    model.effort.per_data_function = 10.0
    e = model.effort_estimate(Features(data_functions=2))
    # setup (2) + 2 * 10 = 22
    assert e.likely_days == 22.0


def test_parametric_effort_matches_formula():
    cfg = ParametricEffortConfig(base=0.5, score_coeff=0.0,
                                 log_coeffs={"scripts": 0.5, "queries": 0.7}, round_to=0.01)
    model = ComplexityModel(parametric_effort=cfg, effort_model="parametric")
    f = Features(ironpython_scripts=2, custom_queries=3)  # scripts=2, queries=3
    e = model.effort_estimate(f)
    expected = 0.5 + 0.5 * math.log1p(2) + 0.7 * math.log1p(3)
    assert e.likely_days == round(expected, 2)
    assert any(k == "base" for k, _, _ in e.breakdown)
    assert e.min_days <= e.likely_days <= e.max_days


def test_effort_models_are_selectable_and_differ():
    f = Features(pages=10, ironpython_scripts=8, ironpython_lines=2000,
                 data_functions=3, custom_queries=4, non_native_features=5)
    itemized = ComplexityModel(effort_model="itemized").effort_estimate(f)
    parametric = ComplexityModel(effort_model="parametric").effort_estimate(f)
    # both produce positive estimates, via different math
    assert itemized.likely_days > 0 and parametric.likely_days > 0
    assert itemized.breakdown != parametric.breakdown


def test_parametric_score_term_contributes():
    heavy = Features(non_native_features=50, non_native_visuals=50, data_functions=20)
    light = Features()
    cfg = ParametricEffortConfig(score_coeff=0.1, log_coeffs={})
    model = ComplexityModel(parametric_effort=cfg, effort_model="parametric")
    assert model.effort_estimate(heavy).likely_days > model.effort_estimate(light).likely_days
