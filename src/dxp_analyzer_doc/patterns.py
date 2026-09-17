"""Spotfire-specific constants and heuristics used by the analyzer.

The string literals here (type names, field keys, code signals) come from the
internal structure of a ``.dxp`` archive and must not be translated.
"""

from __future__ import annotations

import re

# Maximum size (bytes) of an archive entry we still try to decode as text.
MAX_TEXT_SIZE = 50 * 1024 * 1024

BINARY_EXTENSIONS = {
    ".sbdf", ".stdf", ".png", ".jpg", ".jpeg", ".gif", ".bmp",
    ".ico", ".dll", ".exe", ".zip", ".pdf",
}

IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".gif", ".bmp", ".ico", ".svg"}

# Object types that live inside snapshots/undo history and should be ignored.
SNAPSHOT_TYPES = re.compile(r"Bookmark|Snapshot|Undo|History")

# Field names that usually carry script/source code.
CODE_KEYS = {
    "scriptcode", "code", "script", "scripttext", "source",
    "sourcecode", "body", "text", "content",
}

# Document properties shown on the Spotfire "General" tab (not user properties).
GENERAL_TAB_PROPERTIES = {
    "description", "keywords", "allowwebplayerresume", "publicbookmarkcreation",
    "privatebookmarkcreation", "name", "title", "author", "comments",
}

# Field names that may hold a human-readable object name.
NAME_KEYS = ("name", "title", "displayname", "scriptname", "caption", "titleexpression")

# Visual types recognised on a page.
VISUAL_TYPES = {
    "BarChart", "LineChart", "CombinationChart", "CrossTablePlot", "TablePlot",
    "SummaryTable", "ScatterPlot", "ScatterPlot3D", "PieChart", "Treemap",
    "TreeMap", "HeatMap", "BoxPlot", "GraphicalTable", "KpiChart", "KPIChart",
    "WaterfallChart", "ParallelCoordinatePlot", "MapChart", "HtmlTextArea", "TextArea",
}

TEXT_AREA_TYPES = {"HtmlTextArea", "TextArea"}

PYTHON_SIGNALS = [re.compile(x, re.M) for x in (
    r"^\s*from\s+\w[\w.]*\s+import\b",
    r"^\s*import\s+\w",
    r"\bDocument\.\w",
    r"\bApplication\.\w",
    r"\bclr\.",
    r"^\s*def\s+\w+\s*\(",
    r"^\s*for\s+\w+\s+in\s+.+:\s*$",
    r"^\s*if\s+.+:\s*$",
    r"\.As\[\w+\]",
    r"\bSpotfire\.Dxp\.\w",
)]

JS_SIGNALS = [re.compile(x, re.M) for x in (
    r"\bfunction\s*\w*\s*\(",
    r"\bvar\s+\w",
    r"\b(?:let|const)\s+\w",
    r"\bdocument\.\w",
    r"\$\(",
    r"\bjQuery\b",
    r"\bset(?:Timeout|Interval)\s*\(",
    r"addEventListener",
    r"=>",
    r"getElementById|querySelector",
    r"\bconsole\.\w",
    r"\bwindow\.\w",
)]
