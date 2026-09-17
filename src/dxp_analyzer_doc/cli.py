"""Command-line interface for dxp-analyzer-doc.

Examples::

    dxp-analyzer-doc analyze dashboard.dxp -o out --lang it
    dxp-analyzer-doc document a.dxp b.dxp -o migration.md
    dxp-analyzer-doc all *.dxp -o out
"""

from __future__ import annotations

import argparse
import sys
import zipfile
from pathlib import Path
from typing import List

from . import __version__
from .analyzer import DxpAnalyzer
from .export import Workbook, export_result, write_summary
from .i18n import LANGUAGES, normalize_lang
from .migration import ComplexityModel, DashboardAssessment, build_report


def _iter_dxp(paths: List[str]):
    """Expand paths (files, globs, directories) into existing ``.dxp`` files."""
    for raw in paths:
        p = Path(raw)
        if p.is_dir():
            yield from sorted(p.glob("*.dxp"))
        elif any(ch in raw for ch in "*?["):
            yield from sorted(Path().glob(raw))
        else:
            yield p


def _base_dir(files: List[str]) -> Path:
    """Directory the output defaults to: where the input .dxp files live."""
    first = files[0]
    p = Path(first)
    if p.is_dir():
        base = p
    elif any(ch in first for ch in "*?["):
        base = p.parent
    else:
        base = p.parent
    return base if str(base) not in ("", ".") else Path.cwd()


def _resolve_out_dir(output, base: Path) -> Path:
    """Output directory. Relative paths (and the default) resolve under `base`."""
    if not output:
        return base / "dxp-output"
    p = Path(output)
    return p if p.is_absolute() else base / p


def _resolve_doc(output, base: Path) -> Path:
    """Output .md file. Relative paths (and the default) resolve under `base`."""
    if not output:
        return base / "migration_documentation.md"
    p = Path(output)
    if not p.is_absolute():
        p = base / p
    if p.suffix.lower() != ".md":
        p = p / "migration_documentation.md"
    return p


def _analyze_one(path: Path):
    analyzer = DxpAnalyzer(path)
    result = analyzer.analyze()
    return analyzer, result


def _cmd_analyze(args) -> int:
    lang = normalize_lang(args.lang)
    out = _resolve_out_dir(args.output, _base_dir(args.files))
    out.mkdir(parents=True, exist_ok=True)
    if Workbook is None:
        print("openpyxl not installed: exporting CSV. For .xlsx run: pip install openpyxl")
    results = []
    for path in _iter_dxp(args.files):
        print(path.name)
        if not path.exists():
            print("  file not found")
            continue
        try:
            analyzer, result = _analyze_one(path)
        except zipfile.BadZipFile:
            print("  unreadable archive")
            continue
        except PermissionError as e:
            print(f"  access denied: {e}")
            continue
        folder = out / _safe(path.stem)
        export_result(result, folder, lang)
        if args.extract_archive:
            analyzer.extract_archive(folder / "extracted_archive")
        results.append(result)
        print(f"  pages {len(result.pages)}, visuals {result.total_visuals}, "
              f"scripts {len(result.scripts)}, queries {len(result.queries)}")
        if result.errors:
            print(f"  errors: {len(result.errors)} (see errors.log)")
    if results:
        write_summary(results, out, lang)
    print(f"output in {out}")
    return 0


def _cmd_document(args) -> int:
    lang = normalize_lang(args.lang)
    model = ComplexityModel(effort_model=getattr(args, "effort_model", "itemized"))
    assessments = []
    for path in _iter_dxp(args.files):
        if not path.exists():
            print(f"{path.name}: file not found")
            continue
        try:
            _, result = _analyze_one(path)
        except zipfile.BadZipFile:
            print(f"{path.name}: unreadable archive")
            continue
        except PermissionError as e:
            print(f"{path.name}: access denied ({e})")
            continue
        a = DashboardAssessment(result, model=model)
        assessments.append(a)
        print(f"{path.name}: complexity {a.score.level} ({a.score.index}/100), "
              f"effort ~{a.effort.likely_days} person-days")
    if not assessments:
        print("no dashboard processed")
        return 1
    out = _resolve_doc(args.output, _base_dir(args.files))
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(build_report(assessments, lang, model=model), encoding="utf-8")
    print(f"output in {out}")
    return 0


def _cmd_all(args) -> int:
    rc = _cmd_analyze(args)
    out_dir = _resolve_out_dir(args.output, _base_dir(args.files))
    doc_args = argparse.Namespace(files=args.files, output=str(out_dir / "migration_documentation.md"),
                                  lang=args.lang, effort_model=getattr(args, "effort_model", "itemized"))
    rc = _cmd_document(doc_args) or rc
    return rc


def _safe(name: str) -> str:
    import re
    return re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", name).strip().strip(".") or "senza nome"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="dxp-analyzer-doc", description="Analyze Spotfire .dxp dashboards and assess Power BI migration.")
    parser.add_argument("--version", action="version", version=f"dxp-analyzer-doc {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    common_lang = dict(choices=list(LANGUAGES), default="en", help="output language (default: en)")

    p_an = sub.add_parser("analyze", help="extract inventory tables and code files")
    p_an.add_argument("files", nargs="+", help=".dxp files, globs or directories")
    p_an.add_argument("-o", "--output", default=None, help="output directory (default: <input folder>/dxp-output; relative paths resolve under the input folder)")
    p_an.add_argument("--lang", **common_lang)
    p_an.add_argument("--extract-archive", action="store_true", help="also extract the full .dxp archive")
    p_an.set_defaults(func=_cmd_analyze)

    p_doc = sub.add_parser("document", help="generate the Power BI migration document")
    p_doc.add_argument("files", nargs="+", help=".dxp files, globs or directories")
    p_doc.add_argument("-o", "--output", default=None, help="output .md file or directory (default: <input folder>/migration_documentation.md)")
    p_doc.add_argument("--lang", **common_lang)
    p_doc.add_argument("--effort-model", choices=["itemized", "parametric"], default="itemized",
                       help="effort estimate model (default: itemized)")
    p_doc.set_defaults(func=_cmd_document)

    p_all = sub.add_parser("all", help="run analyze + document")
    p_all.add_argument("files", nargs="+", help=".dxp files, globs or directories")
    p_all.add_argument("-o", "--output", default=None, help="output directory (default: <input folder>/dxp-output)")
    p_all.add_argument("--lang", **common_lang)
    p_all.add_argument("--extract-archive", action="store_true", help="also extract the full .dxp archive")
    p_all.add_argument("--effort-model", choices=["itemized", "parametric"], default="itemized",
                       help="effort estimate model (default: itemized)")
    p_all.set_defaults(func=_cmd_all)

    return parser


def main(argv=None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
