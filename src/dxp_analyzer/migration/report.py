"""Render the Power BI migration report (Markdown) from dashboard assessments.

Structural sentences are written inline in both languages via :func:`pick`;
short reusable labels come from the i18n catalog.
"""

from __future__ import annotations

import re
import unicodedata
from datetime import datetime
from typing import List

from ..i18n import normalize_lang, t
from .assessment import DashboardAssessment, Entry
from .complexity import ComplexityModel
from .rules import NATIVE, NON_NATIVE, VISUAL_MAP, WORKAROUND, _loc as loc


def pick(lang: str, en: str, it: str) -> str:
    return it if normalize_lang(lang) == "it" else en


# -- markdown helpers ----------------------------------------------------------

def cell(value, maximum=80) -> str:
    text = re.sub(r"\s+", " ", str(value if value is not None else "")).strip().replace("|", "\\|")
    return text if len(text) <= maximum else text[:maximum - 3] + "..."


def table_md(header, rows, lang="en", maximum=80) -> List[str]:
    if not rows:
        return [t("generic.no_items", lang), ""]
    lines = ["| " + " | ".join(header) + " |", "|" + "|".join("---" for _ in header) + "|"]
    for row in rows:
        lines.append("| " + " | ".join(cell(v, maximum) for v in row) + " |")
    lines.append("")
    return lines


def round_num(value):
    return int(value) if float(value).is_integer() else round(value, 1)


def anchor(*parts) -> str:
    text = "-".join(str(p) for p in parts)
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode("ascii")
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")


def heading(level, text, ident) -> List[str]:
    return [f'<a id="{ident}"></a>', "", f"{level} {text}", ""]


def collapsible(label, content) -> List[str]:
    return ["<details>", f"<summary>{label}</summary>", ""] + content + ["</details>", ""]


def name_list(names, lang="en", maximum=6) -> str:
    names = [str(n) for n in names if str(n)]
    if len(names) <= maximum:
        return ", ".join(names)
    return ", ".join(names[:maximum]) + " " + t("generic.and_others", lang, n=len(names) - maximum)


# -- label maps ----------------------------------------------------------------

_DIMENSIONS = {
    "breadth": ("Breadth / size", "Ampiezza / dimensione"),
    "data_model": ("Data model", "Modello dati"),
    "custom_code": ("Custom code", "Codice personalizzato"),
    "interactivity": ("Interactivity", "Interattività"),
    "migration_gap": ("Migration gap", "Distanza dalla migrazione"),
}

_EFFORT = {
    "setup": ("Project setup", "Setup progetto"),
    "pages": ("Pages", "Pagine"),
    "visuals_native": ("Native visuals", "Visual nativi"),
    "visuals_workaround": ("Workaround visuals", "Visual con workaround"),
    "visuals_non_native": ("Non-native visuals", "Visual non nativi"),
    "text_areas": ("Text areas", "Text area"),
    "text_area_controls": ("Text area controls", "Controlli text area"),
    "user_properties": ("User document properties", "Document properties utente"),
    "scripts": ("Scripts", "Script"),
    "data_functions": ("Data functions", "Data function"),
    "queries": ("Custom queries", "Query personalizzate"),
    "source_tables": ("Source tables", "Tabelle sorgente"),
    "calculated_columns": ("Calculated columns", "Colonne calcolate"),
    "adapted_columns": ("Columns to rework", "Colonne da rilavorare"),
    "workaround_features": ("Features to adapt", "Funzionalità da adattare"),
    "non_native_features": ("Non-native features", "Funzionalità non native"),
}


def dim_label(key, lang):
    en, it = _DIMENSIONS.get(key, (key, key))
    return pick(lang, en, it)


def effort_label(key, lang):
    en, it = _EFFORT.get(key, (key, key))
    return pick(lang, en, it)


def outcome_label(outcome, lang):
    return t({"native": "outcome.native", "workaround": "outcome.workaround", "not_native": "outcome.not_native"}[outcome], lang)


# -- cards ---------------------------------------------------------------------

