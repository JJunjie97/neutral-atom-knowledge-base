from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Iterable

from .bibtex import clean_latex_text
from .db import LiteratureDB, utc_now


_CITE_COMMAND = re.compile(
    r"\\(?:cite[a-zA-Z]*|nocite)\*?"
    r"(?:\s*\[[^\]]*\]){0,2}\s*\{([^}]+)\}",
    re.MULTILINE,
)
_HEADING_COMMAND = re.compile(
    r"\\(section|subsection|subsubsection|paragraph)\*?\s*\{([^{}]*)\}",
    re.MULTILINE,
)
_INPUT_COMMAND = re.compile(r"\\(?:input|include)\s*\{([^{}]+)\}")
_TOKEN_COMMAND = re.compile(
    r"\\(?:section|subsection|subsubsection|paragraph)\*?\s*\{([^{}]*)\}"
    r"|\\(?:cite[a-zA-Z]*|nocite)\*?"
    r"(?:\s*\[[^\]]*\]){0,2}\s*\{([^}]+)\}"
    r"|\\(?:input|include)\s*\{([^{}]+)\}",
    re.MULTILINE,
)
_COMMENT = re.compile(r"(?<!\\)%[^\n]*")
_LATEX_COMMAND_WITH_ARGUMENT = re.compile(
    r"\\(?:textit|textbf|emph|mathrm|mathbf|mathit|texttt|url|href)"
    r"\s*\{([^{}]*)\}"
)
_LATEX_COMMAND = re.compile(r"\\[a-zA-Z@]+(?:\*|\[[^\]]*\])?")
_WHITESPACE = re.compile(r"\s+")

_LEVELS = {
    "section": 0,
    "subsection": 1,
    "subsubsection": 2,
    "paragraph": 3,
}

ALLOWED_RULE_FIELDS = {
    "title",
    "abstract",
    "topics",
    "venue",
    "work_type",
    "review_context",
    "review_section",
}


class TaxonomyError(ValueError):
    """Raised when a taxonomy definition is invalid."""


@dataclass(frozen=True)
class TaxonomyRule:
    rule_id: str
    dimension_id: str
    category_id: str
    fields: tuple[str, ...]
    keywords: tuple[str, ...]
    regex: tuple[str, ...]
    sections: tuple[str, ...]
    venues: tuple[str, ...]
    match: str
    confidence: float


@dataclass(frozen=True)
class Taxonomy:
    version: str
    digest: str
    dimensions: tuple[dict[str, Any], ...]
    rules: tuple[TaxonomyRule, ...]
    field_weights: dict[str, float]

    @property
    def labels(self) -> dict[tuple[str, str], dict[str, str | None]]:
        labels: dict[tuple[str, str], dict[str, str | None]] = {}
        for dimension in self.dimensions:
            for category in dimension["categories"]:
                labels[(dimension["id"], category["id"])] = {
                    "dimension_label_en": dimension.get("label_en"),
                    "dimension_label_zh": dimension.get("label_zh"),
                    "category_label_en": category.get("label_en"),
                    "category_label_zh": category.get("label_zh"),
                }
        return labels


def _string_list(value: Any, *, field: str, rule_id: str) -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, str):
        value = [value]
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise TaxonomyError(f"{rule_id}.{field} must be a string or string list")
    return tuple(item.strip() for item in value if item.strip())


