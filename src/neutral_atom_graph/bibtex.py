from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator


@dataclass(frozen=True)
class BibEntry:
    entry_type: str
    key: str
    fields: dict[str, str]
    raw: str


_DOI_PREFIX = re.compile(
    r"^(?:https?://(?:dx\.)?doi\.org/|doi:\s*)", re.IGNORECASE
)
_DOI_IN_TEXT = re.compile(r"10\.\d{4,9}/[-._;()/:A-Z0-9]+", re.IGNORECASE)
_ARXIV_ID = re.compile(
    r"(?<!\d)(\d{4}\.\d{4,5}(?:v\d+)?|[a-z][a-z.\-]+/\d{7}(?:v\d+)?)",
    re.IGNORECASE,
)
_LATEX_COMMAND = re.compile(r"\\(?:text[a-zA-Z]+|emph|mathrm|mathbf|mathit)\s*")
_LATEX_ACCENT = re.compile(r"\\[\"'`^~=.uvHckbdtr]\s*\{?([A-Za-z])\}?")
_CITE_COMMAND = re.compile(
    r"\\(?:cite[a-zA-Z]*|nocite)\*?"
    r"(?:\s*\[[^\]]*\]){0,2}\s*\{([^}]+)\}",
    re.MULTILINE,
)


class BibTeXError(ValueError):
    pass


def _skip_space(text: str, pos: int) -> int:
    while pos < len(text) and (text[pos].isspace() or text[pos] == ","):
        pos += 1
    return pos


def _read_braced(text: str, pos: int) -> tuple[str, int]:
    if text[pos] != "{":
        raise BibTeXError("expected braced value")
    depth = 1
    start = pos + 1
    pos += 1
    while pos < len(text):
        char = text[pos]
        if char == "\\":
            pos += 2
            continue
        if char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return text[start:pos], pos + 1
        pos += 1
    raise BibTeXError("unterminated braced value")


def _read_quoted(text: str, pos: int) -> tuple[str, int]:
    if text[pos] != '"':
        raise BibTeXError("expected quoted value")
    start = pos + 1
    pos += 1
    brace_depth = 0
    while pos < len(text):
        char = text[pos]
        if char == "\\":
            pos += 2
            continue
        if char == "{":
            brace_depth += 1
        elif char == "}" and brace_depth:
            brace_depth -= 1
        elif char == '"' and brace_depth == 0:
            return text[start:pos], pos + 1
        pos += 1
    raise BibTeXError("unterminated quoted value")


def _read_value(text: str, pos: int) -> tuple[str, int]:
    pieces: list[str] = []
    while True:
        pos = _skip_space(text, pos)
        if pos >= len(text):
            break
        if text[pos] == "{":
            value, pos = _read_braced(text, pos)
        elif text[pos] == '"':
            value, pos = _read_quoted(text, pos)
        else:
            start = pos
            while pos < len(text) and text[pos] not in ",#":
                pos += 1
            value = text[start:pos].strip()
        pieces.append(value)
        pos = _skip_space(text, pos)
        if pos >= len(text) or text[pos] != "#":
            break
        pos += 1
    return "".join(pieces).strip(), pos


def _parse_fields(body: str) -> tuple[str, dict[str, str]]:
    comma = body.find(",")
    if comma < 0:
        return body.strip(), {}
    key = body[:comma].strip()
    fields: dict[str, str] = {}
    pos = comma + 1
    while pos < len(body):
        pos = _skip_space(body, pos)
        if pos >= len(body):
            break
        name_start = pos
        while pos < len(body) and (
            body[pos].isalnum() or body[pos] in "_:-"
        ):
            pos += 1
        name = body[name_start:pos].strip().lower()
        if not name:
            pos += 1
            continue
        while pos < len(body) and body[pos].isspace():
            pos += 1
        if pos >= len(body) or body[pos] != "=":
            while pos < len(body) and body[pos] != ",":
                pos += 1
            continue
        value, pos = _read_value(body, pos + 1)
        fields[name] = value
    return key, fields


