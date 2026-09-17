"""Pure helper functions shared across the package (no Spotfire state)."""

from __future__ import annotations

import gzip
import hashlib
import re
import zlib

from .patterns import JS_SIGNALS, PYTHON_SIGNALS


def fingerprint(text: str | None) -> str:
    """Whitespace-insensitive MD5, used to deduplicate code/queries."""
    return hashlib.md5(re.sub(r"\s+", "", text or "").encode("utf-8", "ignore")).hexdigest()


def clean_name(text, length: int = 80) -> str:
    """Make a string safe to use as a file name."""
    cleaned = re.sub(r"[<>:\"/\\|?*\x00-\x1f]", "_", str(text or "")).strip().strip(".")
    cleaned = re.sub(r"\s+", " ", cleaned)
    return cleaned[:length].strip() or "senza nome"


def base_type(type_name: str | None) -> str:
    return (type_name or "").split(",")[0].strip()


def last_segment(type_name: str | None) -> str:
    base = base_type(type_name).split("`")[0]
    return re.split(r"[.+]", base)[-1] if base else ""


def field_key(name: str | None) -> str:
    return re.sub(r"^(?:m_|_)+", "", (name or "").lower())


def normalize_path(path: str | None) -> str:
    return (path or "").replace("\\", "/").lstrip("/").lower()


def is_readable_text(text: str) -> bool:
    sample = text[:4000]
    if not sample:
        return False
    good = sum(1 for c in sample if (ord(c) < 0x250 and (c.isprintable() or c in "\r\n\t")))
    return good / len(sample) > 0.9


def decode_bytes(raw: bytes) -> str | None:
    """Best-effort decode of an archive entry to readable text (handles gzip/zlib/BOM)."""
    data = raw
    if data[:2] == b"\x1f\x8b":
        try:
            data = gzip.decompress(data)
        except Exception:
            pass
    elif data[:1] == b"\x78":
        try:
            data = zlib.decompress(data)
        except Exception:
            pass
    if data[:3] == b"\xef\xbb\xbf":
        encodings = ["utf-8-sig"]
    elif data[:2] in (b"\xff\xfe", b"\xfe\xff"):
        encodings = ["utf-16"]
    else:
        encodings = ["utf-8", "utf-16", "cp1252"]
    for encoding in encodings:
        try:
            text = data.decode(encoding)
        except (UnicodeDecodeError, LookupError):
            continue
        if is_readable_text(text):
            return text
    return None


def code_scores(text: str | None) -> tuple[int, int]:
    """(python_signal_count, javascript_signal_count) for a code snippet."""
    sample = (text or "")[:200000]
    return (
        sum(1 for r in PYTHON_SIGNALS if r.search(sample)),
        sum(1 for r in JS_SIGNALS if r.search(sample)),
    )


def guess_language(text: str | None, strict: bool = True) -> str | None:
    if not text or not text.strip():
        return None
    py, js = code_scores(text)
    if not strict:
        return "JavaScript" if js > py else "IronPython"
    if py >= 3 and py > js:
        return "IronPython"
    if js >= 3 and js > py and ("{" in text or ";" in text):
        return "JavaScript"
    return None


def declared_language(declared: str | None) -> str | None:
    value = (declared or "").strip().lower()
    if "javascript" in value or value in {"js", "jscript"}:
        return "JavaScript"
    if "ironpython" in value:
        return "IronPython"
    if "python" in value:
        return "Python"
    return None
