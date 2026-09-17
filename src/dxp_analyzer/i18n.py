"""Localization of user-facing strings (output language: ``en`` default, ``it``).

Only *presentation* strings live here. Machine keys produced by the analyzer
(outcomes, source natures, property groups, metric ids) are mapped to localized
labels through the catalogs below.
"""

from __future__ import annotations

from typing import Dict

DEFAULT_LANG = "en"
LANGUAGES = ("en", "it")


def normalize_lang(lang: str | None) -> str:
    lang = (lang or DEFAULT_LANG).lower().split("-")[0].strip()
    return lang if lang in LANGUAGES else DEFAULT_LANG


# Flat catalog. Keys are stable identifiers; values are per-language strings.
CATALOG: Dict[str, Dict[str, str]] = {
    # -- outcomes -------------------------------------------------------------
    "outcome.native": {"en": "Native", "it": "Nativo"},
    "outcome.workaround": {"en": "Workaround", "it": "Workaround"},
    "outcome.not_native": {"en": "Not native", "it": "Non nativo"},
    # -- complexity levels ----------------------------------------------------
    "level.low": {"en": "Low", "it": "Bassa"},
    "level.medium": {"en": "Medium", "it": "Media"},
    "level.high": {"en": "High", "it": "Alta"},
    "level.very_high": {"en": "Very high", "it": "Molto alta"},
    # -- source natures -------------------------------------------------------
    "nature.custom_query": {"en": "Custom query", "it": "Query personalizzata"},
    "nature.database_table": {"en": "Database table or view", "it": "Tabella o vista del database"},
    "nature.information_link": {"en": "Information Link", "it": "Information Link"},
    "nature.undetermined": {"en": "Undetermined", "it": "Non determinato"},
    # -- property kinds / groups ---------------------------------------------
    "kind.standard": {"en": "standard", "it": "standard"},
    "kind.user": {"en": "user", "it": "utente"},
    "group.document": {"en": "Document", "it": "Documento"},
    "group.column": {"en": "Column", "it": "Colonna"},
    "group.table": {"en": "Table", "it": "Tabella"},
    # -- generic --------------------------------------------------------------
    "generic.none": {"en": "None.", "it": "Nessuno."},
    "generic.no_items": {"en": "No items.", "it": "Nessun elemento."},
    "generic.total": {"en": "Total", "it": "Totale"},
    "generic.and_others": {"en": "and {n} more", "it": "e altri {n}"},
    "generic.to_verify": {"en": "To verify", "it": "Da verificare"},
    "generic.points": {"en": "points", "it": "punti"},
    "generic.person_days": {"en": "person-days", "it": "giorni/persona"},
    "generic.back_to_menu": {"en": "Back to menu", "it": "Torna al menu"},
    # -- metric labels (for the cross-dashboard summary) ----------------------
    "metric.dashboard": {"en": "Dashboard", "it": "Dashboard"},
    "metric.pages": {"en": "Pages", "it": "Pagine"},
    "metric.page_names": {"en": "Page names", "it": "Nomi pagine"},
    "metric.visuals_total": {"en": "Total visuals", "it": "Oggetti visivi totali"},
    "metric.charts_and_tables": {"en": "Charts and tables", "it": "Grafici e tabelle"},
    "metric.text_areas": {"en": "Text areas", "it": "Text area"},
    "metric.document_properties": {"en": "Document properties", "it": "Document properties"},
    "metric.document_properties_user": {"en": "User document properties", "it": "Document properties utente"},
    "metric.document_properties_standard": {"en": "Standard document properties", "it": "Document properties standard"},
    "metric.scripts_ironpython": {"en": "IronPython scripts", "it": "Script IronPython"},
    "metric.scripts_python": {"en": "Python scripts", "it": "Script Python"},
    "metric.scripts_javascript": {"en": "JavaScript scripts", "it": "Script JavaScript"},
    "metric.data_functions": {"en": "Data functions", "it": "Data function"},
    "metric.custom_queries": {"en": "Custom queries", "it": "Query personalizzate"},
    "metric.database_tables": {"en": "Database tables/views", "it": "Tabelle o viste database"},
    "metric.information_links": {"en": "Information Links", "it": "Information Link"},
    "metric.calculated_columns": {"en": "Calculated columns", "it": "Colonne calcolate"},
    "metric.bookmarks": {"en": "Bookmarks", "it": "Segnalibri"},
    "metric.images": {"en": "Images", "it": "Immagini"},
    # -- table headers (export) ----------------------------------------------
    "hdr.name": {"en": "name", "it": "nome"},
    "hdr.language": {"en": "language", "it": "linguaggio"},
    "hdr.file": {"en": "file", "it": "file"},
    "hdr.code_lines": {"en": "lines_of_code", "it": "righe_di_codice"},
    "hdr.name_in_file": {"en": "name_present_in_file", "it": "nome_presente_nel_file"},
    "hdr.source_resource": {"en": "source_resource", "it": "risorsa_origine"},
    "hdr.number": {"en": "number", "it": "numero"},
    "hdr.page": {"en": "page", "it": "pagina"},
    "hdr.visual_objects": {"en": "visual_objects", "it": "oggetti_visivi"},
    "hdr.text_area": {"en": "text_area", "it": "text_area"},
    "hdr.charts_tables": {"en": "charts_and_tables", "it": "grafici_e_tabelle"},
    "hdr.type": {"en": "type", "it": "tipo"},
    "hdr.title": {"en": "title", "it": "titolo"},
    "hdr.value": {"en": "value", "it": "valore"},
    "hdr.description": {"en": "description", "it": "descrizione"},
    "hdr.used_in": {"en": "used_in", "it": "usata_in"},
    "hdr.attributes": {"en": "attributes", "it": "attributi"},
    "hdr.group": {"en": "group", "it": "gruppo"},
    "hdr.register": {"en": "register", "it": "registro"},
    "hdr.standard": {"en": "standard", "it": "standard"},
    "hdr.table": {"en": "table", "it": "tabella"},
    "hdr.column": {"en": "column", "it": "colonna"},
    "hdr.expression": {"en": "expression", "it": "espressione"},
    "hdr.inputs": {"en": "inputs", "it": "ingressi"},
    "hdr.outputs": {"en": "outputs", "it": "uscite"},
    "hdr.controls_spotfire": {"en": "spotfire_controls", "it": "controlli_spotfire"},
    "hdr.images": {"en": "images", "it": "immagini"},
    "hdr.script_tags": {"en": "script_tags_in_html", "it": "tag_script_nell_html"},
    "hdr.sql_lines": {"en": "sql_lines", "it": "righe_sql"},
    "hdr.table_name": {"en": "table_name", "it": "nome_tabella"},
    "hdr.source_type": {"en": "source_type", "it": "tipo_sorgente"},
    "hdr.database_object": {"en": "database_object", "it": "oggetto_database"},
    "hdr.database_object_type": {"en": "database_object_type", "it": "tipo_oggetto_database"},
    "hdr.context": {"en": "context", "it": "contesto"},
    "hdr.key": {"en": "key", "it": "chiave"},
    "hdr.full_type": {"en": "full_type", "it": "tipo_completo"},
    "hdr.in_document": {"en": "in_document", "it": "nel_documento"},
    "hdr.in_bookmarks": {"en": "in_bookmarks", "it": "nei_segnalibri"},
    "hdr.entry": {"en": "entry", "it": "voce"},
    "hdr.size_bytes": {"en": "size_bytes", "it": "dimensione_byte"},
    "hdr.compressed_bytes": {"en": "compressed_size_bytes", "it": "dimensione_compressa_byte"},
    "hdr.yes": {"en": "yes", "it": "si"},
    "hdr.no": {"en": "no", "it": "no"},
    # -- export sheet names ---------------------------------------------------
    "sheet.scripts": {"en": "script", "it": "script"},
    "sheet.pages": {"en": "pages", "it": "pagine"},
    "sheet.visual_objects": {"en": "visual_objects", "it": "oggetti_visivi"},
    "sheet.document_properties": {"en": "document_properties", "it": "document_properties"},
    "sheet.all_properties": {"en": "all_properties", "it": "tutte_le_proprieta"},
    "sheet.calculated_columns": {"en": "calculated_columns", "it": "colonne_calcolate"},
    "sheet.data_functions": {"en": "data_functions", "it": "data_function"},
    "sheet.text_areas": {"en": "text_areas", "it": "text_area"},
    "sheet.custom_queries": {"en": "custom_queries", "it": "query_personalizzate"},
    "sheet.source_tables": {"en": "source_tables", "it": "tabelle_sorgente"},
    "sheet.connections": {"en": "connections", "it": "connessioni"},
    "sheet.object_types": {"en": "object_types", "it": "tipi_oggetto"},
    "sheet.archive_content": {"en": "archive_content", "it": "contenuto_archivio"},
    "sheet.summary": {"en": "dashboard_summary", "it": "riepilogo_dashboard"},
}


def t(key: str, lang: str = DEFAULT_LANG, **kwargs) -> str:
    lang = normalize_lang(lang)
    entry = CATALOG.get(key)
    if entry is None:
        return key
    text = entry.get(lang) or entry.get(DEFAULT_LANG) or key
    return text.format(**kwargs) if kwargs else text