def parse_bibtex(text: str) -> list[BibEntry]:
    entries: list[BibEntry] = []
    pos = 0
    while True:
        at = text.find("@", pos)
        if at < 0:
            break
        match = re.match(r"@([A-Za-z]+)\s*([\{\(])", text[at:])
        if not match:
            pos = at + 1
            continue
        entry_type = match.group(1).lower()
        opening = match.group(2)
        closing = "}" if opening == "{" else ")"
        body_start = at + match.end()
        depth = 1
        cursor = body_start
        in_quote = False
        while cursor < len(text):
            char = text[cursor]
            if char == "\\":
                cursor += 2
                continue
            if opening == "{":
                if char == opening:
                    depth += 1
                elif char == closing:
                    depth -= 1
                    if depth == 0:
                        break
            elif char == '"':
                in_quote = not in_quote
            elif not in_quote:
                if char == opening:
                    depth += 1
                elif char == closing:
                    depth -= 1
                    if depth == 0:
                        break
            cursor += 1
        if depth:
            raise BibTeXError(f"unterminated @{entry_type} entry at offset {at}")
        raw = text[at : cursor + 1]
        pos = cursor + 1
        if entry_type in {"comment", "preamble", "string"}:
            continue
        key, fields = _parse_fields(text[body_start:cursor])
        if not key:
            raise BibTeXError(f"missing key in @{entry_type} entry at offset {at}")
        entries.append(BibEntry(entry_type, key, fields, raw))
    return entries


def load_bibtex(path: str | Path) -> list[BibEntry]:
    return parse_bibtex(Path(path).read_text(encoding="utf-8"))


def normalize_doi(value: str | None) -> str | None:
    if not value:
        return None
    value = _DOI_PREFIX.sub("", value.strip())
    match = _DOI_IN_TEXT.search(value)
    if not match:
        return None
    return match.group(0).rstrip(".,;:)}]").lower()


def extract_doi(entry: BibEntry) -> str | None:
    direct = normalize_doi(entry.fields.get("doi"))
    if direct:
        return direct
    for field in ("url", "note"):
        match = _DOI_IN_TEXT.search(entry.fields.get(field, ""))
        if match:
            return normalize_doi(match.group(0))
    return None


def normalize_arxiv_id(value: str | None) -> str | None:
    if not value:
        return None
    match = _ARXIV_ID.search(value)
    if not match:
        return None
    return re.sub(r"v\d+$", "", match.group(1), flags=re.IGNORECASE).lower()


def extract_arxiv_id(entry: BibEntry) -> str | None:
    eprint = entry.fields.get("eprint")
    archive = entry.fields.get("archiveprefix", "")
    if eprint and (archive.lower() == "arxiv" or _ARXIV_ID.search(eprint)):
        arxiv_id = normalize_arxiv_id(eprint)
        if arxiv_id:
            return arxiv_id
    for field in ("url", "journal", "number", "note"):
        arxiv_id = normalize_arxiv_id(entry.fields.get(field))
        if arxiv_id:
            return arxiv_id
    return None


def clean_latex_text(value: str | None) -> str | None:
    if value is None:
        return None
    value = _LATEX_ACCENT.sub(r"\1", value)
    value = value.replace("\\&", "&").replace("\\_", "_")
    value = _LATEX_COMMAND.sub("", value)
    value = re.sub(r"\\[A-Za-z]+", " ", value)
    value = value.replace("{", "").replace("}", "")
    value = re.sub(r"\s+", " ", value).strip()
    return value or None


def normalize_title(value: str | None) -> str:
    cleaned = clean_latex_text(value) or ""
    cleaned = unicodedata.normalize("NFKD", cleaned)
    cleaned = "".join(ch for ch in cleaned if not unicodedata.combining(ch))
    cleaned = cleaned.casefold()
    cleaned = re.sub(r"[^a-z0-9]+", " ", cleaned)
    return " ".join(cleaned.split())


def parse_year(value: str | None) -> int | None:
    if not value:
        return None
    match = re.search(r"\b(18|19|20|21)\d{2}\b", value)
    return int(match.group(0)) if match else None


def iter_author_names(value: str | None) -> Iterator[str]:
    if not value:
        return
    for name in re.split(r"\s+and\s+", value, flags=re.IGNORECASE):
        cleaned = clean_latex_text(name)
        if cleaned:
            yield cleaned


def scan_tex_citations(tex_dir: str | Path) -> dict[str, list[str]]:
    result: dict[str, set[str]] = {}
    for path in sorted(Path(tex_dir).glob("*.tex")):
        text = path.read_text(encoding="utf-8", errors="replace")
        for match in _CITE_COMMAND.finditer(text):
            for key in match.group(1).split(","):
                key = key.strip()
                if key and key != "*":
                    result.setdefault(key, set()).add(path.name)
    return {key: sorted(files) for key, files in result.items()}
