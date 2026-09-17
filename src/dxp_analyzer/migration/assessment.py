"""Turn an :class:`AnalysisResult` into a migration assessment.

The assessment is language-neutral: it stores rule objects and bilingual text,
and the report localizes them at render time.
"""

from __future__ import annotations

from collections import Counter, OrderedDict
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Union

from ..model import AnalysisResult
from .complexity import ComplexityModel, ComplexityScore, EffortEstimate, Features
from .rules import (
    EXPRESSION_RULES,
    IRONPYTHON_RULES,
    JAVASCRIPT_RULES,
    NATIVE,
    NON_NATIVE,
    VISUAL_MAP,
    WORKAROUND,
    Rule,
    matching_rules,
    source_mapping,
    worst_outcome,
)

TextField = Union[str, Dict[str, str]]


@dataclass
class Entry:
    """A migration card: one capability and how it maps to Power BI/Databricks."""

    key: str
    outcome: str
    name: TextField
    spotfire: TextField
    power_bi: TextField
    databricks: TextField = ""
    where: List[str] = field(default_factory=list)
    is_visual: bool = False


@dataclass
class ScriptAssessment:
    name: str
    language: str
    lines: int
    rules: List[Rule]
    outcome: str


@dataclass
class ColumnAssessment:
    table: str
    column: str
    rules: List[Rule]
    outcome: str


@dataclass
class PropertyAssessment:
    name: str
    kind: str
    used_in: str
    rules: List[Rule]


class DashboardAssessment:
    """Assess one dashboard for migration to Power BI."""

    def __init__(self, result: AnalysisResult, model: Optional[ComplexityModel] = None):
        self.result = result
        self.name = result.name
        self.model = model or ComplexityModel()
        self.entries: "OrderedDict[str, Entry]" = OrderedDict()
        self.scripts: List[ScriptAssessment] = []
        self.columns: List[ColumnAssessment] = []
        self.properties: List[PropertyAssessment] = []
        self.visual_counts: Counter = Counter(result.visual_counts)
        self.features: Features = Features()
        self.score: ComplexityScore
        self.effort: EffortEstimate
        self._assess()

    # -- registration -----------------------------------------------------------

    def _register(self, key, outcome, name, spotfire, power_bi, databricks="", where="", is_visual=False):
        entry = self.entries.get(key)
        if entry is None:
            entry = Entry(key=key, outcome=outcome, name=name, spotfire=spotfire,
                          power_bi=power_bi, databricks=databricks, is_visual=is_visual)
            self.entries[key] = entry
        if where and where not in entry.where:
            entry.where.append(where)

    def _register_rule(self, rule: Rule, where: str):
        self._register(rule.key, rule.outcome, rule.name, rule.spotfire, rule.power_bi, rule.databricks, where)

    # -- assessment -------------------------------------------------------------

    def _assess(self):
        for script in self.result.scripts:
            ruleset = JAVASCRIPT_RULES if script.language == "JavaScript" else IRONPYTHON_RULES
            found = matching_rules(script.code, ruleset)
            label = script.name if script.name.lower().startswith("script") else f"script {script.name}"
            for rule in found:
                self._register_rule(rule, label)
            lines = script.lines or len([r for r in script.code.splitlines() if r.strip()])
            self.scripts.append(ScriptAssessment(
                name=script.name, language=script.language, lines=lines,
                rules=found, outcome=worst_outcome(r.outcome for r in found) or NATIVE))

        for column in self.result.calculated_columns:
            found = matching_rules(column.expression, EXPRESSION_RULES)
            for rule in found:
                self._register_rule(rule, f"column {column.name}")
            self.columns.append(ColumnAssessment(
                table=column.table, column=column.name, rules=found,
                outcome=worst_outcome(r.outcome for r in found) or NATIVE))

        for prop in self.result.document_properties:
            found = matching_rules(prop.value, EXPRESSION_RULES)
            for rule in found:
                self._register_rule(rule, f"property {prop.name}")
            self.properties.append(PropertyAssessment(
                name=prop.name, kind=prop.kind, used_in=prop.used_in, rules=found))

        for type_name, n in self.visual_counts.items():
            entry = VISUAL_MAP.get(type_name)
            outcome = entry[1] if entry else WORKAROUND
            if outcome != NATIVE and type_name not in ("HtmlTextArea", "TextArea"):
                equivalent = entry[0] if entry else {"en": "To verify", "it": "Da verificare"}
                self._register(
                    f"visual:{type_name}", outcome,
                    name=f"Visual {type_name}",
                    spotfire={"en": f"{n} visuals of type {type_name}.", "it": f"{n} visual di tipo {type_name}."},
                    power_bi={lang: f"{txt}." for lang, txt in equivalent.items()},
                    is_visual=True,
                )

        controls = sum(t.controls for t in self.result.text_areas)
        if controls:
            self._register(
                "text_area_controls", WORKAROUND,
                name={"en": "Controls in text areas", "it": "Controlli nelle text area"},
                spotfire={"en": f"{controls} controls in text areas (buttons, menus, fields, labels).",
                          "it": f"{controls} controlli nelle text area (pulsanti, menu, campi, etichette)."},
                power_bi={"en": "Slicers, buttons with actions and bookmarks. The HTML layout must be rebuilt.",
                          "it": "Slicer, pulsanti con azioni e segnalibri. Il layout HTML va ricostruito."},
            )

        for df in self.result.data_functions:
            self._register(
                "data_function", NON_NATIVE,
                name={"en": "Data function", "it": "Data function"},
                spotfire={"en": "R or Python calculations executed in the document.",
                          "it": "Calcoli in R o Python eseguiti nel documento."},
                power_bi={"en": "No reliable equivalent.", "it": "Nessun equivalente affidabile."},
                databricks={"en": "Rewrite as a notebook and save the result to a table.",
                            "it": "Riscrivere come notebook e salvare il risultato in una tabella."},
                where=df.name,
            )

        for table in self.result.source_tables:
            outcome, power_bi, databricks = source_mapping(table.nature, "en")
            if outcome != NATIVE:
                raw = _SOURCE_TEXT.get(table.nature, _SOURCE_TEXT["undetermined"])
                self._register(
                    f"source:{table.nature}", outcome,
                    name={"en": raw["name_en"], "it": raw["name_it"]},
                    spotfire={"en": "Data read through the Spotfire library.",
                              "it": "Dati letti tramite la libreria Spotfire."},
                    power_bi=raw["power_bi"],
                    databricks=raw["databricks"],
                    where=table.name,
                )

        self.features = self._build_features()
        self.score = self.model.score(self.features)
        self.effort = self.model.effort_estimate(self.features)

    # -- derived metrics --------------------------------------------------------

    def count_visuals(self, outcome: str) -> int:
        return sum(n for t, n in self.visual_counts.items()
                   if t not in ("HtmlTextArea", "TextArea")
                   and (VISUAL_MAP.get(t, (None, WORKAROUND))[1]) == outcome)

    def _build_features(self) -> Features:
        ironpython = [s for s in self.scripts if s.language != "JavaScript"]
        javascript = [s for s in self.scripts if s.language == "JavaScript"]
        non_visual_entries = [e for e in self.entries.values() if not e.is_visual]
        return Features(
            pages=len(self.result.pages),
            native_visuals=self.count_visuals(NATIVE),
            workaround_visuals=self.count_visuals(WORKAROUND),
            non_native_visuals=self.count_visuals(NON_NATIVE),
            text_areas=self.result.text_area_count,
            text_area_controls=sum(t.controls for t in self.result.text_areas),
            user_properties=sum(1 for p in self.properties if p.kind != "standard"),
            ironpython_scripts=len(ironpython),
            ironpython_lines=sum(s.lines for s in ironpython),
            javascript_scripts=len(javascript),
            javascript_lines=sum(s.lines for s in javascript),
            data_functions=len(self.result.data_functions),
            custom_queries=len(self.result.queries),
            source_tables=len(self.result.source_tables),
            calculated_columns=len(self.columns),
            adapted_columns=sum(1 for c in self.columns if c.outcome in (WORKAROUND, NON_NATIVE)),
            workaround_features=sum(1 for e in non_visual_entries if e.outcome == WORKAROUND),
            non_native_features=sum(1 for e in non_visual_entries if e.outcome == NON_NATIVE),
        )

    def counts(self) -> Dict[str, int]:
        return {
            "pages": len(self.result.pages),
            "visuals": sum(self.visual_counts.values()),
            "ironpython": sum(1 for s in self.scripts if s.language != "JavaScript"),
            "javascript": sum(1 for s in self.scripts if s.language == "JavaScript"),
            "properties": len(self.properties),
            "queries": len(self.result.queries),
            "data_functions": len(self.result.data_functions),
            "columns": len(self.columns),
            "non_native": sum(1 for e in self.entries.values() if e.outcome == NON_NATIVE),
            "workaround": sum(1 for e in self.entries.values() if e.outcome == WORKAROUND),
        }

    def entries_by_outcome(self, outcome: str) -> List[Entry]:
        return [e for e in self.entries.values() if e.outcome == outcome]