def load_taxonomy(path: str | Path) -> Taxonomy:
    """Load and validate a deterministic, JSON taxonomy definition.

    Rules may live directly on categories or in a top-level ``rules`` array.
    Category-local rules inherit their dimension/category identifiers.
    """

    taxonomy_path = Path(path)
    raw_bytes = taxonomy_path.read_bytes()
    try:
        payload = json.loads(raw_bytes.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise TaxonomyError(f"invalid taxonomy JSON: {taxonomy_path}") from exc
    if not isinstance(payload, dict):
        raise TaxonomyError("taxonomy root must be an object")
    version = str(payload.get("version") or "").strip()
    if not version:
        raise TaxonomyError("taxonomy.version is required")
    dimensions = payload.get("dimensions")
    if not isinstance(dimensions, list) or not dimensions:
        raise TaxonomyError("taxonomy.dimensions must be a non-empty list")

    default_field_weights = {
        "manual": 1.0,
        "review_context": 0.94,
        "review_section": 0.88,
        "title": 0.84,
        "abstract": 0.78,
        "topics": 0.58,
        "venue": 0.70,
        "work_type": 0.60,
    }
    configured_weights = payload.get("field_weights") or {}
    if not isinstance(configured_weights, dict):
        raise TaxonomyError("taxonomy.field_weights must be an object")
    field_weights = dict(default_field_weights)
    for field, weight in configured_weights.items():
        if field not in ALLOWED_RULE_FIELDS | {"manual"}:
            raise TaxonomyError(f"unsupported field weight: {field}")
        numeric_weight = float(weight)
        if not 0.0 <= numeric_weight <= 1.0:
            raise TaxonomyError(f"field weight for {field} must be between 0 and 1")
        field_weights[field] = numeric_weight

    normalized_dimensions: list[dict[str, Any]] = []
    category_ids: set[tuple[str, str]] = set()
    dimension_ids: set[str] = set()
    rule_payloads: list[tuple[dict[str, Any], str, str]] = []
    for dimension in dimensions:
        if not isinstance(dimension, dict):
            raise TaxonomyError("each dimension must be an object")
        dimension_id = str(dimension.get("id") or "").strip()
        if not dimension_id or dimension_id in dimension_ids:
            raise TaxonomyError(f"invalid or duplicate dimension id: {dimension_id!r}")
        dimension_ids.add(dimension_id)
        categories = dimension.get("categories")
        if not isinstance(categories, list) or not categories:
            raise TaxonomyError(f"{dimension_id}.categories must be non-empty")
        normalized_categories: list[dict[str, Any]] = []
        for category in categories:
            if not isinstance(category, dict):
                raise TaxonomyError(f"{dimension_id} category must be an object")
            category_id = str(category.get("id") or "").strip()
            key = (dimension_id, category_id)
            if not category_id or key in category_ids:
                raise TaxonomyError(f"invalid or duplicate category: {key}")
            category_ids.add(key)
            normalized_categories.append(
                {
                    "id": category_id,
                    "label_en": category.get("label_en"),
                    "label_zh": category.get("label_zh"),
                    "description_en": category.get("description_en"),
                    "description_zh": category.get("description_zh"),
                    "description": category.get("description"),
                }
            )
            for rule in category.get("rules") or []:
                if not isinstance(rule, dict):
                    raise TaxonomyError(f"{key} rule must be an object")
                rule_payloads.append((rule, dimension_id, category_id))
        normalized_dimensions.append(
            {
                "id": dimension_id,
                "label_en": dimension.get("label_en"),
                "label_zh": dimension.get("label_zh"),
                "description_en": dimension.get("description_en"),
                "description_zh": dimension.get("description_zh"),
                "description": dimension.get("description"),
                "multi": bool(dimension.get("multi", True)),
                "categories": normalized_categories,
            }
        )

    for rule in payload.get("rules") or []:
        if not isinstance(rule, dict):
            raise TaxonomyError("top-level rules must be objects")
        rule_payloads.append(
            (
                rule,
                str(rule.get("dimension") or rule.get("dimension_id") or "").strip(),
                str(rule.get("category") or rule.get("category_id") or "").strip(),
            )
        )

    seen_rule_ids: set[str] = set()
    rules: list[TaxonomyRule] = []
    for index, (rule, dimension_id, category_id) in enumerate(rule_payloads):
        if (dimension_id, category_id) not in category_ids:
            raise TaxonomyError(
                f"rule targets unknown category: {(dimension_id, category_id)}"
            )
        rule_id = str(rule.get("id") or f"{dimension_id}.{category_id}.{index}").strip()
        if not rule_id or rule_id in seen_rule_ids:
            raise TaxonomyError(f"invalid or duplicate rule id: {rule_id!r}")
        seen_rule_ids.add(rule_id)
        fields = _string_list(
            rule.get("fields") or ["title", "abstract", "review_context"],
            field="fields",
            rule_id=rule_id,
        )
        unknown_fields = set(fields) - ALLOWED_RULE_FIELDS
        if unknown_fields:
            raise TaxonomyError(
                f"{rule_id}.fields contains unsupported fields: "
                f"{sorted(unknown_fields)}"
            )
        keywords = _string_list(rule.get("keywords"), field="keywords", rule_id=rule_id)
        patterns = _string_list(
            rule.get("regex") or rule.get("patterns"),
            field="regex",
            rule_id=rule_id,
        )
        sections = _string_list(rule.get("sections"), field="sections", rule_id=rule_id)
        venues = _string_list(rule.get("venues"), field="venues", rule_id=rule_id)
        if not any((keywords, patterns, sections, venues)):
            raise TaxonomyError(f"{rule_id} has no matching criteria")
        for pattern in patterns:
            try:
                re.compile(pattern, re.IGNORECASE)
            except re.error as exc:
                raise TaxonomyError(f"{rule_id} has invalid regex: {pattern}") from exc
        match = str(rule.get("match") or "any").lower()
        if match not in {"any", "all"}:
            raise TaxonomyError(f"{rule_id}.match must be 'any' or 'all'")
        confidence = float(rule.get("confidence", 0.75))
        if not 0.0 <= confidence <= 1.0:
            raise TaxonomyError(f"{rule_id}.confidence must be between 0 and 1")
        rules.append(
            TaxonomyRule(
                rule_id=rule_id,
                dimension_id=dimension_id,
                category_id=category_id,
                fields=fields,
                keywords=keywords,
                regex=patterns,
                sections=sections,
                venues=venues,
                match=match,
                confidence=confidence,
            )
        )

    digest = hashlib.sha256(raw_bytes).hexdigest()
    return Taxonomy(
        version=version,
        digest=digest,
        dimensions=tuple(normalized_dimensions),
        rules=tuple(rules),
        field_weights=field_weights,
    )


def _strip_comments(text: str) -> str:
    return _COMMENT.sub("", text)


def _plain_tex(text: str) -> str:
    previous = None
    while text != previous:
        previous = text
        text = _LATEX_COMMAND_WITH_ARGUMENT.sub(r"\1", text)
    text = _CITE_COMMAND.sub(" ", text)
    text = _LATEX_COMMAND.sub(" ", text)
    text = text.replace("{", " ").replace("}", " ")
    text = text.replace("~", " ").replace("&", " ")
    return _WHITESPACE.sub(" ", text).strip()


def _citation_context(text: str, start: int, end: int, *, limit: int = 700) -> str:
    line_start = text.rfind("\n", 0, start) + 1
    line_end = text.find("\n", end)
    if line_end < 0:
        line_end = len(text)
    line = text[line_start:line_end]
    if "&" in line or "\\\\" in line:
        return _plain_tex(line)

    paragraph_start = text.rfind("\n\n", 0, start)
    paragraph_start = 0 if paragraph_start < 0 else paragraph_start + 2
    paragraph_end = text.find("\n\n", end)
    paragraph_end = len(text) if paragraph_end < 0 else paragraph_end
    left = max(paragraph_start, start - limit // 2)
    right = min(paragraph_end, end + limit // 2)
    return _plain_tex(text[left:right])


def _mention_id(
    review_id: str, source_file: str, citation_start: int, bib_key: str
) -> str:
    raw = f"{review_id}\0{source_file}\0{citation_start}\0{bib_key}".encode("utf-8")
    return "mention-" + hashlib.sha256(raw).hexdigest()[:24]


def extract_review_mentions(
    tex_dir: str | Path,
    *,
    review_id: str,
    root_file: str = "main.tex",
) -> list[dict[str, Any]]:
    """Extract citation contexts while following TeX input/include order."""

    root = Path(tex_dir)
    start_path = root / root_file
    if not start_path.is_file():
        raise FileNotFoundError(start_path)
    mentions: list[dict[str, Any]] = []
    active_files: set[Path] = set()

    def visit(path: Path, section_path: list[str]) -> list[str]:
        resolved = path.resolve()
        if resolved in active_files:
            raise ValueError(f"cyclic TeX include: {path}")
        active_files.add(resolved)
        text = _strip_comments(path.read_text(encoding="utf-8", errors="replace"))
        state = list(section_path)
        for match in _TOKEN_COMMAND.finditer(text):
            token = match.group(0)
            heading_match = _HEADING_COMMAND.fullmatch(token)
            if heading_match:
                level = _LEVELS[heading_match.group(1)]
                heading = clean_latex_text(heading_match.group(2)) or ""
                state = state[:level]
                while len(state) < level:
                    state.append("")
                state.append(heading)
                continue
            input_match = _INPUT_COMMAND.fullmatch(token)
            if input_match:
                include_path = Path(input_match.group(1))
                if include_path.suffix == "":
                    include_path = include_path.with_suffix(".tex")
                candidate = root / include_path
                if candidate.is_file():
                    state = visit(candidate, state)
                continue
            cite_match = _CITE_COMMAND.fullmatch(token)
            if not cite_match:
                continue
            line = text.count("\n", 0, match.start()) + 1
            context = _citation_context(text, match.start(), match.end())
            source_file = path.relative_to(root).as_posix()
            for raw_key in cite_match.group(1).split(","):
                bib_key = raw_key.strip()
                if not bib_key or bib_key == "*":
                    continue
                mentions.append(
                    {
                        "mention_id": _mention_id(
                            review_id, source_file, match.start(), bib_key
                        ),
                        "review_id": review_id,
                        "bib_key": bib_key,
                        "source_file": source_file,
                        "section_path": [item for item in state if item],
                        "context_text": context,
                        "citation_command": token,
                        "line_number": line,
                        "char_start": match.start(),
                        "char_end": match.end(),
                    }
                )
        active_files.remove(resolved)
        return state

    visit(start_path, [])
    return mentions


def sync_review_mentions(
    db: LiteratureDB,
    tex_dir: str | Path,
    *,
    review_id: str,
    root_file: str = "main.tex",
) -> dict[str, int]:
    mentions = extract_review_mentions(
        tex_dir, review_id=review_id, root_file=root_file
    )
    work_by_key = {
        str(row["bib_key"]): int(row["work_id"])
        for row in db.conn.execute("SELECT bib_key,work_id FROM seed_entries")
    }
    with db.transaction():
        db.conn.execute("DELETE FROM review_mentions WHERE review_id=?", (review_id,))
        resolved = 0
        for mention in mentions:
            work_id = work_by_key.get(mention["bib_key"])
            resolved += int(work_id is not None)
            db.conn.execute(
                """
                INSERT INTO review_mentions(
                  mention_id,review_id,work_id,bib_key,source_file,
                  section_path_json,context_text,citation_command,
                  line_number,char_start,char_end,created_at
                ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    mention["mention_id"],
                    mention["review_id"],
                    work_id,
                    mention["bib_key"],
                    mention["source_file"],
                    json.dumps(mention["section_path"], ensure_ascii=False),
                    mention["context_text"],
                    mention["citation_command"],
                    mention["line_number"],
                    mention["char_start"],
                    mention["char_end"],
                    utc_now(),
                ),
            )
    return {
        "mentions": len(mentions),
        "resolved": resolved,
        "unresolved": len(mentions) - resolved,
        "works_mentioned": len(
            {mention["bib_key"] for mention in mentions if mention["bib_key"] in work_by_key}
        ),
    }


def _json_list(value: str | None) -> list[Any]:
    try:
        parsed = json.loads(value or "[]")
    except json.JSONDecodeError:
        return []
    return parsed if isinstance(parsed, list) else []


def _field_values(
    row: Any, mentions: list[Any]
) -> dict[str, list[tuple[str, str | None]]]:
    topics = _json_list(row["topics_json"])
    topic_text = " ".join(
        str(topic.get("display_name") or topic.get("name") or topic)
        if isinstance(topic, dict)
        else str(topic)
        for topic in topics
    )
    values: dict[str, list[tuple[str, str | None]]] = {
        "title": [(str(row["title"] or ""), None)],
        "abstract": [(str(row["abstract"] or ""), None)],
        "topics": [(topic_text, None)],
        "venue": [(str(row["venue"] or ""), None)],
        "work_type": [(str(row["work_type"] or ""), None)],
        "review_context": [
            (str(mention["context_text"] or ""), str(mention["mention_id"]))
            for mention in mentions
        ],
        "review_section": [
            (
                " > ".join(_json_list(mention["section_path_json"])),
                str(mention["mention_id"]),
            )
            for mention in mentions
        ],
    }
    return values


def _contains_keyword(text: str, keyword: str) -> bool:
    normalized_text = text.casefold()
    normalized_keyword = keyword.casefold()
    if re.fullmatch(r"[\w-]+", normalized_keyword, re.UNICODE):
        return (
            re.search(
                rf"(?<![\w-]){re.escape(normalized_keyword)}(?![\w-])",
                normalized_text,
            )
            is not None
        )
    return normalized_keyword in normalized_text


def _match_rule(
    rule: TaxonomyRule,
    values: dict[str, list[tuple[str, str | None]]],
) -> list[dict[str, Any]]:
    evidence: list[dict[str, Any]] = []
    candidates: list[tuple[str, str, str | None]] = []
    for field in rule.fields:
        candidates.extend(
            (field, text, mention_id)
            for text, mention_id in values.get(field, [])
            if text
        )

    criterion_hits: list[bool] = []
    for keyword in rule.keywords:
        hits = [
            (field, mention_id)
            for field, text, mention_id in candidates
            if _contains_keyword(text, keyword)
        ]
        criterion_hits.append(bool(hits))
        for field, mention_id in hits:
            evidence.append(
                {
                    "kind": "keyword",
                    "value": keyword,
                    "field": field,
                    **({"mention_id": mention_id} if mention_id else {}),
                }
            )
    for pattern in rule.regex:
        compiled = re.compile(pattern, re.IGNORECASE)
        hits = [
            (field, mention_id)
            for field, text, mention_id in candidates
            if compiled.search(text)
        ]
        criterion_hits.append(bool(hits))
        for field, mention_id in hits:
            evidence.append(
                {
                    "kind": "regex",
                    "value": pattern,
                    "field": field,
                    **({"mention_id": mention_id} if mention_id else {}),
                }
            )
    section_candidates = values.get("review_section", [])
    for section in rule.sections:
        hits = [
            mention_id
            for text, mention_id in section_candidates
            if _contains_keyword(text, section)
        ]
        criterion_hits.append(bool(hits))
        for mention_id in hits:
            evidence.append(
                {
                    "kind": "section",
                    "value": section,
                    "field": "review_section",
                    **({"mention_id": mention_id} if mention_id else {}),
                }
            )
    venue_candidates = values.get("venue", [])
    for venue in rule.venues:
        hits = [
            mention_id
            for text, mention_id in venue_candidates
            if _contains_keyword(text, venue)
        ]
        criterion_hits.append(bool(hits))
        for mention_id in hits:
            evidence.append(
                {
                    "kind": "venue",
                    "value": venue,
                    "field": "venue",
                    **({"mention_id": mention_id} if mention_id else {}),
                }
            )
    matched = bool(criterion_hits) and (
        all(criterion_hits) if rule.match == "all" else any(criterion_hits)
    )
    if not matched:
        return []
    unique: dict[tuple[str, str, str, str], dict[str, Any]] = {}
    for item in evidence:
        key = (
            item["kind"],
            item["value"],
            item["field"],
            item.get("mention_id", ""),
        )
        unique[key] = item
    return [unique[key] for key in sorted(unique)]


def classify_works(
    db: LiteratureDB,
    taxonomy: Taxonomy,
    *,
    seed_only: bool = True,
    progress: Callable[[str], None] | None = None,
) -> dict[str, Any]:
    """Apply deterministic rules and atomically replace rule-based assignments."""

    where = "WHERE is_seed=1" if seed_only else ""
    works = db.conn.execute(
        f"SELECT * FROM works {where} ORDER BY work_id"
    ).fetchall()
    mentions_by_work: dict[int, list[Any]] = {}
    for mention in db.conn.execute(
        """
        SELECT * FROM review_mentions
        WHERE work_id IS NOT NULL
        ORDER BY work_id,mention_id
        """
    ):
        mentions_by_work.setdefault(int(mention["work_id"]), []).append(mention)

    assignments: list[dict[str, Any]] = []
    for position, work in enumerate(works, start=1):
        work_id = int(work["work_id"])
        values = _field_values(work, mentions_by_work.get(work_id, []))
        grouped: dict[tuple[str, str], dict[str, Any]] = {}
        for rule in taxonomy.rules:
            evidence = _match_rule(rule, values)
            if not evidence:
                continue
            key = (rule.dimension_id, rule.category_id)
            assignment = grouped.setdefault(
                key,
                {
                    "work_id": work_id,
                    "dimension_id": rule.dimension_id,
                    "category_id": rule.category_id,
                    "confidence": 0.0,
                    "rule_ids": [],
                    "matches": [],
                },
            )
            matched_fields = {item["field"] for item in evidence}
            evidence_weight = max(
                (taxonomy.field_weights.get(field, 0.5) for field in matched_fields),
                default=0.5,
            )
            effective_confidence = min(rule.confidence, evidence_weight)
            assignment["confidence"] = max(
                float(assignment["confidence"]), effective_confidence
            )
            assignment["rule_ids"].append(rule.rule_id)
            assignment["matches"].extend(evidence)
        for assignment in grouped.values():
            assignment["rule_ids"] = sorted(set(assignment["rule_ids"]))
            unique_matches = {
                (
                    match["kind"],
                    match["value"],
                    match["field"],
                    match.get("mention_id", ""),
                ): match
                for match in assignment["matches"]
            }
            assignment["matches"] = [
                unique_matches[key] for key in sorted(unique_matches)
            ]
            assignments.append(assignment)
        if progress and (position % 500 == 0 or position == len(works)):
            progress(
                f"[Classify] rule evaluation {position}/{len(works)} works"
            )

    with db.transaction():
        db.conn.execute(
            """
            DELETE FROM work_classifications
            WHERE taxonomy_version=? AND method='deterministic_rule'
            """,
            (taxonomy.version,),
        )
        for assignment in assignments:
            db.conn.execute(
                """
                INSERT INTO work_classifications(
                  work_id,taxonomy_version,taxonomy_digest,dimension_id,
                  category_id,method,confidence,evidence_json,created_at,updated_at
                ) VALUES(?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    assignment["work_id"],
                    taxonomy.version,
                    taxonomy.digest,
                    assignment["dimension_id"],
                    assignment["category_id"],
                    "deterministic_rule",
                    assignment["confidence"],
                    json.dumps(
                        {
                            "rule_ids": assignment["rule_ids"],
                            "matches": assignment["matches"],
                        },
                        ensure_ascii=False,
                        sort_keys=True,
                    ),
                    utc_now(),
                    utc_now(),
                ),
            )
    return {
        "taxonomy_version": taxonomy.version,
        "taxonomy_digest": taxonomy.digest,
        "works_considered": len(works),
        "works_classified": len(
            {int(assignment["work_id"]) for assignment in assignments}
        ),
        "assignments": len(assignments),
        "seed_only": seed_only,
    }


def classification_rows(
    db: LiteratureDB, work_ids: Iterable[int] | None = None
) -> dict[int, list[dict[str, Any]]]:
    params: list[Any] = []
    where = ""
    if work_ids is not None:
        ids = sorted({int(work_id) for work_id in work_ids})
        if not ids:
            return {}
        where = f"WHERE work_id IN ({','.join('?' for _ in ids)})"
        params.extend(ids)
    rows: dict[int, list[dict[str, Any]]] = {}
    for row in db.conn.execute(
        f"""
        SELECT work_id,taxonomy_version,dimension_id,category_id,
               method,confidence,evidence_json
        FROM work_classifications
        {where}
        ORDER BY work_id,dimension_id,category_id,method
        """,
        params,
    ):
        evidence = json.loads(row["evidence_json"] or "{}")
        compact_matches = [
            {
                "kind": item.get("kind"),
                "value": item.get("value"),
                "field": item.get("field"),
                **(
                    {"mention_id": item["mention_id"]}
                    if item.get("mention_id")
                    else {}
                ),
            }
            for item in evidence.get("matches", [])
        ]
        rows.setdefault(int(row["work_id"]), []).append(
            {
                "taxonomy_version": row["taxonomy_version"],
                "dimension": row["dimension_id"],
                "category": row["category_id"],
                "method": row["method"],
                "confidence": row["confidence"],
                "rule_ids": evidence.get("rule_ids", []),
                "evidence": compact_matches,
            }
        )
    return rows
