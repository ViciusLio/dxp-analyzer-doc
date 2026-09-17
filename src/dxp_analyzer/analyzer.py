"""The Spotfire ``.dxp`` analysis engine.

A ``.dxp`` file is a ZIP archive of XML documents plus binary resources. This
module walks that structure and produces a fully structured
:class:`~dxp_analyzer.model.AnalysisResult`.

The extraction logic is a faithful port of the original working script; only the
identifiers were translated and the output was turned into typed dataclasses and
machine-readable keys (so the presentation layer can localize it).
"""

from __future__ import annotations

import re
import zipfile
import xml.etree.ElementTree as ET
from collections import Counter, OrderedDict
from pathlib import Path

from ._utils import (
    base_type,
    clean_name,
    code_scores,
    decode_bytes,
    declared_language,
    field_key,
    fingerprint,
    guess_language,
    last_segment,
    normalize_path,
)
from .model import (
    AnalysisResult,
    CalcColumn,
    Connection,
    DataFunctionInfo,
    Page,
    PropertyInfo,
    Query,
    ScriptInfo,
    SourceTable,
    TextArea,
    VisualRef,
    ZipEntry,
)
from .patterns import (
    BINARY_EXTENSIONS,
    CODE_KEYS,
    GENERAL_TAB_PROPERTIES,
    IMAGE_EXTENSIONS,
    MAX_TEXT_SIZE,
    NAME_KEYS,
    SNAPSHOT_TYPES,
    TEXT_AREA_TYPES,
    VISUAL_TYPES,
)

# Source-table nature machine keys (localized by the presentation layer).
NATURE_CUSTOM_QUERY = "custom_query"
NATURE_DATABASE_TABLE = "database_table"
NATURE_INFORMATION_LINK = "information_link"
NATURE_UNDETERMINED = "undetermined"


def is_visual(type_name: str) -> bool:
    base = base_type(type_name)
    return "+" not in base and base.startswith("Spotfire.Dxp.Application.Visuals") and last_segment(type_name) in VISUAL_TYPES