def _cards(assessment: DashboardAssessment, outcome: str, lang: str) -> List[str]:
    lines: List[str] = []
    for entry in assessment.entries_by_outcome(outcome):
        lines.append(f"**{loc(entry.name, lang)}**")
        lines.append("")
        lines.append(f"- Spotfire: {loc(entry.spotfire, lang)}")
        lines.append(f"- Power BI: {loc(entry.power_bi, lang)}")
        databricks = loc(entry.databricks, lang)
        if databricks:
            lines.append(f"- Databricks: {databricks}")
        if entry.where:
            lines.append("- " + pick(lang, "Where", "Dove") + f": {name_list(entry.where, lang)}")
        lines.append("")
    return lines or [t("generic.none", lang), ""]


# -- pros / cons synthesis -----------------------------------------------------

def _pros_cons(assessment: DashboardAssessment, lang: str):
    f = assessment.features
    counts = assessment.counts()
    pros, cons = [], []

    native_visuals = assessment.count_visuals(NATIVE)
    if native_visuals and native_visuals >= assessment.count_visuals(WORKAROUND) + assessment.count_visuals(NON_NATIVE):
        pros.append(pick(lang,
                         "Most visuals have a direct Power BI equivalent.",
                         "La maggior parte dei visual ha un equivalente diretto in Power BI."))
    native_sources = sum(1 for tbl in assessment.result.source_tables if tbl.nature in ("custom_query", "database_table"))
    if native_sources:
        pros.append(pick(lang,
                         f"{native_sources} data source(s) map directly to Databricks / Unity Catalog.",
                         f"{native_sources} sorgenti dati si mappano direttamente su Databricks / Unity Catalog."))
    if counts["ironpython"] + counts["javascript"] == 0:
        pros.append(pick(lang, "No custom scripts to reverse-engineer.",
                         "Nessuno script personalizzato da reinterpretare."))
    if assessment.score.level in ("low", "medium"):
        pros.append(pick(lang, "Overall complexity is manageable.",
                         "La complessità complessiva è gestibile."))

    if f.non_native_features:
        names = [loc(e.name, lang) for e in assessment.entries_by_outcome(NON_NATIVE) if not e.is_visual]
        cons.append(pick(lang,
                        f"{f.non_native_features} feature(s) have no native equivalent: {name_list(names, lang)}.",
                        f"{f.non_native_features} funzionalità senza equivalente nativo: {name_list(names, lang)}."))
    if f.data_functions:
        cons.append(pick(lang,
                        f"{f.data_functions} data function(s) must be rewritten as Databricks notebooks.",
                        f"{f.data_functions} data function da riscrivere come notebook Databricks."))
    if counts["ironpython"] + counts["javascript"]:
        cons.append(pick(lang,
                        f"{counts['ironpython'] + counts['javascript']} script(s) ({f.total_script_lines} lines) to analyze and redesign.",
                        f"{counts['ironpython'] + counts['javascript']} script ({f.total_script_lines} righe) da analizzare e ridisegnare."))
    if f.non_native_visuals:
        cons.append(pick(lang,
                        f"{f.non_native_visuals} visual(s) have no Power BI equivalent.",
                        f"{f.non_native_visuals} visual senza equivalente in Power BI."))
    if f.text_area_controls:
        cons.append(pick(lang,
                        f"{f.text_area_controls} text-area control(s): the HTML layout must be rebuilt natively.",
                        f"{f.text_area_controls} controlli nelle text area: il layout HTML va ricostruito in modo nativo."))
    if not cons:
        cons.append(pick(lang, "No blocking elements found.", "Nessun elemento bloccante rilevato."))

    lines = [pick(lang, "**Pros**", "**Pro**"), ""]
    lines += [f"- {p}" for p in pros] or ["- " + pick(lang, "None highlighted.", "Nessuno di rilievo."), ]
    lines += ["", pick(lang, "**Cons**", "**Contro**"), ""]
    lines += [f"- {c}" for c in cons]
    lines.append("")
    return lines


# -- per-dashboard section -----------------------------------------------------