# Source-nature card text (kept here so rules.py stays about pattern rules).
_SOURCE_TEXT = {
    "custom_query": {
        "name_en": "Custom query", "name_it": "Query personalizzata",
        "power_bi": {"en": "SQL query in the connection or a database view.",
                     "it": "Query SQL nella connessione o vista sul database."},
        "databricks": {"en": "A view in Unity Catalog with the same query.",
                       "it": "Vista in Unity Catalog con la stessa query."},
    },
    "database_table": {
        "name_en": "Database table or view", "name_it": "Tabella o vista del database",
        "power_bi": {"en": "Direct connection to the table or view.",
                     "it": "Connessione diretta alla tabella o vista."},
        "databricks": {"en": "A table or view in Unity Catalog.",
                       "it": "Tabella o vista in Unity Catalog."},
    },
    "information_link": {
        "name_en": "Information Link", "name_it": "Information Link",
        "power_bi": {"en": "Retrieve the underlying query from the Spotfire library and recreate it.",
                     "it": "Recuperare dalla libreria Spotfire la query sottostante e ricrearla."},
        "databricks": {"en": "A view in Unity Catalog with the retrieved query.",
                       "it": "Vista in Unity Catalog con la query recuperata."},
    },
    "undetermined": {
        "name_en": "Undetermined source", "name_it": "Sorgente non determinata",
        "power_bi": {"en": "To be verified by opening the dashboard.",
                     "it": "Da verificare aprendo la dashboard."},
        "databricks": {"en": "", "it": ""},
    },
}
