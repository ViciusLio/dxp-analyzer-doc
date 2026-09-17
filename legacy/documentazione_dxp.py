import gzip
import hashlib
import re
import sys
import unicodedata
import zipfile
import zlib
import xml.etree.ElementTree as ET
from collections import Counter, OrderedDict
from datetime import datetime
from pathlib import Path


CARTELLA_DXP = Path("input")

FILE_DXP = []

CARTELLA_DOCUMENTAZIONE = Path("output")

FILE_DOCUMENTAZIONE = CARTELLA_DOCUMENTAZIONE / "documentazione_migrazione.md"


DIMENSIONE_MASSIMA_TESTO = 50 * 1024 * 1024

ESTENSIONI_BINARIE = {".sbdf", ".stdf", ".png", ".jpg", ".jpeg", ".gif", ".bmp", ".ico", ".dll", ".exe", ".zip", ".pdf"}

ESTENSIONI_IMMAGINE = {".png", ".jpg", ".jpeg", ".gif", ".bmp", ".ico", ".svg"}

TIPI_ISTANTANEA = re.compile(r"Bookmark|Snapshot|Undo|History")

CHIAVI_CODICE = {"scriptcode", "code", "script", "scripttext", "source", "sourcecode", "body", "text", "content"}

PROPRIETA_SCHEDA_GENERAL = {"description", "keywords", "allowwebplayerresume", "publicbookmarkcreation", "privatebookmarkcreation", "name", "title", "author", "comments"}

CHIAVI_NOME = ("name", "title", "displayname", "scriptname", "caption", "titleexpression")

TIPI_VISUAL = {
    "BarChart", "LineChart", "CombinationChart", "CrossTablePlot", "TablePlot", "SummaryTable", "ScatterPlot",
    "ScatterPlot3D", "PieChart", "Treemap", "TreeMap", "HeatMap", "BoxPlot", "GraphicalTable", "KpiChart",
    "KPIChart", "WaterfallChart", "ParallelCoordinatePlot", "MapChart", "HtmlTextArea", "TextArea",
}

TIPI_TEXT_AREA = {"HtmlTextArea", "TextArea"}

