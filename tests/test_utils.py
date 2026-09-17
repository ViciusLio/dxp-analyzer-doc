from dxp_analyzer_doc._utils import (
    base_type,
    clean_name,
    declared_language,
    field_key,
    guess_language,
    last_segment,
    normalize_path,
)


def test_type_helpers():
    assert base_type("Spotfire.Dxp.Application.Visuals.BarChart, Spotfire.Dxp") == "Spotfire.Dxp.Application.Visuals.BarChart"
    assert last_segment("Spotfire.Dxp.Application.Visuals.BarChart") == "BarChart"
    assert field_key("m_Name") == "name"
    assert normalize_path("\\Data\\Foo.XML") == "data/foo.xml"


def test_clean_name():
    assert clean_name('a/b:c*?.') == "a_b_c__"
    assert clean_name("") == "senza nome"


def test_guess_language():
    py = "import clr\nfrom x import y\ndef f():\n    pass"
    assert guess_language(py) == "IronPython"
    js = "var x = 1; function f(){ document.getElementById('a'); } let y = () => 2;"
    assert guess_language(js) == "JavaScript"
    assert guess_language("hello world") is None


def test_declared_language():
    assert declared_language("JavaScript") == "JavaScript"
    assert declared_language("ironpython") == "IronPython"
    assert declared_language("python") == "Python"
    assert declared_language("") is None
