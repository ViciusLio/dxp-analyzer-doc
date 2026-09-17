from dxp_analyzer.migration.complexity import (
    ComplexityModel,
    Features,
    LEVEL_LOW,
    LEVEL_VERY_HIGH,
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