def _dashboard_md(a: DashboardAssessment, lang: str) -> List[str]:
    c = a.counts()
    base = anchor(a.name)
    level = t(f"level.{a.score.level}", lang)
    md = heading("##", a.name, base)
    md.append(pick(lang, "Complexity", "Complessità") + f" **{level}** — "
              + pick(lang, "index", "indice") + f" **{round_num(a.score.index)}/100**")
    md.append("")
    md.append(pick(lang, "Estimated effort", "Effort stimato")
              + f": **{round_num(a.effort.likely_days)}** {t('generic.person_days', lang)} "
              + f"({round_num(a.effort.min_days)}–{round_num(a.effort.max_days)})")
    md.append("")
    md.append(f"{t('metric.pages', lang)} {c['pages']} · {t('metric.visuals_total', lang)} {c['visuals']} · "
              f"{t('metric.scripts_ironpython', lang)} {c['ironpython']} · {t('metric.scripts_javascript', lang)} {c['javascript']} · "
              f"{t('metric.document_properties', lang)} {c['properties']} · {t('metric.custom_queries', lang)} {c['queries']} · "
              f"{t('metric.data_functions', lang)} {c['data_functions']} · {t('metric.calculated_columns', lang)} {c['columns']}")
    md.append("")
    md.append(" · ".join([
        f"[{pick(lang, 'Not migratable', 'Non migrabili')} ({c['non_native']})](#{base}-non-migratable)",
        f"[{pick(lang, 'To adapt', 'Da adattare')} ({c['workaround']})](#{base}-to-adapt)",
        f"[{pick(lang, 'Directly migratable', 'Migrabili direttamente')}](#{base}-direct)",
        f"[{pick(lang, 'Inventory', 'Inventario')}](#{base}-inventory)",
        f"[Menu](#menu)",
    ]))
    md.append("")

    # synthesis
    md += heading("###", pick(lang, "Migration synthesis", "Sintesi di migrazione"), f"{base}-synthesis")
    md += _pros_cons(a, lang)

    # complexity breakdown
    md += heading("###", pick(lang, "Complexity breakdown", "Composizione della complessità"), f"{base}-complexity")
    md += table_md(
        [pick(lang, "Dimension", "Dimensione"), pick(lang, "Normalized (0-1)", "Normalizzato (0-1)"),
         pick(lang, "Weight", "Peso"), pick(lang, "Raw load", "Carico grezzo")],
        [[dim_label(k, lang), a.score.dimensions.get(k, 0), a.model.complexity.dimension_weights.get(k, 0),
          a.score.loads.get(k, 0)] for k in a.score.dimensions],
        lang)

    # cards
    md += heading("###", pick(lang, "Not migratable with native Power BI", "Non migrabili con Power BI nativo"), f"{base}-non-migratable")
    md += _cards(a, NON_NATIVE, lang)
    md += heading("###", pick(lang, "To adapt with a workaround", "Da adattare con un workaround"), f"{base}-to-adapt")
    md += _cards(a, WORKAROUND, lang)

    md += heading("###", pick(lang, "Directly migratable", "Migrabili direttamente"), f"{base}-direct")
    direct = []
    natives = [(t_, n) for t_, n in a.visual_counts.most_common() if VISUAL_MAP.get(t_, (None, WORKAROUND))[1] == NATIVE]
    if natives:
        direct.append("- " + pick(lang, "Visuals", "Visual") + ": " + ", ".join(f"{loc(VISUAL_MAP[t_][0], lang)} ({n})" for t_, n in natives))
    native_features = [loc(e.name, lang) for e in a.entries_by_outcome(NATIVE)]
    if native_features:
        direct.append("- " + pick(lang, "Features", "Funzionalità") + ": " + ", ".join(native_features))
    native_sources = [tbl for tbl in a.result.source_tables if tbl.nature in ("custom_query", "database_table")]
    if native_sources:
        direct.append("- " + pick(lang, "Data sources", "Sorgenti dati") + ": " + name_list([s.name for s in native_sources], lang))
    md += (direct + [""]) if direct else [t("generic.none", lang), ""]

    # inventory
    md += heading("###", pick(lang, "Inventory", "Inventario"), f"{base}-inventory")
    md += _inventory(a, lang)
    md += [f"[{t('generic.back_to_menu', lang)}](#menu)", ""]
    return md