class DxpAnalyzer:
    """Parse a single ``.dxp`` file and expose the extracted content.

    Typical use::

        result = DxpAnalyzer("dashboard.dxp").analyze()
    """

    def __init__(self, path):
        self.path = Path(path)
        self.name = self.path.stem
        self.trees = OrderedDict()
        self.indexes = OrderedDict()
        self.texts = {}
        self.texts_norm = {}
        self.zip_entries = []
        self.images = []
        self.resources = []
        self.resource_by_id = {}
        self.resource_by_name = {}
        self.resource_refs = {}
        self._type_cache = {}
        self._snapshot_cache = {}
        self.live_types = Counter()
        self.snapshot_types = Counter()
        self._script_objects = []
        self._data_function_objects = []
        self._property_objects = []
        self._calc_column_objects = []
        self._data_table_objects = []
        self.data_tables = []
        self.bookmarks = 0
        self.pages = []
        self.visual_counts = Counter()
        self.text_areas = []
        self.scripts = []
        self.data_functions = []
        self._data_function_hashes = set()
        self.properties = []
        self.document_properties = []
        self.document_properties_standard = []
        self.cited_properties = {}
        self.calculated_columns = []
        self.queries = []
        self._query_names = set()
        self._query_hashes = set()
        self.connections = []
        self._seen_connections = set()
        self.document_copies = []
        self.main_file = None
        self.resource_name_by_file = {}
        self.source_tables = []
        self._seen_tables = set()
        self.warnings = []
        self.errors = []

    # -- public entry point -----------------------------------------------------

    def analyze(self) -> AnalysisResult:
        self._load_archive()
        self._build_index()
        self._census_objects()
        self._extract_pages_and_visuals()
        self._extract_data_functions()
        self._extract_scripts()
        self._extract_properties()
        self._extract_calculated_columns()
        self._extract_queries_and_connections()
        self._extract_source_tables()
        self._extract_data_tables()
        return self.result()

    def result(self) -> AnalysisResult:
        return AnalysisResult(
            name=self.name,
            path=str(self.path),
            pages=self.pages,
            visual_counts=dict(self.visual_counts),
            text_areas=self.text_areas,
            scripts=self.scripts,
            data_functions=self.data_functions,
            document_properties=self.document_properties,
            all_properties=self.properties,
            calculated_columns=self.calculated_columns,
            queries=self.queries,
            source_tables=self.source_tables,
            data_tables=self.data_tables,
            connections=self.connections,
            bookmarks=self.bookmarks,
            images=len(self.images),
            live_types=dict(self.live_types),
            snapshot_types=dict(self.snapshot_types),
            zip_entries=self.zip_entries,
            warnings=self.warnings,
            errors=self.errors,
        )

    # -- XML helpers ------------------------------------------------------------

    def _parse_xml(self, data):
        try:
            if isinstance(data, bytes):
                root = ET.fromstring(data)
            else:
                root = ET.fromstring(re.sub(r"^\s*<\?xml[^>]*\?>", "", data))
        except (ET.ParseError, ValueError):
            if isinstance(data, bytes):
                text = decode_bytes(data)
                if text:
                    return self._parse_xml(text)
            return None
        for element in root.iter():
            if isinstance(element.tag, str) and "}" in element.tag:
                element.tag = element.tag.rsplit("}", 1)[1]
            if any("}" in k for k in element.attrib):
                element.attrib = {k.rsplit("}", 1)[-1]: v for k, v in element.attrib.items()}
        return root

    def _load_archive(self):
        with zipfile.ZipFile(self.path, "r") as zf:
            for info in zf.infolist():
                if info.is_dir():
                    continue
                name = info.filename
                self.zip_entries.append(ZipEntry(name, info.file_size, info.compress_size))
                extension = Path(name).suffix.lower()
                if extension in IMAGE_EXTENSIONS:
                    self.images.append(name)
                if extension in BINARY_EXTENSIONS or info.file_size > MAX_TEXT_SIZE:
                    continue
                try:
                    raw = zf.read(info)
                except Exception as e:
                    self.errors.append(f"Lettura non riuscita di {name}: {e}")
                    continue
                if raw.startswith(b"\x89PNG") or raw.startswith(b"\xff\xd8\xff") or raw.startswith(b"GIF8"):
                    self.images.append(name)
                    continue
                if extension == ".xml" or raw.lstrip()[:5] == b"<?xml":
                    root = self._parse_xml(raw)
                    if root is not None:
                        self.trees[name] = root
                        continue
                text = decode_bytes(raw)
                if text is None:
                    continue
                if text.lstrip().startswith("<?xml"):
                    root = self._parse_xml(text)
                    if root is not None:
                        self.trees[name] = root
                        continue
                self.texts[name] = text
                normalized = normalize_path(name)
                self.texts_norm[normalized] = text
                self.texts_norm.setdefault(normalized.split("/")[-1], text)
                base = name.replace("\\", "/").split("/")[-1]
                if not base.isdigit():
                    self.resource_by_name.setdefault(base, name)

    def _build_index(self):
        for file_name, root in self.trees.items():
            index = {"file": file_name, "types": {}, "strings": {}, "objects": {}, "parents": {}}
            for parent in root.iter():
                for child in parent:
                    index["parents"][child] = parent
            for element in root.iter():
                tag = element.tag
                if not isinstance(tag, str):
                    continue
                ident = element.get("Id")
                if tag == "TypeObject" and ident is not None:
                    index["types"][ident] = element.get("FullTypeName", "")
                elif tag == "Object" and ident is not None:
                    index["objects"][ident] = element
                elif tag == "String" and ident is not None:
                    index["strings"][ident] = element.get("Value", element.text or "")
                path = element.get("ArchiveElementPath") or element.get("Path")
                if "resource" in tag.lower() and path:
                    resource_id = element.get("Id") or element.get("ResourceId") or ""
                    resource_name = element.get("Name", "")
                    self.resources.append({"id": resource_id, "name": resource_name, "path": path})
                    if resource_id:
                        self.resource_by_id[resource_id] = path
                    for key in (resource_name, path, path.replace("\\", "/").split("/")[-1]):
                        if key and not key.isdigit():
                            self.resource_by_name[key] = path
            self.indexes[file_name] = index
        documents = []
        for file_name, root in self.trees.items():
            index = self.indexes[file_name]
            index["copy"] = False
            for obj in root.iter("Object"):
                if base_type(self._object_type(obj, index)) == "Spotfire.Dxp.Application.Document":
                    documents.append(file_name)
                    break
        main = next((f for f in documents if f.lower().endswith("analysisdocument.xml")), documents[0] if documents else None)
        for file_name in documents:
            if file_name != main:
                self.indexes[file_name]["copy"] = True
                self.document_copies.append(file_name)
        self.main_file = main
        self.resource_name_by_file = {normalize_path(r["path"]): r["name"] for r in self.resources}
        for file_name, root in self.trees.items():
            index = self.indexes[file_name]
            for element in root.iter():
                if not isinstance(element.tag, str):
                    continue
                if "resource" in element.tag.lower() and (element.get("ArchiveElementPath") or element.get("Path")):
                    continue
                pairs = list(element.attrib.items())
                if element.text and len(element.text) < 300:
                    pairs.append(("", element.text.strip()))
                for key, value in pairs:
                    path = self._resource_from_value(value, key, element.tag)
                    if path:
                        self.resource_refs.setdefault(normalize_path(path), []).append((element, index))

    def _resource_from_value(self, value, key, tag):
        if not value:
            return None
        if value in self.resource_by_name:
            return self.resource_by_name[value]
        hint = f"{key}{tag}".lower()
        if value in self.resource_by_id and ("resource" in hint or "embedded" in hint or "blob" in hint):
            return self.resource_by_id[value]
        return None

    def _resource_text(self, path):
        if path in self.texts:
            return self.texts[path]
        normalized = normalize_path(path)
        return self.texts_norm.get(normalized) or self.texts_norm.get(normalized.split("/")[-1])

    def _object_type(self, obj, index):
        if obj in self._type_cache:
            return self._type_cache[obj]
        result = ""
        type_node = obj.find("Type")
        if type_node is None:
            result = obj.get("FullTypeName", "")
        else:
            for child in type_node:
                if child.tag == "TypeObject":
                    result = child.get("FullTypeName", "")
                    break
                if isinstance(child.tag, str) and child.tag.endswith("Ref"):
                    result = index["types"].get(child.get("Value") or child.get("Id"), "")
                    break
            if not result:
                for value in type_node.attrib.values():
                    if value in index["types"]:
                        result = index["types"][value]
                        break
        self._type_cache[obj] = result
        return result

    def _in_snapshot(self, element, index):
        if index.get("copy"):
            return True
        parents = index["parents"]
        node = parents.get(element)
        chain = []
        outcome = False
        while node is not None:
            if node in self._snapshot_cache:
                outcome = self._snapshot_cache[node]
                break
            chain.append(node)
            if node.tag == "Object" and SNAPSHOT_TYPES.search(last_segment(self._object_type(node, index))):
                outcome = True
                break
            node = parents.get(node)
        for n in chain:
            self._snapshot_cache[n] = outcome
        return outcome

    def _ancestor_objects(self, element, index, include_self=True):
        node = element if include_self else index["parents"].get(element)
        while node is not None:
            if node.tag == "Object":
                yield node
            node = index["parents"].get(node)

    def _type_chain(self, element, index, maximum=6):
        types = [last_segment(self._object_type(o, index)) for o in self._ancestor_objects(element, index)]
        return " dentro ".join(t for t in types[:maximum] if t)

    def _resolve(self, element, index):
        if element.tag == "Object":
            return element
        if isinstance(element.tag, str) and element.tag.endswith("Ref") and element.tag not in ("TypeRef", "StringRef"):
            return index["objects"].get(element.get("Value") or element.get("Id"))
        return None

    def _simple_value(self, field, index, depth=2):
        for child in field:
            if child.tag == "String":
                value = child.get("Value", child.text or "")
                if value.strip():
                    return value
            elif isinstance(child.tag, str) and child.tag.endswith("Ref"):
                value = index["strings"].get(child.get("Value") or child.get("Id"))
                if value:
                    return value
            elif child.tag == "Object" and depth > 0:
                fields = child.find("Fields")
                if fields is None:
                    continue
                for inner in fields:
                    if field_key(inner.get("Name")) in ("expression", "value", "text", "name", "title"):
                        value = self._simple_value(inner, index, depth - 1)
                        if value:
                            return value
        return ""

    def _direct_name(self, obj, index):
        fields = obj.find("Fields")
        if fields is None:
            return ""
        found = {}
        for field in fields:
            if field.tag != "Field":
                continue
            key = field_key(field.get("Name"))
            if key in NAME_KEYS and key not in found:
                value = self._simple_value(field, index)
                if value:
                    found[key] = value
        for key in NAME_KEYS:
            if key in found:
                return found[key].strip()
        return ""

    def _collect_values(self, element, index, path="", depth=0):
        results = []
        if depth > 150:
            return results
        for child in element:
            tag = child.tag
            if not isinstance(tag, str) or tag == "Type":
                continue
            if tag == "Field":
                name = child.get("Name", "")
                sub = f"{path}.{name}" if path else name
                results.extend(self._collect_values(child, index, sub, depth + 1))
                continue
            if tag.endswith("Ref"):
                ref = child.get("Value") or child.get("Id")
                if ref in index["strings"]:
                    results.append((path, index["strings"][ref]))
                continue
            value = child.get("Value")
            if value is None and len(child) == 0 and child.text and child.text.strip():
                value = child.text
            if value is not None:
                results.append((path, value))
            for key, v in child.attrib.items():
                resource_path = self._resource_from_value(v, key, tag)
                if resource_path:
                    content = self._resource_text(resource_path)
                    if content:
                        results.append((path, content))
            results.extend(self._collect_values(child, index, path, depth + 1))
        return results

    @staticmethod
    def _field_value(values, keys, mode="last", exclude=()):
        for path, value in values:
            lower = path.lower()
            if any(e in lower for e in exclude):
                continue
            parts = [field_key(p) for p in lower.split(".") if p]
            if not parts:
                continue
            matches = parts[-1] in keys if mode == "last" else any(p in keys for p in parts)
            if matches and value and value.strip():
                return value
        return ""

    def _census_objects(self):
        for file_name, root in self.trees.items():
            index = self.indexes[file_name]
            if index.get("copy"):
                continue
            for obj in root.iter("Object"):
                type_name = self._object_type(obj, index)
                if not type_name:
                    continue
                snapshot = self._in_snapshot(obj, index)
                if snapshot:
                    self.snapshot_types[type_name] += 1
                else:
                    self.live_types[type_name] += 1
                last = last_segment(type_name)
                if last == "Bookmark":
                    self.bookmarks += 1
                if snapshot or "+" in base_type(type_name):
                    continue
                if last.endswith("ScriptDefinition"):
                    self._script_objects.append((obj, index))
                elif last.endswith("DataFunctionDefinition"):
                    self._data_function_objects.append((obj, index))
                elif re.fullmatch(r"DataProperty(?:Impl)?", last):
                    self._property_objects.append((obj, index))
                elif last in ("CalculatedColumn", "CalculatedColumnImpl"):
                    self._calc_column_objects.append((obj, index))
                elif last == "DataTable":
                    self._data_table_objects.append((obj, index))

    def _extract_data_tables(self):
        """Collect the distinct data-model tables (DataTable) behind the canvas."""
        seen = set()
        for obj, index in self._data_table_objects:
            name = self._direct_name(obj, index)
            key = name.lower() if name else id(obj)
            if key in seen:
                continue
            seen.add(key)
            self.data_tables.append(name or f"Tabella {len(self.data_tables) + 1}")

    def _collection_items(self, obj, index, field_name):
        fields = obj.find("Fields")
        if fields is None:
            return None
        field = next((c for c in fields if c.tag == "Field" and field_key(c.get("Name")) == field_name), None)
        if field is None:
            return None
        container = field
        for child in field:
            resolved = self._resolve(child, index)
            if resolved is not None:
                container = resolved
                break
        items = None
        for inner in container.iter("Field"):
            if field_key(inner.get("Name")) == "items":
                items = inner.find(".//Elements")
                break
        if items is None:
            items = container.find(".//Elements")
        if items is None:
            return None
        return [c for c in items if self._resolve(c, index) is not None]

    def _visuals_of_page(self, page, index, seen, follow_refs):
        results = []
        stack = list(reversed(list(page)))
        while stack:
            node = stack.pop()
            if not isinstance(node.tag, str) or node.tag == "Type":
                continue
            target = self._resolve(node, index)
            if target is not None:
                if node.tag != "Object" and not follow_refs:
                    continue
                type_name = self._object_type(target, index)
                if is_visual(type_name):
                    if target not in seen:
                        seen.add(target)
                        results.append((last_segment(type_name), self._direct_name(target, index), target))
                    continue
                if node.tag != "Object":
                    continue
            stack.extend(reversed(list(node)))
        return results

    def _first_inner_visual(self, obj, index):
        stack = list(reversed(list(obj)))
        generic = None
        while stack:
            node = stack.pop()
            if not isinstance(node.tag, str) or node.tag == "Type":
                continue
            if node.tag == "Object":
                type_name = self._object_type(node, index)
                if is_visual(type_name):
                    return node
                base = base_type(type_name)
                if generic is None and "+" not in base and base.startswith("Spotfire.Dxp.Application.Visuals.") and "Collection" not in base:
                    generic = node
            stack.extend(reversed(list(node)))
        return generic

    def _visuals_from_collection(self, page, index, seen):
        items = self._collection_items(page, index, "visuals")
        if items is None:
            return None
        results = []
        for item in items:
            obj = self._resolve(item, index)
            if obj is None or obj in seen:
                continue
            seen.add(obj)
            target = obj
            if not is_visual(self._object_type(obj, index)):
                inner = self._first_inner_visual(obj, index)
                if inner is not None:
                    target = inner
            type_name = last_segment(self._object_type(target, index)) or "Sconosciuto"
            name = self._direct_name(target, index) or self._direct_name(obj, index)
            results.append((type_name, name, target))
        return results

    def _extract_pages_and_visuals(self):
        document = None
        ordered = sorted(self.trees.items(), key=lambda x: 0 if x[0] == self.main_file else 1)
        for file_name, root in ordered:
            index = self.indexes[file_name]
            if index.get("copy"):
                continue
            for obj in root.iter("Object"):
                if base_type(self._object_type(obj, index)) == "Spotfire.Dxp.Application.Document" and not self._in_snapshot(obj, index):
                    document = (obj, index)
                    break
            if document:
                break
        pages = []
        if document:
            obj, index = document
            for item in self._collection_items(obj, index, "pages") or []:
                page = self._resolve(item, index)
                if page is not None and last_segment(self._object_type(page, index)) == "Page" and page not in [p for p, _ in pages]:
                    pages.append((page, index))
        if not pages:
            for file_name, root in self.trees.items():
                index = self.indexes[file_name]
                if index.get("copy"):
                    continue
                for obj in root.iter("Object"):
                    if base_type(self._object_type(obj, index)) == "Spotfire.Dxp.Application.Page" and not self._in_snapshot(obj, index):
                        pages.append((obj, index))
        seen = set()
        for number, (page, index) in enumerate(pages, 1):
            title = self._direct_name(page, index) or f"Pagina {number}"
            visuals = self._visuals_from_collection(page, index, seen)
            if visuals is None:
                visuals = self._visuals_of_page(page, index, seen, False)
            self.pages.append(Page(title=title, visuals=[VisualRef(u, n) for u, n, _ in visuals]))
            for last, name, obj in visuals:
                self.visual_counts[last] += 1
                if last in TEXT_AREA_TYPES:
                    self._add_text_area(obj, index, name or f"Text area {len(self.text_areas) + 1}", title)

    def _add_text_area(self, obj, index, title, page):
        values = self._collect_values(obj, index)
        preferred = [v for p, v in values if "html" in p.lower() and v.strip()]
        generic = [v for p, v in values if "<" in v and ">" in v and len(v) > 5]
        candidates = preferred or generic
        html = max(candidates, key=len) if candidates else ""
        self.text_areas.append(TextArea(
            title=title,
            page=page,
            html=html,
            controls=len(re.findall(r"<SpotfireControl\b", html, re.I)),
            images=len(re.findall(r"<img\b", html, re.I)),
            script_tags=len(re.findall(r"<script\b", html, re.I)),
            libraries=re.findall(r"<script\b[^>]*\bsrc=[\"']([^\"']+)", html, re.I),
        ))

    def _pick_code(self, values, allow_without_signals=False):
        best = ""
        best_score = (-1, 0)
        for path, value in values:
            if not value or not value.strip():
                continue
            key = field_key(path.split(".")[-1]) if path else ""
            if not (key in CODE_KEYS or key.endswith("code")):
                continue
            signals = max(code_scores(value))
            if signals == 0 and not (allow_without_signals and "\n" in value):
                continue
            score = (signals, len(value))
            if score > best_score:
                best, best_score = value, score
        return best

    def _extract_data_functions(self):
        for obj, index in self._data_function_objects:
            values = self._collect_values(obj, index)
            code = self._pick_code(values, allow_without_signals=True)
            declared = self._field_value(values, {"language", "scriptlanguage", "languagename", "engine", "executor"}, mode="any").lower()
            if "python" in declared or re.search(r"^\s*(?:import|from|def)\s", code, re.M):
                language = "Python"
            else:
                language = "R (TERR)"
            if code:
                self._data_function_hashes.add(fingerprint(code))
            lines = len([r for r in code.splitlines() if r.strip()])
            self.data_functions.append(DataFunctionInfo(
                name=self._direct_name(obj, index) or f"Data function {len(self.data_functions) + 1}",
                language=language,
                code=code,
                lines=lines,
                inputs=sorted({v for p, v in values if re.search(r"input", p, re.I) and field_key(p.split(".")[-1]) == "name"}),
                outputs=sorted({v for p, v in values if re.search(r"output", p, re.I) and field_key(p.split(".")[-1]) == "name"}),
            ))

    def _element_name(self, node, index):
        if node.tag not in ("Field", "Attribute", "Property", "String"):
            for key in ("Name", "name", "DisplayName", "Title", "ScriptName"):
                value = node.get(key)
                if value and value.strip() and len(value) < 200:
                    return value.strip()
        if node.tag == "Object":
            return self._direct_name(node, index)
        for child in node:
            if not isinstance(child.tag, str):
                continue
            label = child.tag.lower()
            if label in ("name", "title", "displayname", "scriptname") and child.text and child.text.strip() and len(child.text) < 200:
                return child.text.strip()
            if child.tag == "Field" and field_key(child.get("Name")) in ("name", "title", "displayname", "scriptname"):
                value = self._simple_value(child, index)
                if value and len(value) < 200:
                    return value.strip()
            if child.tag in ("Attribute", "Property") and (child.get("Key") or child.get("Name") or "").lower() in ("name", "title", "displayname", "scriptname"):
                value = child.get("Value") or child.text or ""
                if value.strip() and len(value) < 200:
                    return value.strip()
        return ""

    def _element_language(self, node, index):
        for key, value in node.attrib.items():
            if "language" in key.lower():
                return value
        for child in node:
            if not isinstance(child.tag, str):
                continue
            if "language" in child.tag.lower() and child.text:
                return child.text
            label = (child.get("Name") or child.get("Key") or "").lower() if child.tag in ("Field", "Attribute", "Property") else ""
            if "language" in label:
                value = child.get("Value") or self._simple_value(child, index, 3)
                for p, v in self._collect_values(child, index)[:5]:
                    value = value or v
                return value or ""
        return ""

    def _nearby_context(self, element, index, counter):
        node = element
        levels = 0
        name = ""
        language = ""
        while node is not None and levels < 7:
            if node is not element and counter.get(node, 0) > 1:
                break
            name = name or self._element_name(node, index)
            language = language or self._element_language(node, index)
            if name and language:
                break
            node = index["parents"].get(node)
            levels += 1
        return name, language

    def _extract_scripts(self):
        script_files = set()
        for file_name in self.trees:
            resource_name = self.resource_name_by_file.get(normalize_path(file_name), "")
            if "script" in resource_name.lower() or "script" in Path(file_name).name.lower():
                script_files.add(file_name)

        found = []
        seen = set(self._data_function_hashes)
        for file_name, root in self.trees.items():
            index = self.indexes[file_name]
            if index.get("copy"):
                continue
            dedicated = file_name in script_files
            for element in root.iter():
                for value in (element.get("Value"), element.text):
                    if not value or not value.strip() or value.lstrip().startswith("<"):
                        continue
                    if dedicated:
                        if len(value.strip()) < 8 or max(code_scores(value)) < 1:
                            continue
                        language = guess_language(value) or guess_language(value, strict=False)
                    else:
                        if len(value.strip()) < 15:
                            continue
                        language = guess_language(value)
                    if not language:
                        continue
                    key = fingerprint(value)
                    if key in seen:
                        continue
                    if self._in_snapshot(element, index):
                        continue
                    seen.add(key)
                    found.append({"text": value, "language": language, "element": element, "index": index, "dedicated": dedicated, "origin": self.resource_name_by_file.get(normalize_path(file_name)) or file_name})
        for path, text in self.texts.items():
            language = guess_language(text)
            key = fingerprint(text)
            if not language or key in seen:
                continue
            normalized = normalize_path(path)
            refs = self.resource_refs.get(normalized, []) + self.resource_refs.get(normalized.split("/")[-1], [])
            if refs and all(self._in_snapshot(e, i) for e, i in refs):
                continue
            seen.add(key)
            found.append({"text": text, "language": language, "element": None, "index": None, "dedicated": False, "origin": self.resource_name_by_file.get(normalized) or path})
        found.sort(key=lambda t: 0 if t["dedicated"] else 1)

        counters = {}
        for t in found:
            if t["element"] is None:
                continue
            counter = counters.setdefault(t["index"]["file"], Counter())
            node = t["element"]
            while node is not None:
                counter[node] += 1
                node = t["index"]["parents"].get(node)

        seen_names = set()
        for t in found:
            name = ""
            declared = ""
            context = ""
            if t["element"] is not None:
                name, declared = self._nearby_context(t["element"], t["index"], counters[t["index"]["file"]])
                context = self._type_chain(t["element"], t["index"])
            if name and fingerprint(name) == fingerprint(t["text"]):
                name = ""
            language = declared_language(declared) or t["language"]
            name_key = (language, name.lower())
            if name and name_key in seen_names:
                continue
            seen_names.add(name_key)
            self.scripts.append(ScriptInfo(
                name=name,
                name_in_file=bool(name),
                language=language,
                code=t["text"],
                lines=len([r for r in t["text"].splitlines() if r.strip()]),
                origin=t["origin"],
            ))

        counts = Counter()
        for s in self.scripts:
            counts[s.language] += 1
            if not s.name:
                s.name = f"Script {s.language} {counts[s.language]}"

    def _property_class(self, obj, index):
        node = index["parents"].get(obj)
        steps = 0
        while node is not None and steps < 30:
            if node.tag == "Field":
                name = field_key(node.get("Name"))
                if name != "properties" and ("properties" in name or re.search(r"document|column|table|hierarchy|filter|visual", name)):
                    return node.get("Name")
            node = index["parents"].get(node)
            steps += 1
        return ""

    @staticmethod
    def _visible_in_properties(prop: PropertyInfo, with_attributes):
        if not prop.standard:
            return True
        if with_attributes and "isvisible" not in prop.attributes.lower():
            return False
        if "." in prop.name:
            return False
        return prop.name.lower() not in GENERAL_TAB_PROPERTIES

    def _extract_properties(self):
        cited = {}
        for s in self.scripts:
            for name in re.findall(r"Properties\s*\[\s*[\"']([^\"']+)[\"']\s*\]", s.code):
                cited.setdefault(name, set()).add(s.name)
            for name in re.findall(r"Properties\.\w+\(\s*[\"']([^\"']+)[\"']", s.code):
                cited.setdefault(name, set()).add(s.name)
        for file_name, root in self.trees.items():
            index = self.indexes[file_name]
            if index.get("copy"):
                continue
            for element in root.iter():
                value = element.get("Value")
                if not value or ("${" not in value and "DocumentProperty" not in value):
                    continue
                names = re.findall(r"\$\{([^}]+)\}", value) + re.findall(r"DocumentProperty\(\s*\"([^\"]+)\"", value)
                if names and not self._in_snapshot(element, index):
                    for name in names:
                        cited.setdefault(name.strip(), set()).add("espressioni")
        self.cited_properties = cited

        seen = set()
        for obj, index in self._property_objects:
            values = self._collect_values(obj, index)
            name = self._direct_name(obj, index)
            if not name:
                continue
            class_name = self._property_class(obj, index)
            key = (class_name.lower(), name)
            if key in seen:
                continue
            seen.add(key)
            attributes = self._field_value(values, {"attributes"})
            lower = class_name.lower()
            if "document" in lower or "analysis" in lower:
                group = "document"
            elif "column" in lower:
                group = "column"
            elif "table" in lower:
                group = "table"
            else:
                group = class_name or ""
            self.properties.append(PropertyInfo(
                name=name,
                class_name=class_name,
                group=group,
                standard="isstandard" in attributes.lower(),
                attributes=attributes,
                data_type=self._field_value(values, {"datatype", "valuetype", "typename"}, mode="any", exclude=("description",)),
                value=self._field_value(values, {"value", "defaultvalue", "currentvalue"}, exclude=("datatype", "description")),
                description=self._field_value(values, {"description"}),
                used_in=", ".join(sorted(cited.get(name, []))),
            ))

        document = [p for p in self.properties if p.group == "document"]
        if document:
            with_attributes = any(p.attributes for p in document)
            visible = [p for p in document if self._visible_in_properties(p, with_attributes)]
            self.document_properties = sorted(visible, key=lambda p: (not p.standard,))
            self.document_properties_standard = [p for p in self.document_properties if p.standard]
        else:
            non_standard = [p for p in self.properties if not p.standard and p.group not in ("column", "table")]
            if non_standard:
                self.document_properties = non_standard
            else:
                for name, sources in sorted(cited.items()):
                    self.document_properties.append(PropertyInfo(name=name, used_in=", ".join(sorted(sources))))

    def _extract_source_tables(self):
        useful_keys = re.compile(r"catalog|schema|table|view|owner|database|external|tabletype|elementid|librarypath|path|server|connection|sourcetype|customquery|query", re.I)
        for file_name, root in self.trees.items():
            index = self.indexes[file_name]
            if index.get("copy"):
                continue
            for element in root.iter():
                if not isinstance(element.tag, str) or not re.search(r"TableSchema$|^DataTableSource$|^SourceTable$", element.tag):
                    continue
                name = element.get("DisplayName") or element.get("Name") or ""
                props = OrderedDict()
                for k, v in element.attrib.items():
                    if k not in ("Name", "DisplayName") and useful_keys.search(k):
                        props[k] = v
                stack = list(element)
                while stack:
                    child = stack.pop(0)
                    if not isinstance(child.tag, str) or "column" in child.tag.lower():
                        continue
                    key = child.get("Key") or (child.get("Name") if child.tag in ("Attribute", "Property", "Field") else None)
                    value = child.get("Value") if child.get("Value") is not None else (child.text or "").strip()
                    if key and value and useful_keys.search(key) and key not in props:
                        props[key] = value
                    stack.extend(list(child))
                self._add_table(name, props, file_name)
            for obj in root.iter("Object"):
                type_name = self._object_type(obj, index)
                last = last_segment(type_name)
                if not re.search(r"DataSource$|InformationLink|DatabaseTable|SourceTable", last) or re.search(r"Collection|Settings|Manager", last):
                    continue
                if self._in_snapshot(obj, index):
                    continue
                props = OrderedDict([("TipoSorgente", last)])
                for path, value in self._collect_values(obj, index)[:400]:
                    leaf = path.split(".")[-1] if path else ""
                    if leaf and value and len(value) < 2000 and useful_keys.search(leaf) and leaf not in props:
                        props[leaf] = value
                if len(props) > 1:
                    self._add_table(self._direct_name(obj, index), props, file_name)

    def _add_table(self, name, props, file_name):
        key = name.strip().lower() if name else tuple(props.items())
        if key in self._seen_tables or (not name and not props):
            return
        self._seen_tables.add(key)
        values = {k.lower(): v for k, v in props.items()}
        query = next((v for k, v in values.items() if "customquery" in k or k in ("query", "sqlquery", "sql")), "")
        catalog = next((v for k, v in values.items() if "catalog" in k and "path" not in k), "")
        schema = next((v for k, v in values.items() if "schema" in k and "path" not in k), "")
        db_object = next((v for k, v in values.items() if re.search(r"^(?:table|tablename|view|viewname|sourcetable|sourcetablename|externalname|externaltablename)$", k)), "")
        db_object_type = next((v for k, v in values.items() if "tabletype" in k or k == "type"), "")
        if query:
            nature = NATURE_CUSTOM_QUERY
        elif db_object or schema:
            nature = NATURE_DATABASE_TABLE
        elif any("librarypath" in k or "elementid" in k for k in values) or "InformationLink" in props.get("TipoSorgente", ""):
            nature = NATURE_INFORMATION_LINK
        else:
            nature = NATURE_UNDETERMINED
        full = ".".join(x for x in (catalog, schema, db_object or (name if nature == NATURE_DATABASE_TABLE else "")) if x)
        self.source_tables.append(SourceTable(
            name=name,
            nature=nature,
            database_object=full,
            database_object_type=db_object_type,
            details="; ".join(f"{k}={re.sub(chr(10), ' ', v)[:150]}" for k, v in props.items() if "query" not in k.lower()),
            file=file_name,
        ))

    def _extract_queries_and_connections(self):
        ordered = sorted(self.trees.items(), key=lambda x: 0 if x[0].lower().endswith("dataaccessplan.xml") else 1)
        for file_name, root in ordered:
            if self.indexes[file_name].get("copy"):
                continue
            stack = [(root, "")]
            while stack:
                element, context = stack.pop()
                if not isinstance(element.tag, str):
                    continue
                tag = element.tag
                element_name = element.get("DisplayName") or element.get("Name")
                if tag not in ("Field", "Attribute", "Property") and element_name:
                    context = element_name
                key = element.get("Key") or (element.get("Name") if tag in ("Field", "Property") else None)
                if key:
                    value = element.get("Value")
                    if value is None:
                        child_values = [f.get("Value") or (f.text or "") for f in element]
                        value = max(child_values, key=len) if child_values else (element.text or "")
                    if value:
                        self._evaluate_pair(key, value, context, file_name)
                for k, v in element.attrib.items():
                    if k not in ("Key", "Name", "Value", "DisplayName", "Id"):
                        self._evaluate_pair(k, v, context, file_name)
                for child in element:
                    stack.append((child, context))

    def _evaluate_pair(self, key, value, context, file_name):
        lower = key.lower()
        if re.search(r"pass|pwd|secret|token|credential", lower):
            return
        if re.search(r"query|sql|commandtext|statement", lower) and len(value) > 15 and re.search(r"\b(?:select|with|exec|execute|call)\b", value, re.I):
            hash_key = fingerprint(value)
            name_key = (context or "").strip().lower()
            if hash_key in self._query_hashes or (name_key and name_key in self._query_names):
                return
            self._query_hashes.add(hash_key)
            if name_key:
                self._query_names.add(name_key)
            self.queries.append(Query(name=context or f"query {len(self.queries) + 1}", sql=value))
            return
        if re.search(r"server|host|database|catalog|schema|adaptertype|connectionstring|datasourcename|httppath|warehouse|driver|provider|librarypath|informationlink", lower) and 0 < len(value) < 500:
            safe = re.sub(r"(?i)(password|pwd)\s*=\s*[^;]*", r"\1=nascosta", value)
            triple = (context, key, safe)
            if triple not in self._seen_connections:
                self._seen_connections.add(triple)
                self.connections.append(Connection(context=context, key=key, value=safe))

    def _extract_calculated_columns(self):
        seen = set()
        for obj, index in self._calc_column_objects:
            values = self._collect_values(obj, index)
            name = ""
            table = ""
            for ancestor in self._ancestor_objects(obj, index):
                last = last_segment(self._object_type(ancestor, index))
                if not name:
                    name = self._direct_name(ancestor, index)
                if last == "DataTable":
                    table = self._direct_name(ancestor, index)
                    break
            expression = self._field_value(values, {"expression", "expressiontext", "originalexpression"}, mode="any")
            key = (table, name, expression)
            if key in seen:
                continue
            seen.add(key)
            self.calculated_columns.append(CalcColumn(table=table, name=name, expression=expression))

    def extract_archive(self, destination):
        """Extract the whole archive to ``destination`` (sanitized paths)."""
        destination = Path(destination)
        with zipfile.ZipFile(self.path, "r") as zf:
            for info in zf.infolist():
                if info.is_dir():
                    continue
                parts = [clean_name(p, 120) for p in re.split(r"[\\/]", info.filename) if p and p not in (".", "..")]
                if not parts:
                    continue
                target = destination.joinpath(*parts)
                try:
                    target.parent.mkdir(parents=True, exist_ok=True)
                    with zf.open(info) as source, open(target, "wb") as out:
                        out.write(source.read())
                except OSError as e:
                    self.errors.append(f"{info.filename}: {e}")
