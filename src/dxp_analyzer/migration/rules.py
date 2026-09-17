"""Migration rules mapping Spotfire features to Power BI / Databricks.

Each rule is bilingual (``en`` default, ``it``). A rule fires when its regex
matches a script, expression or property value; the matched rules drive both the
migration report and the complexity/effort model.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Dict, List, Tuple

from ..i18n import DEFAULT_LANG, normalize_lang

# -- outcomes (machine keys; localized via i18n "outcome.*") -------------------
NATIVE = "native"
WORKAROUND = "workaround"
NON_NATIVE = "not_native"

OUTCOME_ORDER = {NATIVE: 0, WORKAROUND: 1, NON_NATIVE: 2}
OUTCOME_POINTS = {NATIVE: 0, WORKAROUND: 1, NON_NATIVE: 3}
OUTCOME_I18N = {NATIVE: "outcome.native", WORKAROUND: "outcome.workaround", NON_NATIVE: "outcome.not_native"}


def _loc(value, lang: str) -> str:
    """Pick a language from a {en, it} dict (or return a plain string)."""
    if isinstance(value, dict):
        lang = normalize_lang(lang)
        return value.get(lang) or value.get(DEFAULT_LANG) or ""
    return value or ""


@dataclass
class Rule:
    key: str
    pattern: "re.Pattern"
    outcome: str
    name: Dict[str, str]
    spotfire: Dict[str, str]
    power_bi: Dict[str, str]
    databricks: Dict[str, str] = field(default_factory=dict)

    def name_of(self, lang: str) -> str:
        return _loc(self.name, lang)

    def localized(self, lang: str) -> Dict[str, str]:
        return {
            "name": _loc(self.name, lang),
            "outcome": self.outcome,
            "spotfire": _loc(self.spotfire, lang),
            "power_bi": _loc(self.power_bi, lang),
            "databricks": _loc(self.databricks, lang),
        }


def _rule(key, pattern, outcome, name_en, name_it, sf_en, sf_it, pb_en, pb_it,
          db_en="", db_it="", flags=re.I) -> Rule:
    return Rule(
        key=key,
        pattern=re.compile(pattern, flags),
        outcome=outcome,
        name={"en": name_en, "it": name_it},
        spotfire={"en": sf_en, "it": sf_it},
        power_bi={"en": pb_en, "it": pb_it},
        databricks={"en": db_en, "it": db_it},
    )


IRONPYTHON_RULES: List[Rule] = [
    _rule("page_navigation", r"ActivePageReference|PageNavigation", NATIVE,
          "Page navigation", "Navigazione pagine",
          "The script changes the active page.", "Lo script cambia la pagina attiva.",
          "Button with a Page navigation action.", "Pulsante con azione Navigazione pagina."),
    _rule("document_properties_code", r"Document\.Properties|DocumentProperty", WORKAROUND,
          "Document properties from code", "Document properties da codice",
          "The script reads or writes document variables.", "Lo script legge o scrive variabili del documento.",
          "Field parameters or disconnected tables used in slicers. The value cannot be set from code.",
          "Parametri di campo o tabelle scollegate usate negli slicer. Il valore non si imposta da codice.",
          "Value lists can live in a parameter table.", "Le liste di valori possono stare in una tabella di parametri."),
    _rule("filters_code",
          r"FilterPanel|FilteringScheme|ListBoxFilter|CheckBoxFilter|RangeFilter|ItemFilter|RadioButtonFilter|TextFilter|HierarchyFilter|ResetAllFilters",
          WORKAROUND,
          "Filters from code", "Filtri da codice",
          "The script sets or resets filters.", "Lo script imposta o azzera i filtri.",
          "Slicers and bookmarks. Reset via a button linked to a bookmark.",
          "Slicer e segnalibri. Il reset si fa con un pulsante collegato a un segnalibro.",
          "Fixed filters are applied directly in the views.", "I filtri fissi si applicano direttamente nelle viste."),
    _rule("marking", r"Marking|DataMarkingSelection|SetSelection|IndexSet", WORKAROUND,
          "Marking", "Marking",
          "The script uses the rows selected in a chart.", "Lo script usa le righe selezionate in un grafico.",
          "Cross-visual interactions and drill-through. The selection is not readable as a list of rows.",
          "Interazioni tra visual e drill through. La selezione non è leggibile come elenco di righe."),
    _rule("dynamic_axes", r"XAxis|YAxis|ColorAxis|CategoryAxis|ValueAxis|MeasureAxis", WORKAROUND,
          "Dynamic axes", "Assi dinamici",
          "The script changes columns or measures on the axes.", "Lo script cambia colonne o misure sugli assi.",
          "Field parameters to choose what to show on the axes.", "Parametri di campo per scegliere cosa mostrare sugli assi."),
    _rule("visual_properties_code", r"\.Title\s*=|\.Visible\s*=|Visuals\.(?:Add|Remove)", WORKAROUND,
          "Visual properties from code", "Proprietà dei visual da codice",
          "The script changes chart title or visibility.", "Lo script cambia titolo o visibilità dei grafici.",
          "Dynamic title from a measure. Visibility via bookmarks and the Selection pane.",
          "Titolo dinamico da misura. Visibilità con segnalibri e riquadro Selezione."),
    _rule("text_area_code", r"HtmlContent", WORKAROUND,
          "Text area from code", "Text area da codice",
          "The script rewrites the content of a text area.", "Lo script riscrive il contenuto di una text area.",
          "Text box or card with values computed from measures.", "Casella di testo o scheda con valori calcolati da misure."),
    _rule("color_rules", r"ColorRule|AddFixedColorRule|AddThresholdRule|Coloring", NATIVE,
          "Color rules", "Regole colore",
          "The script sets color rules.", "Lo script imposta regole di colore.",
          "Conditional formatting.", "Formattazione condizionale."),
    _rule("bookmarks_code", r"Bookmark", NATIVE,
          "Bookmarks", "Segnalibri",
          "The script applies bookmarks.", "Lo script applica segnalibri.",
          "Bookmarks triggered by buttons.", "Segnalibri richiamati da pulsanti."),
    _rule("data_refresh", r"\.Refresh\(|ReloadAllData|ReloadData|RefreshAsync|InvalidateData", NON_NATIVE,
          "Data refresh", "Refresh dati",
          "The script reloads data on user request.", "Lo script ricarica i dati quando l'utente lo chiede.",
          "The report has no refresh button. Use scheduled refresh or DirectQuery.",
          "Nel report non esiste un pulsante di refresh. Si usa il refresh pianificato oppure DirectQuery.",
          "Jobs that refresh the tables at the required frequency.", "Job che aggiornano le tabelle alla frequenza richiesta."),
    _rule("modify_data_tables",
          r"AddRows|ReplaceData|RemoveRows|DataFlowBuilder|TextFileDataSource|SbdfLibraryDataSource|AddDataTable",
          NON_NATIVE,
          "Modify data tables", "Modifica tabelle dati",
          "The script adds, replaces or loads tables at runtime.", "Lo script aggiunge, sostituisce o carica tabelle durante l'uso.",
          "Not possible: the report data model is fixed.", "Non possibile: il modello dati del report è fisso.",
          "Move the logic to a notebook or pipeline that produces the final table.",
          "Spostare la logica in un notebook o in una pipeline che produce la tabella finale."),
    _rule("columns_from_code", r"AddCalculatedColumn|AddTransformation|AddBinnedColumn", WORKAROUND,
          "Columns created from code", "Colonne create da codice",
          "The script creates calculated columns or transformations.", "Lo script crea colonne calcolate o trasformazioni.",
          "Define the columns beforehand in DAX or Power Query.", "Definire le colonne in anticipo in DAX o Power Query.",
          "Compute the columns directly in the tables.", "Calcolare le colonne direttamente nelle tabelle."),
    _rule("row_by_row", r"DataValueCursor|CreateCursor|GetDistinctRowValues|GetRows", WORKAROUND,
          "Row-by-row data reads", "Lettura dei dati riga per riga",
          "The script iterates data row by row.", "Lo script scorre i dati riga per riga.",
          "Rewrite the logic as a DAX measure (SUMX, FILTER, CALCULATE).",
          "Riscrivere la logica come misura DAX (SUMX, FILTER, CALCULATE).",
          "For heavy computation use SQL or PySpark.", "Per calcoli pesanti usare SQL o PySpark."),
    _rule("file_io", r"System\.IO|StreamWriter|StreamReader|File\.(?:Write|Read|Open|Exists|Copy|Delete)", NON_NATIVE,
          "File read or write", "Lettura o scrittura file",
          "The script reads or writes files.", "Lo script legge o scrive file.",
          "Not possible from the report.", "Non possibile dal report.",
          "Read and write files on Unity Catalog volumes.", "Lettura e scrittura file su volumi Unity Catalog."),
    _rule("export", r"Export\w*\(|PowerPoint|PdfExport", WORKAROUND,
          "Export", "Export",
          "The script exports PDF, images or data.", "Lo script esporta PDF, immagini o dati.",
          "Export from the service menu or email subscriptions. Cannot be automated from a button.",
          "Export dal menu del servizio o sottoscrizioni email. Non automatizzabile da un pulsante.",
          "Periodic extracts generated by jobs.", "Estrazioni periodiche generate da job."),
    _rule("web_api", r"System\.Net|WebClient|HttpWebRequest|HttpClient|urllib", NON_NATIVE,
          "Web or API calls", "Chiamate web o API",
          "The script calls an external service.", "Lo script chiama un servizio esterno.",
          "Web calls only during refresh (Web.Contents), never on user action.",
          "Chiamate web solo durante il refresh (Web.Contents), mai su azione dell'utente.",
          "Data ingestion via jobs.", "Ingestione dei dati tramite job."),
    _rule("db_write",
          r"SqlConnection|OdbcConnection|OleDbConnection|ExecuteNonQuery|INSERT\s+INTO|UPDATE\s+\w+\s+SET|DELETE\s+FROM",
          NON_NATIVE,
          "Database write", "Scrittura su database",
          "The script writes data to a database.", "Lo script scrive dati su un database.",
          "The report does not write data.", "Il report non scrive dati.",
          "Update tables with MERGE from jobs. User data entry requires an external app.",
          "Aggiornamento tabelle con MERGE da job. L'inserimento dati da parte dell'utente richiede un'app esterna."),
    _rule("data_function_call", r"DataFunction", NON_NATIVE,
          "Data function execution", "Esecuzione data function",
          "The script triggers an R or Python data function.", "Lo script avvia una data function R o Python.",
          "No reliable equivalent.", "Nessun equivalente affidabile.",
          "Rewrite as a notebook and save the result to a table.", "Riscrivere come notebook e salvare il risultato in una tabella."),
    _rule("popups", r"MessageBox|System\.Windows|NotificationService|ProgressService", NON_NATIVE,
          "Popups and notifications", "Popup e notifiche",
          "The script shows dialogs or messages.", "Lo script mostra finestre o messaggi.",
          "No popups. Show a panel via a bookmark or a page tooltip.",
          "Nessun popup. Pannello mostrato con un segnalibro oppure tooltip di pagina."),
    _rule("background_timers", r"\bThread\b|BeginInvoke|\bTimer\b|time\.sleep", NON_NATIVE,
          "Background or timed actions", "Azioni in background o a tempo",
          "The script runs actions in the background or at intervals.", "Lo script esegue azioni in background o a intervalli.",
          "Not available. Automatic page refresh exists only with DirectQuery.",
          "Non disponibile. L'aggiornamento automatico della pagina esiste solo con DirectQuery."),
    _rule("send_email", r"SmtpClient|MailMessage", NON_NATIVE,
          "Email sending", "Invio email",
          "The script sends email.", "Lo script invia email.",
          "Subscriptions and alerts, scheduled only.", "Sottoscrizioni e avvisi, solo pianificati.",
          "Job notifications.", "Notifiche dei job."),
    _rule("per_user_logic", r"UserName|CurrentPrincipal|UserService", WORKAROUND,
          "Per-user logic", "Logica per utente",
          "The script changes behavior based on the user.", "Lo script cambia comportamento in base all'utente.",
          "USERPRINCIPALNAME and row-level security (RLS).", "USERPRINCIPALNAME e sicurezza a livello di riga (RLS).",
          "A mapping table between users and scopes.", "Tabella di mappatura tra utenti e perimetri."),
    _rule("layout_code", r"PageLayout|LayoutDefinition|BeginSideBySideSection|AutoConfigure", NON_NATIVE,
          "Layout from code", "Layout da codice",
          "The script changes the page layout.", "Lo script modifica la disposizione della pagina.",
          "Fixed layout. You can only show or hide groups of objects via bookmarks.",
          "Layout fisso. Si possono solo mostrare o nascondere gruppi di oggetti con i segnalibri."),
    _rule("dotnet_libs", r"clr\.AddReference", NON_NATIVE,
          ".NET libraries", "Librerie .NET",
          "The script loads .NET libraries.", "Lo script carica librerie .NET.",
          "No equivalent. The script's effect must be understood to choose an alternative.",
          "Nessun equivalente. Va capito l'effetto dello script per scegliere un'alternativa."),
]

JAVASCRIPT_RULES: List[Rule] = [
    _rule("js_dom_style", r"getElementById|querySelector|getElementsBy|\$\(|jQuery|innerHTML|\.css\(", NON_NATIVE,
          "HTML and style manipulation", "Modifica HTML e stile",
          "The code changes the page's HTML and style.", "Il codice modifica HTML e stile della pagina.",
          "Not possible. Appearance is handled with a JSON theme and visual formatting.",
          "Non possibile. L'aspetto si gestisce con tema JSON e formattazione dei visual."),
    _rule("js_show_hide", r"\.hide\(|\.show\(|\.toggle\(", WORKAROUND,
          "Show and hide elements", "Mostra e nascondi elementi",
          "The code shows or hides elements.", "Il codice mostra o nasconde elementi.",
          "Bookmarks with the Selection pane, triggered by buttons.",
          "Segnalibri con riquadro Selezione, richiamati da pulsanti."),
    _rule("js_events", r"\.click\(|\.trigger\(|addEventListener|\.on\(", WORKAROUND,
          "Events and clicks", "Eventi e click",
          "The code reacts to or simulates clicks.", "Il codice reagisce ai click o li simula.",
          "Buttons with a native action. You cannot chain multiple actions.",
          "Pulsanti con azione nativa. Non si possono concatenare più azioni."),
    _rule("js_timers", r"setInterval|setTimeout", NON_NATIVE,
          "Timers", "Timer",
          "The code runs actions at intervals.", "Il codice esegue azioni a intervalli.",
          "Not available. Automatic page refresh only with DirectQuery.",
          "Non disponibile. Aggiornamento automatico della pagina solo con DirectQuery.",
          "Tables refreshed by frequent jobs.", "Tabelle aggiornate da job frequenti."),
    _rule("js_network", r"fetch\(|XMLHttpRequest|\$\.ajax|axios", NON_NATIVE,
          "Network calls from the browser", "Chiamate di rete dal browser",
          "The code downloads data from external services.", "Il codice scarica dati da servizi esterni.",
          "Not possible from the report.", "Non possibile dal report.",
          "Data ingestion via jobs.", "Ingestione dei dati tramite job."),
    _rule("js_ext_charts", r"\bd3\.|Highcharts|echarts|plotly|google\.visualization", NON_NATIVE,
          "External charting libraries", "Librerie grafiche esterne",
          "The code draws charts with external libraries.", "Il codice disegna grafici con librerie esterne.",
          "Use the closest standard visual.", "Usare il visual standard più simile."),
    _rule("js_browser_storage", r"localStorage|sessionStorage|document\.cookie", NON_NATIVE,
          "Browser storage", "Memoria del browser",
          "The code saves settings in the browser.", "Il codice salva impostazioni nel browser.",
          "Partly covered by the service's persistent filters.", "Coperto in parte dai filtri persistenti del servizio."),
    _rule("js_tooltip_modal", r"tooltip|popover|modal|alert\(", WORKAROUND,
          "Tooltips and dialogs", "Tooltip e finestre",
          "The code shows tooltips or dialogs.", "Il codice mostra tooltip o finestre.",
          "Page tooltips.", "Tooltip di pagina."),
    _rule("js_css", r"<style|addClass|removeClass|classList", WORKAROUND,
          "CSS styles", "Stili CSS",
          "The code applies CSS styles.", "Il codice applica stili CSS.",
          "JSON theme, with fewer customization options.", "Tema JSON, con meno possibilità di personalizzazione."),
    _rule("js_inputs", r"<input|\.val\(|keyup|keydown", WORKAROUND,
          "Input fields", "Campi di input",
          "The code uses input fields.", "Il codice usa campi di input.",
          "Search-enabled slicers or what-if parameters. There is no free text field.",
          "Slicer con ricerca o parametri what if. Non esiste un campo di testo libero."),
]

EXPRESSION_RULES: List[Rule] = [
    _rule("expr_over", r"\bOVER\b", WORKAROUND,
          "Per-group calculations (OVER)", "Calcoli per gruppo (OVER)",
          "Expression with a per-group or cumulative calculation.", "Espressione con calcolo per gruppo o cumulato.",
          "DAX measure with CALCULATE or WINDOW.", "Misura DAX con CALCULATE o WINDOW.",
          "Precompute with a SQL window function.", "Precalcolo con window function SQL."),
    _rule("expr_period_compare", r"Intersect\(|Previous\(|AllPrevious\(|NavigatePeriod\(|ParallelPeriod\(", WORKAROUND,
          "Period-over-period comparison", "Confronto tra periodi",
          "Expression comparing different periods.", "Espressione che confronta periodi diversi.",
          "Time-intelligence functions with a calendar table.", "Funzioni di time intelligence con tabella calendario."),
    _rule("expr_rank", r"\b(?:Dense)?Rank\(", WORKAROUND,
          "Rankings (Rank)", "Classifiche (Rank)",
          "Expression computing a ranking.", "Espressione che calcola una classifica.",
          "RANKX function.", "Funzione RANKX.",
          "SQL window function.", "Window function SQL."),
    _rule("expr_regex", r"\bRX\w+\(", NON_NATIVE,
          "Regular expressions", "Espressioni regolari",
          "Expression using regular expressions.", "Espressione con espressioni regolari.",
          "Not available in DAX.", "Non disponibili in DAX.",
          "Compute in SQL or Power Query.", "Calcolo in SQL o Power Query."),
    _rule("expr_doc_props", r"\$\{[^}]+\}|DocumentProperty\(", WORKAROUND,
          "Use of document properties", "Uso di document properties",
          "Expression using a document property.", "Espressione che usa una document property.",
          "A parameter or slicer read with SELECTEDVALUE.", "Parametro o slicer letto con SELECTEDVALUE."),
    _rule("expr_case", r"\bcase\b", NATIVE,
          "Conditions (case)", "Condizioni (case)",
          "Expression with conditions.", "Espressione con condizioni.",
          "SWITCH function in DAX.", "Funzione SWITCH in DAX."),
]


# Visual type -> (equivalent {en, it}, outcome)
VISUAL_MAP: Dict[str, Tuple[Dict[str, str], str]] = {
    "BarChart": ({"en": "Bar chart", "it": "Grafico a barre"}, NATIVE),
    "LineChart": ({"en": "Line chart", "it": "Grafico a linee"}, NATIVE),
    "CombinationChart": ({"en": "Line and column chart", "it": "Grafico a linee e colonne"}, NATIVE),
    "CrossTablePlot": ({"en": "Matrix", "it": "Matrice"}, NATIVE),
    "TablePlot": ({"en": "Table", "it": "Tabella"}, NATIVE),
    "SummaryTable": ({"en": "Matrix with statistical DAX measures", "it": "Matrice con misure statistiche in DAX"}, WORKAROUND),
    "ScatterPlot": ({"en": "Scatter chart", "it": "Grafico a dispersione"}, NATIVE),
    "ScatterPlot3D": ({"en": "No 3D chart; use a 2D scatter chart", "it": "Nessun grafico 3D, usare un grafico a dispersione 2D"}, NON_NATIVE),
    "PieChart": ({"en": "Pie or donut chart", "it": "Grafico a torta o ad anello"}, NATIVE),
    "Treemap": ({"en": "Treemap", "it": "Mappa ad albero"}, NATIVE),
    "TreeMap": ({"en": "Treemap", "it": "Mappa ad albero"}, NATIVE),
    "HeatMap": ({"en": "Matrix with conditional background color", "it": "Matrice con colore di sfondo condizionale"}, WORKAROUND),
    "BoxPlot": ({"en": "No box plot; approximate with standard charts", "it": "Nessun box plot, approssimare con grafici standard"}, NON_NATIVE),
    "GraphicalTable": ({"en": "Table with sparklines and icons", "it": "Tabella con sparkline e icone"}, WORKAROUND),
    "KpiChart": ({"en": "Card or KPI", "it": "Scheda o KPI"}, NATIVE),
    "KPIChart": ({"en": "Card or KPI", "it": "Scheda o KPI"}, NATIVE),
    "WaterfallChart": ({"en": "Waterfall chart", "it": "Grafico a cascata"}, NATIVE),
    "ParallelCoordinatePlot": ({"en": "No equivalent", "it": "Nessun equivalente"}, NON_NATIVE),
    "MapChart": ({"en": "Map or Azure Maps, with fewer layers", "it": "Mappa o Azure Maps, con meno livelli"}, WORKAROUND),
    "HtmlTextArea": ({"en": "Text box, buttons and slicers", "it": "Casella di testo, pulsanti e slicer"}, WORKAROUND),
    "TextArea": ({"en": "Text box, buttons and slicers", "it": "Casella di testo, pulsanti e slicer"}, WORKAROUND),
}


# Source nature -> (outcome, power_bi {en, it}, databricks {en, it})
SOURCE_MAP: Dict[str, Tuple[str, Dict[str, str], Dict[str, str]]] = {
    "custom_query": (NATIVE,
                     {"en": "SQL query in the connection or a database view.", "it": "Query SQL nella connessione o vista sul database."},
                     {"en": "A view in Unity Catalog with the same query.", "it": "Vista in Unity Catalog con la stessa query."}),
    "database_table": (NATIVE,
                       {"en": "Direct connection to the table or view.", "it": "Connessione diretta alla tabella o vista."},
                       {"en": "A table or view in Unity Catalog.", "it": "Tabella o vista in Unity Catalog."}),
    "information_link": (WORKAROUND,
                         {"en": "Retrieve the underlying query from the Spotfire library and recreate it.",
                          "it": "Recuperare dalla libreria Spotfire la query sottostante e ricrearla."},
                         {"en": "A view in Unity Catalog with the retrieved query.",
                          "it": "Vista in Unity Catalog con la query recuperata."}),
    "undetermined": (WORKAROUND,
                     {"en": "To be verified by opening the dashboard.", "it": "Da verificare aprendo la dashboard."},
                     {"en": "", "it": ""}),
}


def visual_equivalent(type_name: str, lang: str) -> Tuple[str, str]:
    """(localized equivalent, outcome) for a visual type; falls back to 'to verify'."""
    entry = VISUAL_MAP.get(type_name)
    if entry is None:
        from ..i18n import t
        return t("generic.to_verify", lang), WORKAROUND
    return _loc(entry[0], lang), entry[1]


def source_mapping(nature: str, lang: str) -> Tuple[str, str, str]:
    """(outcome, localized power_bi, localized databricks) for a source nature."""
    outcome, power_bi, databricks = SOURCE_MAP.get(nature, SOURCE_MAP["undetermined"])
    return outcome, _loc(power_bi, lang), _loc(databricks, lang)


def matching_rules(text: str, rules: List[Rule]) -> List[Rule]:
    return [r for r in rules if r.pattern.search(text or "")]


def worst_outcome(outcomes) -> str:
    outcomes = list(outcomes)
    return max(outcomes, key=lambda o: OUTCOME_ORDER[o]) if outcomes else ""