def _inventory(a: DashboardAssessment, lang: str) -> List[str]:
    c = a.counts()
    md: List[str] = []
    md += collapsible(f"{t('metric.pages', lang)} ({c['pages']})", table_md(
        [t("hdr.page", lang), t("hdr.visual_objects", lang), t("hdr.text_area", lang), t("hdr.charts_tables", lang)],
        [[p.title, len(p.visuals),
          sum(1 for v in p.visuals if v.type in ("HtmlTextArea", "TextArea")),
          sum(1 for v in p.visuals if v.type not in ("HtmlTextArea", "TextArea"))] for p in a.result.pages], lang))
    md += collapsible(f"{pick(lang, 'Visuals', 'Visual')} ({c['visuals']})", table_md(
        [pick(lang, "Spotfire type", "Tipo Spotfire"), t("hdr.number", lang), pick(lang, "In Power BI", "In Power BI"), pick(lang, "Outcome", "Esito")],
        [[tp, n, loc(VISUAL_MAP.get(tp, ({"en": "To verify", "it": "Da verificare"}, WORKAROUND))[0], lang),
          outcome_label(VISUAL_MAP.get(tp, (None, WORKAROUND))[1], lang)] for tp, n in a.visual_counts.most_common()], lang))
    md += collapsible(f"{pick(lang, 'Scripts', 'Script')} ({len(a.scripts)})", table_md(
        [t("hdr.name", lang), t("hdr.language", lang), pick(lang, "Lines", "Righe"), pick(lang, "Outcome", "Esito"), pick(lang, "Features found", "Funzionalità trovate")],
        [[s.name, s.language, s.lines, outcome_label(s.outcome, lang), ", ".join(r.name_of(lang) for r in s.rules)] for s in a.scripts], lang))
    md += collapsible(f"{t('metric.document_properties', lang)} ({c['properties']})", table_md(
        [t("hdr.name", lang), t("hdr.type", lang), t("hdr.used_in", lang)],
        [[p.name, t(f"kind.{p.kind}", lang), p.used_in] for p in a.properties], lang))
    md += collapsible(f"{pick(lang, 'Data sources', 'Sorgenti dati')} ({len(a.result.source_tables)})", table_md(
        [t("hdr.table", lang), t("hdr.type", lang), t("hdr.database_object", lang)],
        [[s.name, t(f"nature.{s.nature}", lang), s.database_object] for s in a.result.source_tables], lang))
    md += collapsible(f"{t('metric.calculated_columns', lang)} ({c['columns']})", table_md(
        [t("hdr.table", lang), t("hdr.column", lang), pick(lang, "Outcome", "Esito"), pick(lang, "Functions found", "Funzioni trovate")],
        [[x.table, x.column, outcome_label(x.outcome, lang), ", ".join(r.name_of(lang) for r in x.rules)] for x in a.columns], lang))
    md += collapsible(f"{t('metric.text_areas', lang)} ({len(a.result.text_areas)})", table_md(
        [t("hdr.page", lang), t("hdr.title", lang), pick(lang, "Controls", "Controlli"), t("hdr.images", lang)],
        [[ta.page, ta.title, ta.controls, ta.images] for ta in a.result.text_areas], lang))
    md += collapsible(f"{t('metric.data_functions', lang)} ({c['data_functions']})", table_md(
        [t("hdr.name", lang), t("hdr.language", lang), pick(lang, "Lines", "Righe")],
        [[d.name, d.language, d.lines] for d in a.result.data_functions], lang))
    md += collapsible(f"{pick(lang, 'Effort estimate', 'Stima effort')} ({round_num(a.effort.likely_days)} {t('generic.person_days', lang)})", table_md(
        [pick(lang, "Item", "Voce"), pick(lang, "Quantity", "Quantità"), t("generic.person_days", lang)],
        [[effort_label(k, lang), q, round_num(d)] for k, q, d in a.effort.breakdown]
        + [[t("generic.total", lang), "", round_num(a.effort.likely_days)]], lang))
    return md


# -- global sections -----------------------------------------------------------

