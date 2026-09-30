# dxp-analyzer-doc

Analyze **TIBCO Spotfire `.dxp`** dashboards and assess their **migration to
Power BI** (with Databricks as the data back-end).

A `.dxp` file is a ZIP archive of XML documents. `dxp-analyzer-doc` walks that
structure and produces:

- a **structured inventory** (pages, visuals, IronPython/JavaScript scripts,
  data functions, document properties, calculated columns, custom queries,
  source tables, connections) exported as `.xlsx` (or `.csv`);
- a **migration assessment**: every Spotfire capability mapped to its Power BI /
  Databricks equivalent and classified as *native*, *workaround* or *not native*;
- a **normalized complexity index (0–100)** and a **migration effort estimate**
  (person-days, min / likely / max);
- a **migration document** in Markdown with a pros/cons synthesis per dashboard.

Output language is selectable: **English (default)** or **Italian** (`--lang it`).

> Italiano: libreria per analizzare dashboard Spotfire `.dxp` e valutarne la
> migrazione a Power BI. Output in inglese (default) o italiano (`--lang it`).

## Install

```bash
pip install -e .            # no dependencies; tables are written as .csv
```

The migration document is always Markdown (`.md`). Tables default to `.csv`
(`;`-separated, UTF-8-BOM so Excel opens them directly). If you prefer `.xlsx`
output instead, add the optional extra:

```bash
pip install -e ".[xlsx]"    # pulls in openpyxl for .xlsx tables
```

## Command line

```bash
# Inventory tables + extracted code files
dxp-analyzer-doc analyze dashboard.dxp -o out --lang en

# Migration document (Markdown) for one or many dashboards
dxp-analyzer-doc document a.dxp b.dxp -o migration.md --lang it

# Both, for every .dxp in a folder
dxp-analyzer-doc all ./dashboards -o out
```

`files` accepts `.dxp` files, glob patterns, or directories (all `*.dxp` inside).
Add `--extract-archive` to also unpack the raw `.dxp` contents.

**Output location.** By default the output is written **next to the input
`.dxp` files**, not in the current working directory: `analyze`/`all` create
`<input folder>/dxp-output/`, and `document` writes
`<input folder>/migration_documentation.md`. A relative `-o` also resolves under
the input folder; pass an absolute `-o` to write anywhere.

## Python API

```python
from dxp_analyzer_doc import analyze, assess, build_report

# 1. Structured inventory
result = analyze("dashboard.dxp")
print(len(result.pages), result.total_visuals, len(result.scripts))

# 2. Migration assessment (complexity + effort + capability mapping)
a = assess("dashboard.dxp")
print(a.score.index, a.score.level)        # e.g. 42.5 "medium"
print(a.effort.min_days, a.effort.likely_days, a.effort.max_days)

# 3. Markdown migration document (one or many assessments)
md = build_report([a], lang="it")
```

Export helpers:

```python
from dxp_analyzer_doc.export import export_result, write_summary
export_result(result, "out/dashboard", lang="en")
write_summary([result], "out", lang="en")
```

## The complexity & effort model

The complexity index does not sum raw counts. It groups the incidence variables
into **five normalized dimensions**, each mapped to `0..1` with a saturating
function so no single factor can dominate, then combines them with configurable
weights into a **0–100 index**:

| Dimension       | What it captures                                         | Weight |
|-----------------|----------------------------------------------------------|--------|
| Breadth / size  | pages, total visuals, text areas                         | 0.15   |
| Data model      | source tables, custom queries (weighted by difficulty), calculated columns, data functions | 0.20   |
| Custom code     | IronPython/JavaScript scripts and their lines            | 0.25   |
| Interactivity   | text-area controls, user properties, workaround visuals  | 0.15   |
| Migration gap   | non-native features/visuals, workarounds, reworked columns | 0.25 |

Levels: `Low ≤ 25`, `Medium ≤ 50`, `High ≤ 75`, `Very high > 75`.

### Effort estimate (parametric)

The effort is returned in person-days with a min/likely/max band, from a single
parametric formula with diminishing returns:

```
effort = base + score_coeff · index
       + Σ coeff_i · ln(1 + n_i)            # generic drivers (scripts, data functions, non-native features, …)
       + q_easy · ln(1 + n_easy)            # easy custom queries (diminishing)
       + q_medium · ln(1 + n_medium)        # medium custom queries (diminishing)
       + q_complex · n_complex              # complex custom queries (linear)
```

`ln` (natural log) means the 10th script costs less than the 1st. **Custom
queries are classified** as *easy / medium / complex* (see below), and every
**complex** query adds a linear cost, because a complex query implies the
underlying semantic model has to be decomposed. Defaults: `base=0.5`,
`score_coeff=0.05`, `scripts=0.5, data_functions=0.9, non_native_features=1.2`,
`q_easy=0.4, q_medium=0.8, q_complex=1.5`.

Every coefficient is overridable:

```python
from dxp_analyzer_doc import ComplexityModel, ParametricEffortConfig, assess

model = ComplexityModel(parametric_effort=ParametricEffortConfig(
    score_coeff=0.06, query_complex_coeff=2.0,
    log_coeffs={"scripts": 0.5, "data_functions": 1.0, "non_native_features": 1.2},
))
a = assess("dashboard.dxp", model=model)
print(a.effort.min_days, a.effort.likely_days, a.effort.max_days)
```

### Custom query classification

Each custom query behind the data model is scored (dependency-free SQL
heuristics: joins, subqueries, CTEs, window functions, conditions, group-by,
aggregations, length, …) and bucketed into **easy / medium / complex**. The
level drives both the effort (above) and the `data_model` dimension of the
index. Thresholds and weights live in `QueryComplexityConfig`:

```python
from dxp_analyzer_doc import ComplexityModel, QueryComplexityConfig
from dxp_analyzer_doc.migration import classify_query

level, score, metrics = classify_query("SELECT a FROM t JOIN u ON t.id = u.id")
model = ComplexityModel(query_config=QueryComplexityConfig(easy_max=2, medium_max=6))
```

## Migration rules

The Spotfire→Power BI mapping lives in `dxp_analyzer_doc/migration/rules.py`
(bilingual). Each rule is a regex over scripts/expressions/properties plus its
Power BI and Databricks guidance. Add or tune rules there.

## Project layout

```
src/dxp_analyzer_doc/
  analyzer.py        # DxpAnalyzer: the .dxp parsing engine
  model.py           # AnalysisResult and its dataclasses
  export.py          # xlsx/csv tables + extracted files
  i18n.py            # en/it string catalog
  migration/
    rules.py            # bilingual Spotfire -> Power BI rules
    complexity.py       # normalized index + parametric effort model
    query_complexity.py # SQL custom-query difficulty classifier
    assessment.py       # DashboardAssessment
    report.py           # Markdown migration document
  cli.py             # dxp-analyzer-doc command
legacy/              # original standalone scripts (reference only)
tests/               # pytest suite + synthetic .dxp
```

## Development

```bash
pip install -e ".[dev]"
pytest -q
```

The test suite builds a synthetic `.dxp` (see `tests/_sample.py`) and exercises
the full pipeline in both languages.

## License

MIT — see [LICENSE](LICENSE).