SEGNALI_PYTHON = [re.compile(x, re.M) for x in (
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

SEGNALI_JS = [re.compile(x, re.M) for x in (
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




def impronta(testo):
    return hashlib.md5(re.sub(r"\s+", "", testo or "").encode("utf-8", "ignore")).hexdigest()


def pulisci_nome(testo, lunghezza=80):
    pulito = re.sub(r"[<>:\"/\\|?*\x00-\x1f]", "_", str(testo or "")).strip().strip(".")
    pulito = re.sub(r"\s+", " ", pulito)
    return pulito[:lunghezza].strip() or "senza nome"


def tipo_base(tipo):
    return (tipo or "").split(",")[0].strip()


def ultimo_segmento(tipo):
    base = tipo_base(tipo).split("`")[0]
    return re.split(r"[.+]", base)[-1] if base else ""


def chiave_campo(nome):
    return re.sub(r"^(?:m_|_)+", "", (nome or "").lower())


def normalizza_percorso(percorso):
    return (percorso or "").replace("\\", "/").lstrip("/").lower()


def testo_leggibile(testo):
    campione = testo[:4000]
    if not campione:
        return False
    buoni = sum(1 for c in campione if (ord(c) < 0x250 and (c.isprintable() or c in "\r\n\t")))
    return buoni / len(campione) > 0.9


def decodifica_bytes(raw):
    dati = raw
    if dati[:2] == b"\x1f\x8b":
        try:
            dati = gzip.decompress(dati)
        except Exception:
            pass
    elif dati[:1] == b"\x78":
        try:
            dati = zlib.decompress(dati)
        except Exception:
            pass
    if dati[:3] == b"\xef\xbb\xbf":
        codifiche = ["utf-8-sig"]
    elif dati[:2] in (b"\xff\xfe", b"\xfe\xff"):
        codifiche = ["utf-16"]
    else:
        codifiche = ["utf-8", "utf-16", "cp1252"]
    for codifica in codifiche:
        try:
            testo = dati.decode(codifica)
        except (UnicodeDecodeError, LookupError):
            continue
        if testo_leggibile(testo):
            return testo
    return None


def punti_codice(testo):
    campione = (testo or "")[:200000]
    return (
        sum(1 for r in SEGNALI_PYTHON if r.search(campione)),
        sum(1 for r in SEGNALI_JS if r.search(campione)),
    )


def indovina_linguaggio(testo, rigoroso=True):
    if not testo or not testo.strip():
        return None
    punti_py, punti_js = punti_codice(testo)
    if not rigoroso:
        return "JavaScript" if punti_js > punti_py else "IronPython"
    if punti_py >= 3 and punti_py > punti_js:
        return "IronPython"
    if punti_js >= 3 and punti_js > punti_py and ("{" in testo or ";" in testo):
        return "JavaScript"
    return None


def linguaggio_dichiarato(dichiarato):
    valore = (dichiarato or "").strip().lower()
    if "javascript" in valore or valore in {"js", "jscript"}:
        return "JavaScript"
    if "ironpython" in valore:
        return "IronPython"
    if "python" in valore:
        return "Python"
    return None




def e_visual(tipo):
    base = tipo_base(tipo)
    return "+" not in base and base.startswith("Spotfire.Dxp.Application.Visuals") and ultimo_segmento(tipo) in TIPI_VISUAL



class AnalizzatoreDxp:

    def __init__(self, percorso):
        self.percorso = Path(percorso)
        self.nome = self.percorso.stem
        self.xml = OrderedDict()
        self.indici = OrderedDict()
        self.testi = {}
        self.testi_normalizzati = {}
        self.voci_zip = []
        self.immagini = []
        self.risorse = []
        self.risorse_per_id = {}
        self.risorse_per_nome = {}
        self.riferimenti_risorse = {}
        self.cache_tipo = {}
        self.cache_istantanea = {}
        self.tipi_vivi = Counter()
        self.tipi_istantanea = Counter()
        self.oggetti_script = []
        self.oggetti_data_function = []
        self.oggetti_proprieta = []
        self.oggetti_colonne_calcolate = []
        self.segnalibri = 0
        self.pagine = []
        self.visual = Counter()
        self.text_area = []
        self.script = []
        self.data_function = []
        self.hash_data_function = set()
        self.proprieta = []
        self.proprieta_documento = []
        self.proprieta_documento_standard = []
        self.proprieta_citate = {}
        self.colonne_calcolate = []
        self.query = []
        self.nomi_query = set()
        self.hash_query = set()
        self.connessioni = []
        self.connessioni_viste = set()
        self.copie_documento = []
        self.file_principale = None
        self.nome_risorsa_per_file = {}
        self.tabelle_sorgente = []
        self.tabelle_viste = set()
        self.avvisi = []
        self.errori = []

    def esegui(self):
        self.carica_archivio()
        self.indicizza()
        self.censisci_oggetti()
        self.estrai_pagine_e_visual()
        self.estrai_data_function()
        self.estrai_script()
        self.estrai_proprieta()
        self.estrai_colonne_calcolate()
        self.estrai_query_e_connessioni()
        self.estrai_tabelle_sorgente()

    def parse_xml(self, dati):
        try:
            if isinstance(dati, bytes):
                radice = ET.fromstring(dati)
            else:
                radice = ET.fromstring(re.sub(r"^\s*<\?xml[^>]*\?>", "", dati))
        except (ET.ParseError, ValueError):
            if isinstance(dati, bytes):
                testo = decodifica_bytes(dati)
                if testo:
                    return self.parse_xml(testo)
            return None
        for elemento in radice.iter():
            if isinstance(elemento.tag, str) and "}" in elemento.tag:
                elemento.tag = elemento.tag.rsplit("}", 1)[1]
            if any("}" in k for k in elemento.attrib):
                elemento.attrib = {k.rsplit("}", 1)[-1]: v for k, v in elemento.attrib.items()}
        return radice

    def carica_archivio(self):
        with zipfile.ZipFile(self.percorso, "r") as zf:
            for info in zf.infolist():
                if info.is_dir():
                    continue
                nome = info.filename
                self.voci_zip.append((nome, info.file_size, info.compress_size))
                estensione = Path(nome).suffix.lower()
                if estensione in ESTENSIONI_IMMAGINE:
                    self.immagini.append(nome)
                if estensione in ESTENSIONI_BINARIE or info.file_size > DIMENSIONE_MASSIMA_TESTO:
                    continue
                try:
                    raw = zf.read(info)
                except Exception as e:
                    self.errori.append(f"Lettura non riuscita di {nome}: {e}")
                    continue
                if raw.startswith(b"\x89PNG") or raw.startswith(b"\xff\xd8\xff") or raw.startswith(b"GIF8"):
                    self.immagini.append(nome)
                    continue
                if estensione == ".xml" or raw.lstrip()[:5] == b"<?xml":
                    radice = self.parse_xml(raw)
                    if radice is not None:
                        self.xml[nome] = radice
                        continue
                testo = decodifica_bytes(raw)
                if testo is None:
                    continue
                if testo.lstrip().startswith("<?xml"):
                    radice = self.parse_xml(testo)
                    if radice is not None:
                        self.xml[nome] = radice
                        continue
                self.testi[nome] = testo
                normalizzato = normalizza_percorso(nome)
                self.testi_normalizzati[normalizzato] = testo
                self.testi_normalizzati.setdefault(normalizzato.split("/")[-1], testo)
                base = nome.replace("\\", "/").split("/")[-1]
                if not base.isdigit():
                    self.risorse_per_nome.setdefault(base, nome)

    def indicizza(self):
        for nome_file, radice in self.xml.items():
            indice = {"file": nome_file, "tipi": {}, "stringhe": {}, "oggetti": {}, "genitori": {}}
            for padre in radice.iter():
                for figlio in padre:
                    indice["genitori"][figlio] = padre
            for elemento in radice.iter():
                tag = elemento.tag
                if not isinstance(tag, str):
                    continue
                ident = elemento.get("Id")
                if tag == "TypeObject" and ident is not None:
                    indice["tipi"][ident] = elemento.get("FullTypeName", "")
                elif tag == "Object" and ident is not None:
                    indice["oggetti"][ident] = elemento
                elif tag == "String" and ident is not None:
                    indice["stringhe"][ident] = elemento.get("Value", elemento.text or "")
                percorso = elemento.get("ArchiveElementPath") or elemento.get("Path")
                if "resource" in tag.lower() and percorso:
                    ident_risorsa = elemento.get("Id") or elemento.get("ResourceId") or ""
                    nome_risorsa = elemento.get("Name", "")
                    self.risorse.append({"id": ident_risorsa, "nome": nome_risorsa, "percorso": percorso})
                    if ident_risorsa:
                        self.risorse_per_id[ident_risorsa] = percorso
                    for chiave in (nome_risorsa, percorso, percorso.replace("\\", "/").split("/")[-1]):
                        if chiave and not chiave.isdigit():
                            self.risorse_per_nome[chiave] = percorso
            self.indici[nome_file] = indice
        documenti = []
        for nome_file, radice in self.xml.items():
            indice = self.indici[nome_file]
            indice["copia"] = False
            for oggetto in radice.iter("Object"):
                if tipo_base(self.tipo_oggetto(oggetto, indice)) == "Spotfire.Dxp.Application.Document":
                    documenti.append(nome_file)
                    break
        principale = next((f for f in documenti if f.lower().endswith("analysisdocument.xml")), documenti[0] if documenti else None)
        for nome_file in documenti:
            if nome_file != principale:
                self.indici[nome_file]["copia"] = True
                self.copie_documento.append(nome_file)
        self.file_principale = principale
        self.nome_risorsa_per_file = {normalizza_percorso(r["percorso"]): r["nome"] for r in self.risorse}
        for nome_file, radice in self.xml.items():
            indice = self.indici[nome_file]
            for elemento in radice.iter():
                if not isinstance(elemento.tag, str):
                    continue
                if "resource" in elemento.tag.lower() and (elemento.get("ArchiveElementPath") or elemento.get("Path")):
                    continue
                coppie = list(elemento.attrib.items())
                if elemento.text and len(elemento.text) < 300:
                    coppie.append(("", elemento.text.strip()))
                for chiave, valore in coppie:
                    percorso = self.risorsa_da_valore(valore, chiave, elemento.tag)
                    if percorso:
                        self.riferimenti_risorse.setdefault(normalizza_percorso(percorso), []).append((elemento, indice))

    def risorsa_da_valore(self, valore, chiave, tag):
        if not valore:
            return None
        if valore in self.risorse_per_nome:
            return self.risorse_per_nome[valore]
        indizio = f"{chiave}{tag}".lower()
        if valore in self.risorse_per_id and ("resource" in indizio or "embedded" in indizio or "blob" in indizio):
            return self.risorse_per_id[valore]
        return None

    def testo_risorsa(self, percorso):
        if percorso in self.testi:
            return self.testi[percorso]
        normalizzato = normalizza_percorso(percorso)
        return self.testi_normalizzati.get(normalizzato) or self.testi_normalizzati.get(normalizzato.split("/")[-1])

    def tipo_oggetto(self, oggetto, indice):
        if oggetto in self.cache_tipo:
            return self.cache_tipo[oggetto]
        risultato = ""
        tipo = oggetto.find("Type")
        if tipo is None:
            risultato = oggetto.get("FullTypeName", "")
        else:
            for figlio in tipo:
                if figlio.tag == "TypeObject":
                    risultato = figlio.get("FullTypeName", "")
                    break
                if isinstance(figlio.tag, str) and figlio.tag.endswith("Ref"):
                    risultato = indice["tipi"].get(figlio.get("Value") or figlio.get("Id"), "")
                    break
            if not risultato:
                for valore in tipo.attrib.values():
                    if valore in indice["tipi"]:
                        risultato = indice["tipi"][valore]
                        break
        self.cache_tipo[oggetto] = risultato
        return risultato

    def in_istantanea(self, elemento, indice):
        if indice.get("copia"):
            return True
        genitori = indice["genitori"]
        nodo = genitori.get(elemento)
        catena = []
        esito = False
        while nodo is not None:
            if nodo in self.cache_istantanea:
                esito = self.cache_istantanea[nodo]
                break
            catena.append(nodo)
            if nodo.tag == "Object" and TIPI_ISTANTANEA.search(ultimo_segmento(self.tipo_oggetto(nodo, indice))):
                esito = True
                break
            nodo = genitori.get(nodo)
        for n in catena:
            self.cache_istantanea[n] = esito
        return esito

    def antenati_oggetti(self, elemento, indice, includi_se_stesso=True):
        nodo = elemento if includi_se_stesso else indice["genitori"].get(elemento)
        while nodo is not None:
            if nodo.tag == "Object":
                yield nodo
            nodo = indice["genitori"].get(nodo)

    def catena_tipi(self, elemento, indice, massimo=6):
        tipi = [ultimo_segmento(self.tipo_oggetto(o, indice)) for o in self.antenati_oggetti(elemento, indice)]
        return " dentro ".join(t for t in tipi[:massimo] if t)

    def risolvi(self, elemento, indice):
        if elemento.tag == "Object":
            return elemento
        if isinstance(elemento.tag, str) and elemento.tag.endswith("Ref") and elemento.tag not in ("TypeRef", "StringRef"):
            return indice["oggetti"].get(elemento.get("Value") or elemento.get("Id"))
        return None

    def valore_semplice(self, campo, indice, profondita=2):
        for figlio in campo:
            if figlio.tag == "String":
                valore = figlio.get("Value", figlio.text or "")
                if valore.strip():
                    return valore
            elif isinstance(figlio.tag, str) and figlio.tag.endswith("Ref"):
                valore = indice["stringhe"].get(figlio.get("Value") or figlio.get("Id"))
                if valore:
                    return valore
            elif figlio.tag == "Object" and profondita > 0:
                campi = figlio.find("Fields")
                if campi is None:
                    continue
                for interno in campi:
                    if chiave_campo(interno.get("Name")) in ("expression", "value", "text", "name", "title"):
                        valore = self.valore_semplice(interno, indice, profondita - 1)
                        if valore:
                            return valore
        return ""

    def nome_diretto(self, oggetto, indice):
        campi = oggetto.find("Fields")
        if campi is None:
            return ""
        trovati = {}
        for campo in campi:
            if campo.tag != "Field":
                continue
            chiave = chiave_campo(campo.get("Name"))
            if chiave in CHIAVI_NOME and chiave not in trovati:
                valore = self.valore_semplice(campo, indice)
                if valore:
                    trovati[chiave] = valore
        for chiave in CHIAVI_NOME:
            if chiave in trovati:
                return trovati[chiave].strip()
        return ""

    def raccogli_valori(self, elemento, indice, percorso="", profondita=0):
        risultati = []
        if profondita > 150:
            return risultati
        for figlio in elemento:
            tag = figlio.tag
            if not isinstance(tag, str) or tag == "Type":
                continue
            if tag == "Field":
                nome = figlio.get("Name", "")
                sotto = f"{percorso}.{nome}" if percorso else nome
                risultati.extend(self.raccogli_valori(figlio, indice, sotto, profondita + 1))
                continue
            if tag.endswith("Ref"):
                riferimento = figlio.get("Value") or figlio.get("Id")
                if riferimento in indice["stringhe"]:
                    risultati.append((percorso, indice["stringhe"][riferimento]))
                continue
            valore = figlio.get("Value")
            if valore is None and len(figlio) == 0 and figlio.text and figlio.text.strip():
                valore = figlio.text
            if valore is not None:
                risultati.append((percorso, valore))
            for chiave, v in figlio.attrib.items():
                percorso_risorsa = self.risorsa_da_valore(v, chiave, tag)
                if percorso_risorsa:
                    contenuto = self.testo_risorsa(percorso_risorsa)
                    if contenuto:
                        risultati.append((percorso, contenuto))
            risultati.extend(self.raccogli_valori(figlio, indice, percorso, profondita + 1))
        return risultati

    @staticmethod
    def valore_campo(valori, chiavi, modo="ultimo", escludi=()):
        for percorso, valore in valori:
            minuscolo = percorso.lower()
            if any(e in minuscolo for e in escludi):
                continue
            parti = [chiave_campo(p) for p in minuscolo.split(".") if p]
            if not parti:
                continue
            corrisponde = parti[-1] in chiavi if modo == "ultimo" else any(p in chiavi for p in parti)
            if corrisponde and valore and valore.strip():
                return valore
        return ""

    def censisci_oggetti(self):
        for nome_file, radice in self.xml.items():
            indice = self.indici[nome_file]
            if indice.get("copia"):
                continue
            for oggetto in radice.iter("Object"):
                tipo = self.tipo_oggetto(oggetto, indice)
                if not tipo:
                    continue
                istantanea = self.in_istantanea(oggetto, indice)
                if istantanea:
                    self.tipi_istantanea[tipo] += 1
                else:
                    self.tipi_vivi[tipo] += 1
                ultimo = ultimo_segmento(tipo)
                if ultimo == "Bookmark":
                    self.segnalibri += 1
                if istantanea or "+" in tipo_base(tipo):
                    continue
                if ultimo.endswith("ScriptDefinition"):
                    self.oggetti_script.append((oggetto, indice))
                elif ultimo.endswith("DataFunctionDefinition"):
                    self.oggetti_data_function.append((oggetto, indice))
                elif re.fullmatch(r"DataProperty(?:Impl)?", ultimo):
                    self.oggetti_proprieta.append((oggetto, indice))
                elif ultimo in ("CalculatedColumn", "CalculatedColumnImpl"):
                    self.oggetti_colonne_calcolate.append((oggetto, indice))

    def elementi_collezione(self, oggetto, indice, nome_campo):
        campi = oggetto.find("Fields")
        if campi is None:
            return None
        campo = next((c for c in campi if c.tag == "Field" and chiave_campo(c.get("Name")) == nome_campo), None)
        if campo is None:
            return None
        contenitore = campo
        for figlio in campo:
            risolto = self.risolvi(figlio, indice)
            if risolto is not None:
                contenitore = risolto
                break
        elementi = None
        for interno in contenitore.iter("Field"):
            if chiave_campo(interno.get("Name")) == "items":
                elementi = interno.find(".//Elements")
                break
        if elementi is None:
            elementi = contenitore.find(".//Elements")
        if elementi is None:
            return None
        return [c for c in elementi if self.risolvi(c, indice) is not None]

    def visual_di_pagina(self, pagina, indice, visti, segui_riferimenti):
        risultati = []
        pila = list(reversed(list(pagina)))
        while pila:
            nodo = pila.pop()
            if not isinstance(nodo.tag, str) or nodo.tag == "Type":
                continue
            bersaglio = self.risolvi(nodo, indice)
            if bersaglio is not None:
                if nodo.tag != "Object" and not segui_riferimenti:
                    continue
                tipo = self.tipo_oggetto(bersaglio, indice)
                if e_visual(tipo):
                    if bersaglio not in visti:
                        visti.add(bersaglio)
                        risultati.append((ultimo_segmento(tipo), self.nome_diretto(bersaglio, indice), bersaglio))
                    continue
                if nodo.tag != "Object":
                    continue
            pila.extend(reversed(list(nodo)))
        return risultati

    def primo_visual_interno(self, oggetto, indice):
        pila = list(reversed(list(oggetto)))
        generico = None
        while pila:
            nodo = pila.pop()
            if not isinstance(nodo.tag, str) or nodo.tag == "Type":
                continue
            if nodo.tag == "Object":
                tipo = self.tipo_oggetto(nodo, indice)
                if e_visual(tipo):
                    return nodo
                base = tipo_base(tipo)
                if generico is None and "+" not in base and base.startswith("Spotfire.Dxp.Application.Visuals.") and "Collection" not in base:
                    generico = nodo
            pila.extend(reversed(list(nodo)))
        return generico

    def visual_da_collezione(self, pagina, indice, visti):
        elementi = self.elementi_collezione(pagina, indice, "visuals")
        if elementi is None:
            return None
        risultati = []
        for elemento in elementi:
            oggetto = self.risolvi(elemento, indice)
            if oggetto is None or oggetto in visti:
                continue
            visti.add(oggetto)
            bersaglio = oggetto
            if not e_visual(self.tipo_oggetto(oggetto, indice)):
                interno = self.primo_visual_interno(oggetto, indice)
                if interno is not None:
                    bersaglio = interno
            tipo = ultimo_segmento(self.tipo_oggetto(bersaglio, indice)) or "Sconosciuto"
            nome = self.nome_diretto(bersaglio, indice) or self.nome_diretto(oggetto, indice)
            risultati.append((tipo, nome, bersaglio))
        return risultati

    def estrai_pagine_e_visual(self):
        documento = None
        file_ordinati = sorted(self.xml.items(), key=lambda x: 0 if x[0] == self.file_principale else 1)
        for nome_file, radice in file_ordinati:
            indice = self.indici[nome_file]
            if indice.get("copia"):
                continue
            for oggetto in radice.iter("Object"):
                if tipo_base(self.tipo_oggetto(oggetto, indice)) == "Spotfire.Dxp.Application.Document" and not self.in_istantanea(oggetto, indice):
                    documento = (oggetto, indice)
                    break
            if documento:
                break
        pagine = []
        if documento:
            oggetto, indice = documento
            for elemento in self.elementi_collezione(oggetto, indice, "pages") or []:
                pagina = self.risolvi(elemento, indice)
                if pagina is not None and ultimo_segmento(self.tipo_oggetto(pagina, indice)) == "Page" and pagina not in [p for p, _ in pagine]:
                    pagine.append((pagina, indice))
        if not pagine:
            for nome_file, radice in self.xml.items():
                indice = self.indici[nome_file]
                if indice.get("copia"):
                    continue
                for oggetto in radice.iter("Object"):
                    if tipo_base(self.tipo_oggetto(oggetto, indice)) == "Spotfire.Dxp.Application.Page" and not self.in_istantanea(oggetto, indice):
                        pagine.append((oggetto, indice))
        visti = set()
        for numero, (pagina, indice) in enumerate(pagine, 1):
            titolo = self.nome_diretto(pagina, indice) or f"Pagina {numero}"
            visual = self.visual_da_collezione(pagina, indice, visti)
            if visual is None:
                visual = self.visual_di_pagina(pagina, indice, visti, False)
            self.pagine.append({"titolo": titolo, "visual": [(u, n) for u, n, _ in visual]})
            for ultimo, nome, oggetto in visual:
                self.visual[ultimo] += 1
                if ultimo in TIPI_TEXT_AREA:
                    self.aggiungi_text_area(oggetto, indice, nome or f"Text area {len(self.text_area) + 1}", titolo)

    def aggiungi_text_area(self, oggetto, indice, titolo, pagina):
        valori = self.raccogli_valori(oggetto, indice)
        preferiti = [v for p, v in valori if "html" in p.lower() and v.strip()]
        generici = [v for p, v in valori if "<" in v and ">" in v and len(v) > 5]
        candidati = preferiti or generici
        html = max(candidati, key=len) if candidati else ""
        self.text_area.append({
            "titolo": titolo,
            "pagina": pagina,
            "html": html,
            "controlli": len(re.findall(r"<SpotfireControl\b", html, re.I)),
            "immagini": len(re.findall(r"<img\b", html, re.I)),
            "tag_script": len(re.findall(r"<script\b", html, re.I)),
            "librerie": re.findall(r"<script\b[^>]*\bsrc=[\"']([^\"']+)", html, re.I),
        })

    def scegli_codice(self, valori, anche_senza_segnali=False):
        migliore = ""
        punteggio_migliore = (-1, 0)
        for percorso, valore in valori:
            if not valore or not valore.strip():
                continue
            chiave = chiave_campo(percorso.split(".")[-1]) if percorso else ""
            if not (chiave in CHIAVI_CODICE or chiave.endswith("code")):
                continue
            segnali = max(punti_codice(valore))
            if segnali == 0 and not (anche_senza_segnali and "\n" in valore):
                continue
            punteggio = (segnali, len(valore))
            if punteggio > punteggio_migliore:
                migliore, punteggio_migliore = valore, punteggio
        return migliore

    def estrai_data_function(self):
        for oggetto, indice in self.oggetti_data_function:
            valori = self.raccogli_valori(oggetto, indice)
            codice = self.scegli_codice(valori, anche_senza_segnali=True)
            dichiarato = self.valore_campo(valori, {"language", "scriptlanguage", "languagename", "engine", "executor"}, modo="qualsiasi").lower()
            if "python" in dichiarato or re.search(r"^\s*(?:import|from|def)\s", codice, re.M):
                linguaggio = "Python"
            else:
                linguaggio = "R (TERR)"
            if codice:
                self.hash_data_function.add(impronta(codice))
            righe_codice = len([r for r in codice.splitlines() if r.strip()])
            self.data_function.append({
                "nome": self.nome_diretto(oggetto, indice) or f"Data function {len(self.data_function) + 1}",
                "linguaggio": linguaggio,
                "codice": codice,
                "righe": righe_codice,
                "ingressi": sorted({v for p, v in valori if re.search(r"input", p, re.I) and chiave_campo(p.split(".")[-1]) == "name"}),
                "uscite": sorted({v for p, v in valori if re.search(r"output", p, re.I) and chiave_campo(p.split(".")[-1]) == "name"}),
            })

    def nome_elemento(self, nodo, indice):
        if nodo.tag not in ("Field", "Attribute", "Property", "String"):
            for chiave in ("Name", "name", "DisplayName", "Title", "ScriptName"):
                valore = nodo.get(chiave)
                if valore and valore.strip() and len(valore) < 200:
                    return valore.strip()
        if nodo.tag == "Object":
            return self.nome_diretto(nodo, indice)
        for figlio in nodo:
            if not isinstance(figlio.tag, str):
                continue
            etichetta = figlio.tag.lower()
            if etichetta in ("name", "title", "displayname", "scriptname") and figlio.text and figlio.text.strip() and len(figlio.text) < 200:
                return figlio.text.strip()
            if figlio.tag == "Field" and chiave_campo(figlio.get("Name")) in ("name", "title", "displayname", "scriptname"):
                valore = self.valore_semplice(figlio, indice)
                if valore and len(valore) < 200:
                    return valore.strip()
            if figlio.tag in ("Attribute", "Property") and (figlio.get("Key") or figlio.get("Name") or "").lower() in ("name", "title", "displayname", "scriptname"):
                valore = figlio.get("Value") or figlio.text or ""
                if valore.strip() and len(valore) < 200:
                    return valore.strip()
        return ""

    def linguaggio_elemento(self, nodo, indice):
        for chiave, valore in nodo.attrib.items():
            if "language" in chiave.lower():
                return valore
        for figlio in nodo:
            if not isinstance(figlio.tag, str):
                continue
            if "language" in figlio.tag.lower() and figlio.text:
                return figlio.text
            etichetta = (figlio.get("Name") or figlio.get("Key") or "").lower() if figlio.tag in ("Field", "Attribute", "Property") else ""
            if "language" in etichetta:
                valore = figlio.get("Value") or self.valore_semplice(figlio, indice, 3)
                for p, v in self.raccogli_valori(figlio, indice)[:5]:
                    valore = valore or v
                return valore or ""
        return ""

    def contesto_vicino(self, elemento, indice, contatore):
        nodo = elemento
        livelli = 0
        nome = ""
        linguaggio = ""
        while nodo is not None and livelli < 7:
            if nodo is not elemento and contatore.get(nodo, 0) > 1:
                break
            nome = nome or self.nome_elemento(nodo, indice)
            linguaggio = linguaggio or self.linguaggio_elemento(nodo, indice)
            if nome and linguaggio:
                break
            nodo = indice["genitori"].get(nodo)
            livelli += 1
        return nome, linguaggio

    def estrai_script(self):
        file_script = set()
        for nome_file in self.xml:
            nome_risorsa = self.nome_risorsa_per_file.get(normalizza_percorso(nome_file), "")
            if "script" in nome_risorsa.lower() or "script" in Path(nome_file).name.lower():
                file_script.add(nome_file)

        trovati = []
        visti = set(self.hash_data_function)
        for nome_file, radice in self.xml.items():
            indice = self.indici[nome_file]
            if indice.get("copia"):
                continue
            dedicato = nome_file in file_script
            for elemento in radice.iter():
                for valore in (elemento.get("Value"), elemento.text):
                    if not valore or not valore.strip() or valore.lstrip().startswith("<"):
                        continue
                    if dedicato:
                        if len(valore.strip()) < 8 or max(punti_codice(valore)) < 1:
                            continue
                        linguaggio = indovina_linguaggio(valore) or indovina_linguaggio(valore, rigoroso=False)
                    else:
                        if len(valore.strip()) < 15:
                            continue
                        linguaggio = indovina_linguaggio(valore)
                    if not linguaggio:
                        continue
                    chiave = impronta(valore)
                    if chiave in visti:
                        continue
                    if self.in_istantanea(elemento, indice):
                        continue
                    visti.add(chiave)
                    trovati.append({"testo": valore, "linguaggio": linguaggio, "elemento": elemento, "indice": indice, "dedicato": dedicato, "origine": self.nome_risorsa_per_file.get(normalizza_percorso(nome_file)) or nome_file})
        for percorso, testo in self.testi.items():
            linguaggio = indovina_linguaggio(testo)
            chiave = impronta(testo)
            if not linguaggio or chiave in visti:
                continue
            normalizzato = normalizza_percorso(percorso)
            riferimenti = self.riferimenti_risorse.get(normalizzato, []) + self.riferimenti_risorse.get(normalizzato.split("/")[-1], [])
            if riferimenti and all(self.in_istantanea(e, i) for e, i in riferimenti):
                continue
            visti.add(chiave)
            trovati.append({"testo": testo, "linguaggio": linguaggio, "elemento": None, "indice": None, "dedicato": False, "origine": self.nome_risorsa_per_file.get(normalizzato) or percorso})
        trovati.sort(key=lambda t: 0 if t["dedicato"] else 1)

        contatori = {}
        for t in trovati:
            if t["elemento"] is None:
                continue
            contatore = contatori.setdefault(t["indice"]["file"], Counter())
            nodo = t["elemento"]
            while nodo is not None:
                contatore[nodo] += 1
                nodo = t["indice"]["genitori"].get(nodo)

        nomi_visti = set()
        for t in trovati:
            nome = ""
            dichiarato = ""
            contesto = ""
            if t["elemento"] is not None:
                nome, dichiarato = self.contesto_vicino(t["elemento"], t["indice"], contatori[t["indice"]["file"]])
                contesto = self.catena_tipi(t["elemento"], t["indice"])
            if nome and impronta(nome) == impronta(t["testo"]):
                nome = ""
            linguaggio = linguaggio_dichiarato(dichiarato) or t["linguaggio"]
            chiave_nome = (linguaggio, nome.lower())
            if nome and chiave_nome in nomi_visti:
                continue
            nomi_visti.add(chiave_nome)
            self.script.append({
                "nome": nome,
                "nome_nel_file": bool(nome),
                "linguaggio": linguaggio,
                "codice": t["testo"],
                "righe": len([r for r in t["testo"].splitlines() if r.strip()]),
                "origine": t["origine"],
            })

        progressivi = Counter()
        for s in self.script:
            progressivi[s["linguaggio"]] += 1
            if not s["nome"]:
                s["nome"] = f"Script {s['linguaggio']} {progressivi[s['linguaggio']]}"

    def classe_proprieta(self, oggetto, indice):
        nodo = indice["genitori"].get(oggetto)
        passi = 0
        while nodo is not None and passi < 30:
            if nodo.tag == "Field":
                nome = chiave_campo(nodo.get("Name"))
                if nome != "properties" and ("properties" in nome or re.search(r"document|column|table|hierarchy|filter|visual", nome)):
                    return nodo.get("Name")
            nodo = indice["genitori"].get(nodo)
            passi += 1
        return ""

    @staticmethod
    def visibile_in_properties(proprieta, con_attributi):
        if not proprieta["standard"]:
            return True
        if con_attributi and "isvisible" not in proprieta["attributi"].lower():
            return False
        if "." in proprieta["nome"]:
            return False
        return proprieta["nome"].lower() not in PROPRIETA_SCHEDA_GENERAL

    def estrai_proprieta(self):
        citate = {}
        for s in self.script:
            for nome in re.findall(r"Properties\s*\[\s*[\"']([^\"']+)[\"']\s*\]", s["codice"]):
                citate.setdefault(nome, set()).add(s["nome"])
            for nome in re.findall(r"Properties\.\w+\(\s*[\"']([^\"']+)[\"']", s["codice"]):
                citate.setdefault(nome, set()).add(s["nome"])
        for nome_file, radice in self.xml.items():
            indice = self.indici[nome_file]
            if indice.get("copia"):
                continue
            for elemento in radice.iter():
                valore = elemento.get("Value")
                if not valore or ("${" not in valore and "DocumentProperty" not in valore):
                    continue
                nomi = re.findall(r"\$\{([^}]+)\}", valore) + re.findall(r"DocumentProperty\(\s*\"([^\"]+)\"", valore)
                if nomi and not self.in_istantanea(elemento, indice):
                    for nome in nomi:
                        citate.setdefault(nome.strip(), set()).add("espressioni")
        self.proprieta_citate = citate

        viste = set()
        for oggetto, indice in self.oggetti_proprieta:
            valori = self.raccogli_valori(oggetto, indice)
            nome = self.nome_diretto(oggetto, indice)
            if not nome:
                continue
            classe = self.classe_proprieta(oggetto, indice)
            chiave = (classe.lower(), nome)
            if chiave in viste:
                continue
            viste.add(chiave)
            attributi = self.valore_campo(valori, {"attributes"})
            minuscola = classe.lower()
            if "document" in minuscola or "analysis" in minuscola:
                gruppo = "Documento"
            elif "column" in minuscola:
                gruppo = "Colonna"
            elif "table" in minuscola:
                gruppo = "Tabella"
            else:
                gruppo = classe or "Non determinata"
            self.proprieta.append({
                "nome": nome,
                "classe": classe,
                "gruppo": gruppo,
                "standard": "isstandard" in attributi.lower(),
                "attributi": attributi,
                "tipo_dato": self.valore_campo(valori, {"datatype", "valuetype", "typename"}, modo="qualsiasi", escludi=("description",)),
                "valore": self.valore_campo(valori, {"value", "defaultvalue", "currentvalue"}, escludi=("datatype", "description")),
                "descrizione": self.valore_campo(valori, {"description"}),
                "usata_in": ", ".join(sorted(citate.get(nome, []))),
            })

        documento = [p for p in self.proprieta if p["gruppo"] == "Documento"]
        if documento:
            con_attributi = any(p["attributi"] for p in documento)
            visibili = [p for p in documento if self.visibile_in_properties(p, con_attributi)]
            self.proprieta_documento = sorted(visibili, key=lambda p: (not p["standard"],))
            self.proprieta_documento_standard = [p for p in self.proprieta_documento if p["standard"]]
        else:
            non_standard = [p for p in self.proprieta if not p["standard"] and p["gruppo"] not in ("Colonna", "Tabella")]
            if non_standard:
                self.proprieta_documento = non_standard
            else:
                for nome, fonti in sorted(citate.items()):
                    self.proprieta_documento.append({"nome": nome, "classe": "", "gruppo": "", "standard": False, "attributi": "", "tipo_dato": "", "valore": "", "descrizione": "", "usata_in": ", ".join(sorted(fonti))})

    def estrai_tabelle_sorgente(self):
        chiavi_utili = re.compile(r"catalog|schema|table|view|owner|database|external|tabletype|elementid|librarypath|path|server|connection|sourcetype|customquery|query", re.I)
        viste = set()
        for nome_file, radice in self.xml.items():
            indice = self.indici[nome_file]
            if indice.get("copia"):
                continue
            for elemento in radice.iter():
                if not isinstance(elemento.tag, str) or not re.search(r"TableSchema$|^DataTableSource$|^SourceTable$", elemento.tag):
                    continue
                nome = elemento.get("DisplayName") or elemento.get("Name") or ""
                proprieta = OrderedDict()
                for k, v in elemento.attrib.items():
                    if k not in ("Name", "DisplayName") and chiavi_utili.search(k):
                        proprieta[k] = v
                pila = list(elemento)
                while pila:
                    figlio = pila.pop(0)
                    if not isinstance(figlio.tag, str) or "column" in figlio.tag.lower():
                        continue
                    chiave = figlio.get("Key") or (figlio.get("Name") if figlio.tag in ("Attribute", "Property", "Field") else None)
                    valore = figlio.get("Value") if figlio.get("Value") is not None else (figlio.text or "").strip()
                    if chiave and valore and chiavi_utili.search(chiave) and chiave not in proprieta:
                        proprieta[chiave] = valore
                    pila.extend(list(figlio))
                self.aggiungi_tabella(nome, proprieta, nome_file)
            for oggetto in radice.iter("Object"):
                tipo = self.tipo_oggetto(oggetto, indice)
                ultimo = ultimo_segmento(tipo)
                if not re.search(r"DataSource$|InformationLink|DatabaseTable|SourceTable", ultimo) or re.search(r"Collection|Settings|Manager", ultimo):
                    continue
                if self.in_istantanea(oggetto, indice):
                    continue
                proprieta = OrderedDict([("TipoSorgente", ultimo)])
                for percorso, valore in self.raccogli_valori(oggetto, indice)[:400]:
                    ultima = percorso.split(".")[-1] if percorso else ""
                    if ultima and valore and len(valore) < 2000 and chiavi_utili.search(ultima) and ultima not in proprieta:
                        proprieta[ultima] = valore
                if len(proprieta) > 1:
                    self.aggiungi_tabella(self.nome_diretto(oggetto, indice), proprieta, nome_file)

    def aggiungi_tabella(self, nome, proprieta, nome_file):
        chiave = nome.strip().lower() if nome else tuple(proprieta.items())
        if chiave in self.tabelle_viste or (not nome and not proprieta):
            return
        self.tabelle_viste.add(chiave)
        valori = {k.lower(): v for k, v in proprieta.items()}
        query = next((v for k, v in valori.items() if "customquery" in k or k in ("query", "sqlquery", "sql")), "")
        catalogo = next((v for k, v in valori.items() if "catalog" in k and "path" not in k), "")
        schema = next((v for k, v in valori.items() if "schema" in k and "path" not in k), "")
        oggetto_db = next((v for k, v in valori.items() if re.search(r"^(?:table|tablename|view|viewname|sourcetable|sourcetablename|externalname|externaltablename)$", k)), "")
        tipo_oggetto_db = next((v for k, v in valori.items() if "tabletype" in k or k == "type"), "")
        if query:
            natura = "Query personalizzata"
        elif oggetto_db or schema:
            natura = "Tabella o vista del database"
        elif any("librarypath" in k or "elementid" in k for k in valori) or "InformationLink" in proprieta.get("TipoSorgente", ""):
            natura = "Information Link"
        else:
            natura = "Non determinato"
        completo = ".".join(x for x in (catalogo, schema, oggetto_db or (nome if natura == "Tabella o vista del database" else "")) if x)
        self.tabelle_sorgente.append({
            "nome": nome,
            "natura": natura,
            "oggetto_database": completo,
            "tipo_oggetto_database": tipo_oggetto_db,
            "dettagli": "; ".join(f"{k}={re.sub(chr(10), ' ', v)[:150]}" for k, v in proprieta.items() if "query" not in k.lower()),
            "file": nome_file,
        })

    def estrai_query_e_connessioni(self):
        file_ordinati = sorted(self.xml.items(), key=lambda x: 0 if x[0].lower().endswith("dataaccessplan.xml") else 1)
        for nome_file, radice in file_ordinati:
            if self.indici[nome_file].get("copia"):
                continue
            pila = [(radice, "")]
            while pila:
                elemento, contesto = pila.pop()
                if not isinstance(elemento.tag, str):
                    continue
                tag = elemento.tag
                nome_elemento = elemento.get("DisplayName") or elemento.get("Name")
                if tag not in ("Field", "Attribute", "Property") and nome_elemento:
                    contesto = nome_elemento
                chiave = elemento.get("Key") or (elemento.get("Name") if tag in ("Field", "Property") else None)
                if chiave:
                    valore = elemento.get("Value")
                    if valore is None:
                        valori_figli = [f.get("Value") or (f.text or "") for f in elemento]
                        valore = max(valori_figli, key=len) if valori_figli else (elemento.text or "")
                    if valore:
                        self.valuta_coppia(chiave, valore, contesto, nome_file)
                for k, v in elemento.attrib.items():
                    if k not in ("Key", "Name", "Value", "DisplayName", "Id"):
                        self.valuta_coppia(k, v, contesto, nome_file)
                for figlio in elemento:
                    pila.append((figlio, contesto))

    def valuta_coppia(self, chiave, valore, contesto, nome_file):
        minuscola = chiave.lower()
        if re.search(r"pass|pwd|secret|token|credential", minuscola):
            return
        if re.search(r"query|sql|commandtext|statement", minuscola) and len(valore) > 15 and re.search(r"\b(?:select|with|exec|execute|call)\b", valore, re.I):
            chiave_hash = impronta(valore)
            chiave_nome = (contesto or "").strip().lower()
            if chiave_hash in self.hash_query or (chiave_nome and chiave_nome in self.nomi_query):
                return
            self.hash_query.add(chiave_hash)
            if chiave_nome:
                self.nomi_query.add(chiave_nome)
            self.query.append({"nome": contesto or f"query {len(self.query) + 1}", "sql": valore, "file": ""})
            return
        if re.search(r"server|host|database|catalog|schema|adaptertype|connectionstring|datasourcename|httppath|warehouse|driver|provider|librarypath|informationlink", minuscola) and 0 < len(valore) < 500:
            valore_sicuro = re.sub(r"(?i)(password|pwd)\s*=\s*[^;]*", r"\1=nascosta", valore)
            coppia = (contesto, chiave, valore_sicuro)
            if coppia not in self.connessioni_viste:
                self.connessioni_viste.add(coppia)
                self.connessioni.append({"contesto": contesto, "chiave": chiave, "valore": valore_sicuro})

    def estrai_colonne_calcolate(self):
        visti = set()
        for oggetto, indice in self.oggetti_colonne_calcolate:
            valori = self.raccogli_valori(oggetto, indice)
            nome = ""
            tabella = ""
            for antenato in self.antenati_oggetti(oggetto, indice):
                ultimo = ultimo_segmento(self.tipo_oggetto(antenato, indice))
                if not nome:
                    nome = self.nome_diretto(antenato, indice)
                if ultimo == "DataTable":
                    tabella = self.nome_diretto(antenato, indice)
                    break
            espressione = self.valore_campo(valori, {"expression", "expressiontext", "originalexpression"}, modo="qualsiasi")
            chiave = (tabella, nome, espressione)
            if chiave in visti:
                continue
            visti.add(chiave)
            self.colonne_calcolate.append({"tabella": tabella, "nome": nome, "espressione": espressione})

    def dati_documentazione(self):
        return {
            "pagine": [
                {
                    "numero": i,
                    "pagina": p["titolo"],
                    "oggetti_visivi": len(p["visual"]),
                    "text_area": sum(1 for u, _ in p["visual"] if u in TIPI_TEXT_AREA),
                    "grafici_e_tabelle": sum(1 for u, _ in p["visual"] if u not in TIPI_TEXT_AREA),
                }
                for i, p in enumerate(self.pagine, 1)
            ],
            "oggetti_visivi": [{"pagina": p["titolo"], "tipo": u, "titolo": n} for p in self.pagine for u, n in p["visual"]],
            "text_area": [{"pagina": t["pagina"], "titolo": t["titolo"], "controlli_spotfire": t["controlli"], "immagini": t["immagini"]} for t in self.text_area],
            "document_properties": [{"nome": p["nome"], "tipo": "standard" if p["standard"] else "utente", "valore": p["valore"], "usata_in": p["usata_in"]} for p in self.proprieta_documento],
            "script": [{"nome": s["nome"], "linguaggio": s["linguaggio"], "righe_di_codice": s["righe"], "codice": s["codice"]} for s in self.script],
            "data_function": [{"nome": d["nome"], "linguaggio": d["linguaggio"], "righe_di_codice": d["righe"], "ingressi": ", ".join(d["ingressi"]), "uscite": ", ".join(d["uscite"])} for d in self.data_function],
            "query_personalizzate": [{"nome": q["nome"]} for q in self.query],
            "tabelle_sorgente": [{"nome_tabella": t["nome"], "tipo_sorgente": t["natura"], "oggetto_database": t["oggetto_database"]} for t in self.tabelle_sorgente],
            "colonne_calcolate": [{"tabella": c["tabella"], "colonna": c["nome"], "espressione": c["espressione"]} for c in self.colonne_calcolate],
            "segnalibri": self.segnalibri,
            "immagini": len(self.immagini),
        }


NATIVO = "Nativo"
WORKAROUND = "Workaround"
NON_NATIVO = "Non nativo"
ORDINE_ESITI = {NATIVO: 0, WORKAROUND: 1, NON_NATIVO: 2}
PUNTI_ESITO = {NATIVO: 0, WORKAROUND: 1, NON_NATIVO: 3}

SOGLIE_COMPLESSITA = [(25, "Bassa"), (75, "Media"), (200, "Alta")]

REGOLE_IRONPYTHON = [
    ("Navigazione pagine", r"ActivePageReference|PageNavigation", NATIVO,
     "Lo script cambia la pagina attiva.",
     "Pulsante con azione Navigazione pagina.", ""),
    ("Document properties da codice", r"Document\.Properties|DocumentProperty", WORKAROUND,
     "Lo script legge o scrive variabili del documento.",
     "Parametri di campo o tabelle scollegate usate negli slicer. Il valore non si imposta da codice.",
     "Le liste di valori possono stare in una tabella di parametri."),
    ("Filtri da codice", r"FilterPanel|FilteringScheme|ListBoxFilter|CheckBoxFilter|RangeFilter|ItemFilter|RadioButtonFilter|TextFilter|HierarchyFilter|ResetAllFilters", WORKAROUND,
     "Lo script imposta o azzera i filtri.",
     "Slicer e segnalibri. Il reset si fa con un pulsante collegato a un segnalibro.",
     "I filtri fissi si applicano direttamente nelle viste."),
    ("Marking", r"Marking|DataMarkingSelection|SetSelection|IndexSet", WORKAROUND,
     "Lo script usa le righe selezionate in un grafico.",
     "Interazioni tra visual e drill through. La selezione non è leggibile come elenco di righe.", ""),
    ("Assi dinamici", r"XAxis|YAxis|ColorAxis|CategoryAxis|ValueAxis|MeasureAxis", WORKAROUND,
     "Lo script cambia colonne o misure sugli assi.",
     "Parametri di campo per scegliere cosa mostrare sugli assi.", ""),
    ("Proprietà dei visual da codice", r"\.Title\s*=|\.Visible\s*=|Visuals\.(?:Add|Remove)", WORKAROUND,
     "Lo script cambia titolo o visibilità dei grafici.",
     "Titolo dinamico da misura. Visibilità con segnalibri e riquadro Selezione.", ""),
    ("Text area da codice", r"HtmlContent", WORKAROUND,
     "Lo script riscrive il contenuto di una text area.",
     "Casella di testo o scheda con valori calcolati da misure.", ""),
    ("Regole colore", r"ColorRule|AddFixedColorRule|AddThresholdRule|Coloring", NATIVO,
     "Lo script imposta regole di colore.",
     "Formattazione condizionale.", ""),
    ("Segnalibri", r"Bookmark", NATIVO,
     "Lo script applica segnalibri.",
     "Segnalibri richiamati da pulsanti.", ""),
    ("Refresh dati", r"\.Refresh\(|ReloadAllData|ReloadData|RefreshAsync|InvalidateData", NON_NATIVO,
     "Lo script ricarica i dati quando l'utente lo chiede.",
     "Nel report non esiste un pulsante di refresh. Si usa il refresh pianificato oppure DirectQuery.",
     "Job che aggiornano le tabelle alla frequenza richiesta."),
    ("Modifica tabelle dati", r"AddRows|ReplaceData|RemoveRows|DataFlowBuilder|TextFileDataSource|SbdfLibraryDataSource|AddDataTable", NON_NATIVO,
     "Lo script aggiunge, sostituisce o carica tabelle durante l'uso.",
     "Non possibile: il modello dati del report è fisso.",
     "Spostare la logica in un notebook o in una pipeline che produce la tabella finale."),
    ("Colonne create da codice", r"AddCalculatedColumn|AddTransformation|AddBinnedColumn", WORKAROUND,
     "Lo script crea colonne calcolate o trasformazioni.",
     "Definire le colonne in anticipo in DAX o Power Query.",
     "Calcolare le colonne direttamente nelle tabelle."),
    ("Lettura dei dati riga per riga", r"DataValueCursor|CreateCursor|GetDistinctRowValues|GetRows", WORKAROUND,
     "Lo script scorre i dati riga per riga.",
     "Riscrivere la logica come misura DAX (SUMX, FILTER, CALCULATE).",
     "Per calcoli pesanti usare SQL o PySpark."),
    ("Lettura o scrittura file", r"System\.IO|StreamWriter|StreamReader|File\.(?:Write|Read|Open|Exists|Copy|Delete)", NON_NATIVO,
     "Lo script legge o scrive file.",
     "Non possibile dal report.",
     "Lettura e scrittura file su volumi Unity Catalog."),
    ("Export", r"Export\w*\(|PowerPoint|PdfExport", WORKAROUND,
     "Lo script esporta PDF, immagini o dati.",
     "Export dal menu del servizio o sottoscrizioni email. Non automatizzabile da un pulsante.",
     "Estrazioni periodiche generate da job."),
    ("Chiamate web o API", r"System\.Net|WebClient|HttpWebRequest|HttpClient|urllib", NON_NATIVO,
     "Lo script chiama un servizio esterno.",
     "Chiamate web solo durante il refresh (Web.Contents), mai su azione dell'utente.",
     "Ingestione dei dati tramite job."),
    ("Scrittura su database", r"SqlConnection|OdbcConnection|OleDbConnection|ExecuteNonQuery|INSERT\s+INTO|UPDATE\s+\w+\s+SET|DELETE\s+FROM", NON_NATIVO,
     "Lo script scrive dati su un database.",
     "Il report non scrive dati.",
     "Aggiornamento tabelle con MERGE da job. L'inserimento dati da parte dell'utente richiede un'app esterna."),
    ("Esecuzione data function", r"DataFunction", NON_NATIVO,
     "Lo script avvia una data function R o Python.",
     "Nessun equivalente affidabile.",
     "Riscrivere come notebook e salvare il risultato in una tabella."),
    ("Popup e notifiche", r"MessageBox|System\.Windows|NotificationService|ProgressService", NON_NATIVO,
     "Lo script mostra finestre o messaggi.",
     "Nessun popup. Pannello mostrato con un segnalibro oppure tooltip di pagina.", ""),
    ("Azioni in background o a tempo", r"\bThread\b|BeginInvoke|\bTimer\b|time\.sleep", NON_NATIVO,
     "Lo script esegue azioni in background o a intervalli.",
     "Non disponibile. L'aggiornamento automatico della pagina esiste solo con DirectQuery.", ""),
    ("Invio email", r"SmtpClient|MailMessage", NON_NATIVO,
     "Lo script invia email.",
     "Sottoscrizioni e avvisi, solo pianificati.",
     "Notifiche dei job."),
    ("Logica per utente", r"UserName|CurrentPrincipal|UserService", WORKAROUND,
     "Lo script cambia comportamento in base all'utente.",
     "USERPRINCIPALNAME e sicurezza a livello di riga (RLS).",
     "Tabella di mappatura tra utenti e perimetri."),
    ("Layout da codice", r"PageLayout|LayoutDefinition|BeginSideBySideSection|AutoConfigure", NON_NATIVO,
     "Lo script modifica la disposizione della pagina.",
     "Layout fisso. Si possono solo mostrare o nascondere gruppi di oggetti con i segnalibri.", ""),
    ("Librerie .NET", r"clr\.AddReference", NON_NATIVO,
     "Lo script carica librerie .NET.",
     "Nessun equivalente. Va capito l'effetto dello script per scegliere un'alternativa.", ""),
]

REGOLE_JAVASCRIPT = [
    ("Modifica HTML e stile", r"getElementById|querySelector|getElementsBy|\$\(|jQuery|innerHTML|\.css\(", NON_NATIVO,
     "Il codice modifica HTML e stile della pagina.",
     "Non possibile. L'aspetto si gestisce con tema JSON e formattazione dei visual.", ""),
    ("Mostra e nascondi elementi", r"\.hide\(|\.show\(|\.toggle\(", WORKAROUND,
     "Il codice mostra o nasconde elementi.",
     "Segnalibri con riquadro Selezione, richiamati da pulsanti.", ""),
    ("Eventi e click", r"\.click\(|\.trigger\(|addEventListener|\.on\(", WORKAROUND,
     "Il codice reagisce ai click o li simula.",
     "Pulsanti con azione nativa. Non si possono concatenare più azioni.", ""),
    ("Timer", r"setInterval|setTimeout", NON_NATIVO,
     "Il codice esegue azioni a intervalli.",
     "Non disponibile. Aggiornamento automatico della pagina solo con DirectQuery.",
     "Tabelle aggiornate da job frequenti."),
    ("Chiamate di rete dal browser", r"fetch\(|XMLHttpRequest|\$\.ajax|axios", NON_NATIVO,
     "Il codice scarica dati da servizi esterni.",
     "Non possibile dal report.",
     "Ingestione dei dati tramite job."),
    ("Librerie grafiche esterne", r"\bd3\.|Highcharts|echarts|plotly|google\.visualization", NON_NATIVO,
     "Il codice disegna grafici con librerie esterne.",
     "Usare il visual standard più simile.", ""),
    ("Memoria del browser", r"localStorage|sessionStorage|document\.cookie", NON_NATIVO,
     "Il codice salva impostazioni nel browser.",
     "Coperto in parte dai filtri persistenti del servizio.", ""),
    ("Tooltip e finestre", r"tooltip|popover|modal|alert\(", WORKAROUND,
     "Il codice mostra tooltip o finestre.",
     "Tooltip di pagina.", ""),
    ("Stili CSS", r"<style|addClass|removeClass|classList", WORKAROUND,
     "Il codice applica stili CSS.",
     "Tema JSON, con meno possibilità di personalizzazione.", ""),
    ("Campi di input", r"<input|\.val\(|keyup|keydown", WORKAROUND,
     "Il codice usa campi di input.",
     "Slicer con ricerca o parametri what if. Non esiste un campo di testo libero.", ""),
]

REGOLE_ESPRESSIONI = [
    ("Calcoli per gruppo (OVER)", r"\bOVER\b", WORKAROUND,
     "Espressione con calcolo per gruppo o cumulato.",
     "Misura DAX con CALCULATE o WINDOW.",
     "Precalcolo con window function SQL."),
    ("Confronto tra periodi", r"Intersect\(|Previous\(|AllPrevious\(|NavigatePeriod\(|ParallelPeriod\(", WORKAROUND,
     "Espressione che confronta periodi diversi.",
     "Funzioni di time intelligence con tabella calendario.", ""),
    ("Classifiche (Rank)", r"\b(?:Dense)?Rank\(", WORKAROUND,
     "Espressione che calcola una classifica.",
     "Funzione RANKX.",
     "Window function SQL."),
    ("Espressioni regolari", r"\bRX\w+\(", NON_NATIVO,
     "Espressione con espressioni regolari.",
     "Non disponibili in DAX.",
     "Calcolo in SQL o Power Query."),
    ("Uso di document properties", r"\$\{[^}]+\}|DocumentProperty\(", WORKAROUND,
     "Espressione che usa una document property.",
     "Parametro o slicer letto con SELECTEDVALUE.", ""),
    ("Condizioni (case)", r"\bcase\b", NATIVO,
     "Espressione con condizioni.",
     "Funzione SWITCH in DAX.", ""),
]

VISUAL = {
    "BarChart": ("Grafico a barre", NATIVO),
    "LineChart": ("Grafico a linee", NATIVO),
    "CombinationChart": ("Grafico a linee e colonne", NATIVO),
    "CrossTablePlot": ("Matrice", NATIVO),
    "TablePlot": ("Tabella", NATIVO),
    "SummaryTable": ("Matrice con misure statistiche in DAX", WORKAROUND),
    "ScatterPlot": ("Grafico a dispersione", NATIVO),
    "ScatterPlot3D": ("Nessun grafico 3D, usare un grafico a dispersione 2D", NON_NATIVO),
    "PieChart": ("Grafico a torta o ad anello", NATIVO),
    "Treemap": ("Mappa ad albero", NATIVO),
    "TreeMap": ("Mappa ad albero", NATIVO),
    "HeatMap": ("Matrice con colore di sfondo condizionale", WORKAROUND),
    "BoxPlot": ("Nessun box plot, approssimare con grafici standard", NON_NATIVO),
    "GraphicalTable": ("Tabella con sparkline e icone", WORKAROUND),
    "KpiChart": ("Scheda o KPI", NATIVO),
    "KPIChart": ("Scheda o KPI", NATIVO),
    "WaterfallChart": ("Grafico a cascata", NATIVO),
    "ParallelCoordinatePlot": ("Nessun equivalente", NON_NATIVO),
    "MapChart": ("Mappa o Azure Maps, con meno livelli", WORKAROUND),
    "HtmlTextArea": ("Casella di testo, pulsanti e slicer", WORKAROUND),
    "TextArea": ("Casella di testo, pulsanti e slicer", WORKAROUND),
}

SORGENTI = {
    "Query personalizzata": (NATIVO, "Query SQL nella connessione o vista sul database.", "Vista in Unity Catalog con la stessa query."),
    "Tabella o vista del database": (NATIVO, "Connessione diretta alla tabella o vista.", "Tabella o vista in Unity Catalog."),
    "Information Link": (WORKAROUND, "Recuperare dalla libreria Spotfire la query sottostante e ricrearla.", "Vista in Unity Catalog con la query recuperata."),
    "Non determinato": (WORKAROUND, "Da verificare aprendo la dashboard.", ""),
}

PESI = {
    "pagina": 0.5,
    "text_area": 0.5,
    "controllo_text_area": 0.3,
    "document_property": 0.2,
    "data_function": 5,
    "query": 1,
    "colonna_calcolata": 0.2,
    "script_base": 1,
    "script_righe_ogni": 50,
    "script_righe_max": 4,
}


def compila(regole):
    return [(n, re.compile(m, re.I if n in ("Scrittura su database", "Condizioni (case)") else 0), e, s, p, d) for n, m, e, s, p, d in regole]


REGOLE_IRONPYTHON = compila(REGOLE_IRONPYTHON)
REGOLE_JAVASCRIPT = compila(REGOLE_JAVASCRIPT)
REGOLE_ESPRESSIONI = compila(REGOLE_ESPRESSIONI)


def numero(valore):
    try:
        return float(str(valore).replace(",", "."))
    except (TypeError, ValueError):
        return 0


def intero(valore):
    return int(numero(valore))


def cella(valore, massimo=80):
    testo = re.sub(r"\s+", " ", str(valore if valore is not None else "")).strip().replace("|", "\\|")
    return testo if len(testo) <= massimo else testo[:massimo - 3] + "..."


def tabella_md(intestazione, righe, massimo=80):
    if not righe:
        return ["Nessun elemento.", ""]
    linee = ["| " + " | ".join(intestazione) + " |", "|" + "|".join("---" for _ in intestazione) + "|"]
    for riga in righe:
        linee.append("| " + " | ".join(cella(v, massimo) for v in riga) + " |")
    linee.append("")
    return linee


def arrotonda(valore):
    return int(valore) if float(valore).is_integer() else round(valore, 1)


def livello(punteggio):
    for soglia, nome in SOGLIE_COMPLESSITA:
        if punteggio <= soglia:
            return nome
    return "Molto alta"


def esito_peggiore(esiti):
    esiti = list(esiti)
    return max(esiti, key=lambda e: ORDINE_ESITI[e]) if esiti else ""


def ancora(*parti):
    testo = "-".join(str(p) for p in parti)
    testo = unicodedata.normalize("NFKD", testo).encode("ascii", "ignore").decode("ascii")
    return re.sub(r"[^a-z0-9]+", "-", testo.lower()).strip("-")


def titolo(livello_titolo, testo, identificativo):
    return [f'<a id="{identificativo}"></a>', "", f"{livello_titolo} {testo}", ""]


def blocco_apribile(etichetta, contenuto):
    return ["<details>", f"<summary>{etichetta}</summary>", ""] + contenuto + ["</details>", ""]


def elenco_nomi(nomi, massimo=6):
    nomi = [str(n) for n in nomi if str(n)]
    if len(nomi) <= massimo:
        return ", ".join(nomi)
    return ", ".join(nomi[:massimo]) + f" e altri {len(nomi) - massimo}"


def applica_regole(testo, regole):
    return [r for r in regole if r[1].search(testo or "")]


class Dashboard:

    def __init__(self, nome, percorso, dati):
        self.nome = nome
        self.percorso = Path(percorso)
        self.dati = dati
        self.script = []
        self.voci = OrderedDict()
        self.colonne = []
        self.proprieta = []
        self.visual = Counter()
        self.componenti = []
        self.punteggio = 0
        self.complessita = ""
        self.analizza()

    def registra(self, nome, esito, spotfire, power_bi, databricks, dove):
        voce = self.voci.setdefault(nome, {"esito": esito, "spotfire": spotfire, "power_bi": power_bi, "databricks": databricks, "dove": []})
        if dove and dove not in voce["dove"]:
            voce["dove"].append(dove)

    def registra_regola(self, regola, dove):
        nome, _, esito, spotfire, power_bi, databricks = regola
        self.registra(nome, esito, spotfire, power_bi, databricks, dove)

    def analizza(self):
        for riga in self.dati["script"]:
            linguaggio = str(riga.get("linguaggio", ""))
            codice = str(riga.get("codice", ""))
            regole = REGOLE_JAVASCRIPT if linguaggio == "JavaScript" else REGOLE_IRONPYTHON
            trovate = applica_regole(codice, regole)
            for regola in trovate:
                nome_script = str(riga.get("nome", ""))
                self.registra_regola(regola, nome_script if nome_script.lower().startswith("script") else f"script {nome_script}")
            righe = intero(riga.get("righe_di_codice")) or len([r for r in codice.splitlines() if r.strip()])
            punti = PESI["script_base"] + min(PESI["script_righe_max"], righe // PESI["script_righe_ogni"]) + sum(PUNTI_ESITO[r[2]] for r in trovate)
            self.script.append({
                "nome": riga.get("nome", ""),
                "linguaggio": linguaggio,
                "righe": righe,
                "funzionalita": [r[0] for r in trovate],
                "esito": esito_peggiore(r[2] for r in trovate) or NATIVO,
                "punti": punti,
            })

        for riga in self.dati["colonne_calcolate"]:
            trovate = applica_regole(str(riga.get("espressione", "")), REGOLE_ESPRESSIONI)
            for regola in trovate:
                self.registra_regola(regola, f"colonna {riga.get('colonna', '')}")
            self.colonne.append({"tabella": riga.get("tabella", ""), "colonna": riga.get("colonna", ""), "funzioni": [r[0] for r in trovate], "esito": esito_peggiore(r[2] for r in trovate) or NATIVO})

        for riga in self.dati["document_properties"]:
            trovate = applica_regole(str(riga.get("valore", "")), REGOLE_ESPRESSIONI)
            for regola in trovate:
                self.registra_regola(regola, f"proprietà {riga.get('nome', '')}")
            self.proprieta.append({"nome": riga.get("nome", ""), "tipo": riga.get("tipo", ""), "usata_in": riga.get("usata_in", ""), "funzioni": [r[0] for r in trovate]})

        for riga in self.dati["oggetti_visivi"]:
            self.visual[str(riga.get("tipo", ""))] += 1
        for tipo, n in self.visual.items():
            equivalente, esito = VISUAL.get(tipo, ("Da verificare", WORKAROUND))
            if esito != NATIVO and tipo not in ("HtmlTextArea", "TextArea"):
                self.registra(f"Visual {tipo}", esito, f"{n} visual di tipo {tipo}.", equivalente + ".", "", "")

        controlli = sum(intero(r.get("controlli_spotfire")) for r in self.dati["text_area"])
        if controlli:
            self.registra("Controlli nelle text area", WORKAROUND, f"{controlli} controlli nelle text area (pulsanti, menu, campi, etichette).", "Slicer, pulsanti con azioni e segnalibri. Il layout HTML va ricostruito.", "", "")

        for riga in self.dati["data_function"]:
            self.registra("Data function", NON_NATIVO, "Calcoli in R o Python eseguiti nel documento.", "Nessun equivalente affidabile.", "Riscrivere come notebook e salvare il risultato in una tabella.", str(riga.get("nome", "")))

        for riga in self.dati["tabelle_sorgente"]:
            natura = str(riga.get("tipo_sorgente", ""))
            esito, power_bi, databricks = SORGENTI.get(natura, SORGENTI["Non determinato"])
            if esito != NATIVO:
                self.registra(natura, esito, "Dati letti tramite la libreria Spotfire.", power_bi, databricks, str(riga.get("nome_tabella", "")))

        self.calcola_complessita()

    def conta_visual(self, esito):
        return sum(n for tipo, n in self.visual.items() if tipo not in ("HtmlTextArea", "TextArea") and VISUAL.get(tipo, ("", WORKAROUND))[1] == esito)

    def calcola_complessita(self):
        text_area = sum(n for t, n in self.visual.items() if t in ("HtmlTextArea", "TextArea"))
        controlli = sum(intero(r.get("controlli_spotfire")) for r in self.dati["text_area"])
        proprieta_utente = sum(1 for p in self.proprieta if p["tipo"] != "standard")
        colonne_adattate = sum(1 for c in self.colonne if c["esito"] in (WORKAROUND, NON_NATIVO))
        ironpython = [s for s in self.script if s["linguaggio"] != "JavaScript"]
        javascript = [s for s in self.script if s["linguaggio"] == "JavaScript"]
        voci = [
            ("Pagine", len(self.dati["pagine"]), len(self.dati["pagine"]) * PESI["pagina"]),
            ("Visual nativi", self.conta_visual(NATIVO), self.conta_visual(NATIVO) * PUNTI_ESITO[NATIVO]),
            ("Visual con workaround", self.conta_visual(WORKAROUND), self.conta_visual(WORKAROUND) * PUNTI_ESITO[WORKAROUND]),
            ("Visual non nativi", self.conta_visual(NON_NATIVO), self.conta_visual(NON_NATIVO) * PUNTI_ESITO[NON_NATIVO]),
            ("Text area", text_area, text_area * PESI["text_area"]),
            ("Controlli nelle text area", controlli, controlli * PESI["controllo_text_area"]),
            ("Document properties utente", proprieta_utente, proprieta_utente * PESI["document_property"]),
            ("Script IronPython", len(ironpython), sum(s["punti"] for s in ironpython)),
            ("Script JavaScript", len(javascript), sum(s["punti"] for s in javascript)),
            ("Data function", len(self.dati["data_function"]), len(self.dati["data_function"]) * PESI["data_function"]),
            ("Query personalizzate", len(self.dati["query_personalizzate"]), len(self.dati["query_personalizzate"]) * PESI["query"]),
            ("Colonne calcolate", len(self.colonne), len(self.colonne) * PESI["colonna_calcolata"] + colonne_adattate * PUNTI_ESITO[WORKAROUND]),
        ]
        self.componenti = [(nome, quantita, round(punti, 1)) for nome, quantita, punti in voci]
        self.punteggio = round(sum(p for _, _, p in self.componenti), 1)
        self.complessita = livello(self.punteggio)

    def schede(self, esito):
        linee = []
        for nome, voce in self.voci.items():
            if voce["esito"] != esito:
                continue
            linee.append(f"**{nome}**")
            linee.append("")
            linee.append(f"- Spotfire: {voce['spotfire']}")
            linee.append(f"- Power BI: {voce['power_bi']}")
            if voce["databricks"]:
                linee.append(f"- Databricks: {voce['databricks']}")
            if voce["dove"]:
                linee.append(f"- Dove: {elenco_nomi(voce['dove'])}")
            linee.append("")
        return linee or ["Nessuno.", ""]

    def conteggi(self):
        return {
            "pagine": len(self.dati["pagine"]),
            "visual": sum(self.visual.values()),
            "ironpython": sum(1 for s in self.script if s["linguaggio"] != "JavaScript"),
            "javascript": sum(1 for s in self.script if s["linguaggio"] == "JavaScript"),
            "proprieta": len(self.proprieta),
            "query": len(self.dati["query_personalizzate"]),
            "data_function": len(self.dati["data_function"]),
            "colonne": len(self.colonne),
            "non_native": sum(1 for v in self.voci.values() if v["esito"] == NON_NATIVO),
            "workaround": sum(1 for v in self.voci.values() if v["esito"] == WORKAROUND),
        }

    def markdown(self):
        c = self.conteggi()
        base = ancora(self.nome)
        md = titolo("##", self.nome, base)
        md.append(f"Complessità **{self.complessita}** ({arrotonda(self.punteggio)} punti)")
        md.append("")
        md.append(f"Pagine {c['pagine']} · Visual {c['visual']} · Script IronPython {c['ironpython']} · Script JavaScript {c['javascript']} · Document properties {c['proprieta']} · Query personalizzate {c['query']} · Data function {c['data_function']} · Colonne calcolate {c['colonne']}")
        md.append("")
        md.append(" · ".join([
            f"[Non migrabili ({c['non_native']})](#{base}-non-migrabili)",
            f"[Da adattare ({c['workaround']})](#{base}-da-adattare)",
            f"[Migrabili direttamente](#{base}-migrabili)",
            f"[Inventario](#{base}-inventario)",
            "[Menu](#menu)",
        ]))
        md.append("")

        md += titolo("###", "Non migrabili con Power BI nativo", f"{base}-non-migrabili")
        md += self.schede(NON_NATIVO)

        md += titolo("###", "Da adattare con un workaround", f"{base}-da-adattare")
        md += self.schede(WORKAROUND)

        md += titolo("###", "Migrabili direttamente", f"{base}-migrabili")
        diretti = []
        nativi = [(t, n) for t, n in self.visual.most_common() if VISUAL.get(t, ("", WORKAROUND))[1] == NATIVO]
        if nativi:
            diretti.append("- Visual: " + ", ".join(f"{VISUAL[t][0]} ({n})" for t, n in nativi))
        funzioni_native = [nome for nome, v in self.voci.items() if v["esito"] == NATIVO]
        if funzioni_native:
            diretti.append("- Funzionalità: " + ", ".join(funzioni_native))
        sorgenti_native = [r for r in self.dati["tabelle_sorgente"] if SORGENTI.get(str(r.get("tipo_sorgente", "")), SORGENTI["Non determinato"])[0] == NATIVO]
        if sorgenti_native:
            diretti.append("- Sorgenti dati: " + elenco_nomi([r.get("nome_tabella", "") for r in sorgenti_native]))
        md += (diretti + [""]) if diretti else ["Nessuno.", ""]

        md += titolo("###", "Inventario", f"{base}-inventario")
        md += blocco_apribile(f"Pagine ({c['pagine']})", tabella_md(
            ["Pagina", "Visual", "Text area", "Grafici e tabelle"],
            [[r.get("pagina"), r.get("oggetti_visivi"), r.get("text_area"), r.get("grafici_e_tabelle")] for r in self.dati["pagine"]]))
        md += blocco_apribile(f"Visual ({c['visual']})", tabella_md(
            ["Tipo Spotfire", "Numero", "In Power BI", "Esito"],
            [[t, n, VISUAL.get(t, ("Da verificare", WORKAROUND))[0], VISUAL.get(t, ("", WORKAROUND))[1]] for t, n in self.visual.most_common()]))
        md += blocco_apribile(f"Script ({len(self.script)})", tabella_md(
            ["Nome", "Linguaggio", "Righe", "Esito", "Funzionalità trovate"],
            [[s["nome"], s["linguaggio"], s["righe"], s["esito"], ", ".join(s["funzionalita"])] for s in self.script]))
        md += blocco_apribile(f"Document properties ({c['proprieta']})", tabella_md(
            ["Nome", "Tipo", "Usata in"],
            [[p["nome"], p["tipo"], p["usata_in"]] for p in self.proprieta]))
        md += blocco_apribile(f"Sorgenti dati ({len(self.dati['tabelle_sorgente'])})", tabella_md(
            ["Tabella", "Tipo", "Oggetto nel database"],
            [[r.get("nome_tabella"), r.get("tipo_sorgente"), r.get("oggetto_database")] for r in self.dati["tabelle_sorgente"]]))
        md += blocco_apribile(f"Colonne calcolate ({c['colonne']})", tabella_md(
            ["Tabella", "Colonna", "Esito", "Funzioni trovate"],
            [[x["tabella"], x["colonna"], x["esito"], ", ".join(x["funzioni"])] for x in self.colonne]))
        md += blocco_apribile(f"Text area ({len(self.dati['text_area'])})", tabella_md(
            ["Pagina", "Titolo", "Controlli", "Immagini"],
            [[r.get("pagina"), r.get("titolo"), r.get("controlli_spotfire"), r.get("immagini")] for r in self.dati["text_area"]]))
        md += blocco_apribile(f"Data function ({c['data_function']})", tabella_md(
            ["Nome", "Linguaggio", "Righe"],
            [[r.get("nome"), r.get("linguaggio"), r.get("righe_di_codice")] for r in self.dati["data_function"]]))
        md += blocco_apribile(f"Calcolo della complessità ({arrotonda(self.punteggio)} punti)", tabella_md(
            ["Componente", "Quantità", "Punti"],
            [[n, q, arrotonda(p)] for n, q, p in self.componenti] + [["Totale", "", arrotonda(self.punteggio)]]))
        md += ["[Torna al menu](#menu)", ""]
        return md


def come_leggere():
    soglie = ", ".join(f"{nome} fino a {soglia}" for soglia, nome in SOGLIE_COMPLESSITA) + f", Molto alta oltre {SOGLIE_COMPLESSITA[-1][0]}"
    return titolo("##", "Come leggere il documento", "come-leggere") + [
        "Per ogni dashboard gli elementi sono divisi in tre gruppi:",
        "",
        "- Non migrabili: Power BI non li supporta con gli strumenti nativi. Serve una soluzione diversa o spostare la logica su Databricks.",
        "- Da adattare: si ottiene un risultato simile in Power BI, con un approccio diverso da Spotfire.",
        "- Migrabili direttamente: esiste un equivalente diretto.",
        "",
        "Per ogni elemento critico sono indicati cosa fa in Spotfire, come si ottiene in Power BI, l'eventuale contributo di Databricks e dove si trova nella dashboard.",
        "",
        f"La complessità è una somma di punti: ogni elemento da adattare vale {PUNTI_ESITO[WORKAROUND]}, ogni elemento non migrabile {PUNTI_ESITO[NON_NATIVO]}, a cui si aggiungono pagine, script, query e colonne calcolate. Soglie: {soglie}. Il dettaglio è nell'inventario di ogni dashboard.",
        "",
        "[Torna al menu](#menu)",
        "",
    ]


def riepilogo_generale(dashboard):
    md = titolo("##", "Riepilogo generale", "riepilogo-generale")
    righe = []
    for d in sorted(dashboard, key=lambda x: -x.punteggio):
        c = d.conteggi()
        righe.append([f"[{d.nome}](#{ancora(d.nome)})", d.complessita, arrotonda(d.punteggio), c["non_native"], c["workaround"], c["pagine"], c["visual"], c["ironpython"] + c["javascript"], c["query"]])
    md += tabella_md(["Dashboard", "Complessità", "Punti", "Non migrabili", "Da adattare", "Pagine", "Visual", "Script", "Query"], righe)

    md += ["Elementi non migrabili presenti nelle dashboard:", ""]
    nomi = sorted({n for d in dashboard for n, v in d.voci.items() if v["esito"] == NON_NATIVO})
    righe = []
    for nome in nomi:
        presenti = [d.nome for d in dashboard if nome in d.voci]
        voce = next(d.voci[nome] for d in dashboard if nome in d.voci)
        righe.append([nome, voce["power_bi"], ", ".join(presenti)])
    md += tabella_md(["Elemento", "In Power BI", "Dashboard"], righe, 200)
    md += ["[Torna al menu](#menu)", ""]
    return md


def documento(dashboard):
    md = ["# Documentazione migrazione Spotfire", "", f"Ultimo aggiornamento: {datetime.now().strftime('%d/%m/%Y %H:%M:%S')}", ""]
    md += titolo("##", "Menu", "menu")
    md.append("- [Come leggere il documento](#come-leggere)")
    md.append("- [Riepilogo generale](#riepilogo-generale)")
    for d in dashboard:
        md.append(f"- [{d.nome}](#{ancora(d.nome)}): complessità {d.complessita.lower()}")
    md.append("")
    md += come_leggere()
    md += riepilogo_generale(dashboard)
    for d in dashboard:
        md += d.markdown()
    return "\n".join(md)


def main():
    percorsi = [Path(a) for a in sys.argv[1:]] or FILE_DXP
    elaborate = []
    for percorso in percorsi:
        if not percorso.exists():
            print(f"{percorso.name}: file non trovato")
            continue
        try:
            analizzatore = AnalizzatoreDxp(percorso)
            analizzatore.esegui()
        except zipfile.BadZipFile:
            print(f"{percorso.name}: archivio non leggibile")
            continue
        except PermissionError as e:
            print(f"{percorso.name}: accesso negato ({e})")
            continue
        d = Dashboard(percorso.stem, percorso, analizzatore.dati_documentazione())
        elaborate.append(d)
        print(f"{percorso.name}: complessità {d.complessita}, {arrotonda(d.punteggio)} punti")
    if elaborate:
        FILE_DOCUMENTAZIONE.parent.mkdir(parents=True, exist_ok=True)
        FILE_DOCUMENTAZIONE.write_text(documento(elaborate), encoding="utf-8")
        print(f"output in {FILE_DOCUMENTAZIONE}")


if __name__ == "__main__":
    main()