def _how_to_read(lang: str, model: ComplexityModel) -> List[str]:
    th = model.complexity.thresholds
    scale = ", ".join(f"{t(f'level.{name}', lang)} ≤ {int(v)}" for v, name in th) + f", {t('level.very_high', lang)} > {int(th[-1][0])}"
    return heading("##", pick(lang, "How to read this document", "Come leggere il documento"), "how-to-read") + [
        pick(lang, "For each dashboard the elements are split into three groups:",
             "Per ogni dashboard gli elementi sono divisi in tre gruppi:"),
        "",
        "- " + pick(lang, "Not migratable: Power BI does not support them natively. A different approach or Databricks is needed.",
                    "Non migrabili: Power BI non li supporta con gli strumenti nativi. Serve una soluzione diversa o spostare la logica su Databricks."),
        "- " + pick(lang, "To adapt: a similar result is achievable in Power BI with a different approach.",
                    "Da adattare: si ottiene un risultato simile in Power BI, con un approccio diverso."),
        "- " + pick(lang, "Directly migratable: a direct equivalent exists.",
                    "Migrabili direttamente: esiste un equivalente diretto."),
        "",
        pick(lang,
             "The complexity index (0-100) is a weighted blend of five normalized dimensions "
             "(breadth, data model, custom code, interactivity and migration gap), so no single "
             "factor can dominate. The effort is an itemized estimate in person-days with a "
             "min-likely-max band.",
             "L'indice di complessità (0-100) combina in modo pesato cinque dimensioni normalizzate "
             "(ampiezza, modello dati, codice personalizzato, interattività e distanza dalla migrazione), "
             "così nessun singolo fattore può dominare. L'effort è una stima per voci in giorni/persona "
             "con una banda minimo-atteso-massimo."),
        "",
        pick(lang, f"Levels: {scale}.", f"Livelli: {scale}."),
        "",
        f"[{t('generic.back_to_menu', lang)}](#menu)",
        "",
    ]


def _overall_summary(assessments: List[DashboardAssessment], lang: str) -> List[str]:
    md = heading("##", pick(lang, "Overall summary", "Riepilogo generale"), "overall-summary")
    rows = []
    for a in sorted(assessments, key=lambda x: -x.score.index):
        c = a.counts()
        rows.append([f"[{a.name}](#{anchor(a.name)})", t(f"level.{a.score.level}", lang), round_num(a.score.index),
                     f"{round_num(a.effort.min_days)}–{round_num(a.effort.max_days)}",
                     c["non_native"], c["workaround"], c["pages"], c["visuals"], c["ironpython"] + c["javascript"], c["queries"]])
    md += table_md(
        [t("metric.dashboard", lang), pick(lang, "Complexity", "Complessità"), pick(lang, "Index", "Indice"),
         pick(lang, "Effort (p-d)", "Effort (g/p)"), pick(lang, "Not migratable", "Non migrabili"),
         pick(lang, "To adapt", "Da adattare"), t("metric.pages", lang), pick(lang, "Visuals", "Visual"),
         pick(lang, "Scripts", "Script"), t("metric.custom_queries", lang)], rows, lang)

    md += [pick(lang, "Non-migratable elements across the dashboards:",
                "Elementi non migrabili presenti nelle dashboard:"), ""]
    names = sorted({loc(e.name, lang) for a in assessments for e in a.entries.values() if e.outcome == NON_NATIVE})
    rows = []
    for name in names:
        present = [a.name for a in assessments if any(loc(e.name, lang) == name for e in a.entries.values())]
        entry = next(e for a in assessments for e in a.entries.values() if loc(e.name, lang) == name)
        rows.append([name, loc(entry.power_bi, lang), ", ".join(present)])
    md += table_md([pick(lang, "Element", "Elemento"), pick(lang, "In Power BI", "In Power BI"), t("metric.dashboard", lang)], rows, lang, 200)
    md += [f"[{t('generic.back_to_menu', lang)}](#menu)", ""]
    return md


def build_report(assessments: List[DashboardAssessment], lang: str = "en", model: ComplexityModel | None = None) -> str:
    """Build the full multi-dashboard migration document as a Markdown string."""
    lang = normalize_lang(lang)
    model = model or (assessments[0].model if assessments else ComplexityModel())
    title = pick(lang, "Spotfire migration documentation", "Documentazione migrazione Spotfire")
    md = [f"# {title}", "", pick(lang, "Last updated", "Ultimo aggiornamento")
          + f": {datetime.now().strftime('%d/%m/%Y %H:%M:%S')}", ""]
    md += heading("##", "Menu", "menu")
    md.append(f"- [{pick(lang, 'How to read this document', 'Come leggere il documento')}](#how-to-read)")
    md.append(f"- [{pick(lang, 'Overall summary', 'Riepilogo generale')}](#overall-summary)")
    for a in assessments:
        md.append(f"- [{a.name}](#{anchor(a.name)}): {pick(lang, 'complexity', 'complessità')} {t(f'level.{a.score.level}', lang).lower()}")
    md.append("")
    md += _how_to_read(lang, model)
    md += _overall_summary(assessments, lang)
    for a in assessments:
        md += _dashboard_md(a, lang)
    return "\n".join(md)
