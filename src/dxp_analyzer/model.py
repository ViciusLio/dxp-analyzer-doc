"""Structured result of analyzing a ``.dxp`` file.

An :class:`AnalysisResult` is the single source of truth consumed by both the
table exporter and the migration assessment/report.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Tuple


@dataclass
class VisualRef:
    type: str          # last segment, e.g. "BarChart"
    name: str = ""


@dataclass
class Page:
    title: str
    visuals: List[VisualRef] = field(default_factory=list)


@dataclass
class TextArea:
    title: str
    page: str
    html: str = ""
    controls: int = 0
    images: int = 0
    script_tags: int = 0
    libraries: List[str] = field(default_factory=list)
    file: str = ""


@dataclass
class ScriptInfo:
    name: str
    language: str
    code: str = ""
    lines: int = 0
    origin: str = ""
    name_in_file: bool = False
    file: str = ""


@dataclass
class DataFunctionInfo:
    name: str
    language: str
    code: str = ""
    lines: int = 0
    inputs: List[str] = field(default_factory=list)
    outputs: List[str] = field(default_factory=list)
    file: str = ""


@dataclass
class PropertyInfo:
    name: str
    class_name: str = ""
    group: str = ""
    standard: bool = False
    attributes: str = ""
    data_type: str = ""
    value: str = ""
    description: str = ""
    used_in: str = ""

    @property
    def kind(self) -> str:
        """Machine value; the render layer localizes it."""
        return "standard" if self.standard else "user"


@dataclass
class CalcColumn:
    table: str
    name: str
    expression: str = ""


@dataclass
class Query:
    name: str
    sql: str = ""
    file: str = ""


@dataclass
class SourceTable:
    name: str
    nature: str
    database_object: str = ""
    database_object_type: str = ""
    details: str = ""
    file: str = ""


@dataclass
class Connection:
    context: str
    key: str
    value: str


@dataclass
class ZipEntry:
    name: str
    size: int
    compressed_size: int


@dataclass
class AnalysisResult:
    """Everything extracted from a single ``.dxp`` archive."""

    name: str
    path: str = ""
    pages: List[Page] = field(default_factory=list)
    visual_counts: Dict[str, int] = field(default_factory=dict)
    text_areas: List[TextArea] = field(default_factory=list)
    scripts: List[ScriptInfo] = field(default_factory=list)
    data_functions: List[DataFunctionInfo] = field(default_factory=list)
    document_properties: List[PropertyInfo] = field(default_factory=list)
    all_properties: List[PropertyInfo] = field(default_factory=list)
    calculated_columns: List[CalcColumn] = field(default_factory=list)
    queries: List[Query] = field(default_factory=list)
    source_tables: List[SourceTable] = field(default_factory=list)
    data_tables: List[str] = field(default_factory=list)
    connections: List[Connection] = field(default_factory=list)
    bookmarks: int = 0
    images: int = 0
    live_types: Dict[str, int] = field(default_factory=dict)
    snapshot_types: Dict[str, int] = field(default_factory=dict)
    zip_entries: List[ZipEntry] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)

    # -- convenience aggregates -------------------------------------------------

    @property
    def document_properties_standard(self) -> List[PropertyInfo]:
        return [p for p in self.document_properties if p.standard]

    @property
    def text_area_count(self) -> int:
        return sum(self.visual_counts.get(t, 0) for t in ("HtmlTextArea", "TextArea"))

    @property
    def total_visuals(self) -> int:
        return sum(self.visual_counts.values())

    def scripts_by_language(self, language: str) -> List[ScriptInfo]:
        return [s for s in self.scripts if s.language == language]

    def metrics(self) -> "List[Tuple[str, object]]":
        """Ordered (machine_key, value) pairs for the cross-dashboard summary.

        Keys are stable identifiers; the render layer maps them to a localized
        column header via the i18n catalog.
        """
        text_area = self.text_area_count
        total = self.total_visuals
        return [
            ("dashboard", self.name),
            ("pages", len(self.pages)),
            ("page_names", ", ".join(p.title for p in self.pages)),
            ("visuals_total", total),
            ("chart_visuals", total - text_area),
            ("text_areas", text_area),
            ("document_properties", len(self.document_properties)),
            ("document_properties_user", len(self.document_properties) - len(self.document_properties_standard)),
            ("document_properties_standard", len(self.document_properties_standard)),
            ("scripts_ironpython", len(self.scripts_by_language("IronPython"))),
            ("scripts_python", len(self.scripts_by_language("Python"))),
            ("scripts_javascript", len(self.scripts_by_language("JavaScript"))),
            ("data_functions", len(self.data_functions)),
            ("custom_queries", len(self.queries)),
            ("data_tables", len(self.data_tables)),
            ("database_tables", sum(1 for t in self.source_tables if t.nature == "database_table")),
            ("information_links", sum(1 for t in self.source_tables if t.nature == "information_link")),
            ("calculated_columns", len(self.calculated_columns)),
            ("bookmarks", self.bookmarks),
            ("images", self.images),
        ]
