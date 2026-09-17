import pytest

from dxp_analyzer import analyze, assess, build_report
from dxp_analyzer.export import export_result, write_summary
from dxp_analyzer.migration import DashboardAssessment

from _sample import make_sample_dxp


@pytest.fixture
def sample(tmp_path):
    return make_sample_dxp(tmp_path / "sample.dxp")


def test_analyze_extracts_expected_content(sample):
    result = analyze(sample)
    assert result.name == "sample"
    # one page titled "Overview"
    assert len(result.pages) == 1
    assert result.pages[0].title == "Overview"
    # two visuals: BarChart + ScatterPlot3D
    assert result.visual_counts.get("BarChart") == 1
    assert result.visual_counts.get("ScatterPlot3D") == 1
    # a user document property named region, cited by the script
    names = {p.name for p in result.document_properties}
    assert "region" in names
    # the embedded IronPython script was found
    assert any(s.language == "IronPython" for s in result.scripts)


def test_assessment_flags_non_native(sample):
    a = assess(sample)
    # ScatterPlot3D has no equivalent -> at least one non-native element
    assert a.counts()["non_native"] >= 1
    # clr.AddReference and Document.Properties -> features registered
    keys = set(a.entries.keys())
    assert "dotnet_libs" in keys
    assert "document_properties_code" in keys
    # score and effort are populated and bounded
    assert 0 <= a.score.index <= 100
    assert a.effort.likely_days > 0


@pytest.mark.parametrize("lang", ["en", "it"])
def test_build_report_both_languages(sample, lang):
    a = DashboardAssessment(analyze(sample))
    md = build_report([a], lang=lang)
    assert md.startswith("# ")
    assert "sample" in md
    assert "Menu" in md
    # localized complexity level appears
    if lang == "en":
        assert "Migration synthesis" in md
    else:
        assert "Sintesi di migrazione" in md


@pytest.mark.parametrize("lang", ["en", "it"])
def test_export_writes_files(sample, tmp_path, lang):
    result = analyze(sample)
    out = tmp_path / f"out_{lang}"
    export_result(result, out, lang)
    write_summary([result], out, lang)
    produced = list(out.rglob("*"))
    assert produced, "no output produced"
    # the extracted IronPython script file exists
    assert any(p.suffix == ".py" for p in produced)
