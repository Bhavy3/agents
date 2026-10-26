"""Pure, domain-independent extraction and validation of search constraints."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class Constraint:
    kind: str
    raw: str
    value: Any
    unit: str | None
    polarity: str


@dataclass(frozen=True, slots=True)
class Result:
    constraint: Constraint
    status: str
    evidence_snippet: str


_MONTHS = (
    "january|february|march|april|may|june|july|august|september|"
    "october|november|december"
)
_NUMBER_WORDS = {
    "one": 1, "two": 2, "three": 3, "four": 4, "five": 5,
    "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10,
}
_DIGITS = str.maketrans("०१२३४५६७८९", "0123456789")
_NUMBER = r"(?:[\d०-९][\d०-९,]*(?:[.]\d+)?|one|two|three|four|five|six|seven|eight|nine|ten)"
_UNIT = r"(?:₹|\$|€|£|%|[A-Za-z][A-Za-z0-9/%-]*|रुप(?:ये|ए)?|जीबी|घंटे)"
_RELATION = (
    r"under|below|less than|up to|at most|not more than|over|above|more than|"
    r"at least|minimum(?: of)?|no less than|exactly|equal to|priced at|at|"
    r"से कम|तक|से अधिक|कम से कम"
)
_COMPARISON = re.compile(
    rf"(?P<relation>{_RELATION})\s+"
    rf"(?P<prefix_unit>{_UNIT})?\s*(?P<number>{_NUMBER})\s*(?P<unit>{_UNIT})?",
    re.IGNORECASE,
)
_SUFFIX_COMPARISON = re.compile(
    rf"(?P<prefix_unit>{_UNIT})?\s*(?P<number>{_NUMBER})\s*(?P<unit>{_UNIT})?\s*"
    rf"(?P<relation>से कम|तक|से अधिक|कम से कम)",
    re.IGNORECASE,
)
_STANDALONE_NUMBER = re.compile(rf"(?P<number>{_NUMBER})\s*(?P<unit>{_UNIT})?", re.IGNORECASE)
_YEAR = re.compile(r"\b(?:18|19|20|21)\d{2}\b")
_MONTH = re.compile(rf"\b(?:{_MONTHS})\b(?:\s+(?P<year>\d{{4}}))?", re.IGNORECASE)
_QUOTED = re.compile(r"(?P<quote>[\"'])(?P<value>.+?)(?P=quote)")
_PLACE = re.compile(
    r"\b(?P<preposition>in|from|to)\s+"
    r"(?P<place>[A-ZÀ-ÖØ-Þ][\wÀ-ÖØ-ÿ-]*(?:\s+[A-ZÀ-ÖØ-Þ][\wÀ-ÖØ-ÿ-]*)?)"
)
_EXCLUSION = re.compile(
    r"\b(?:not|without|except|excluding)\s+(?P<value>[^,.;!?]+?)"
    r"(?=\s+(?:with|and|or|for|under|below|over|above|in|from|to)\b|[,.;!?]|$)",
    re.IGNORECASE,
)
_FEATURE_PHRASE = re.compile(
    r"\b(?:of|with|for)\s+(?P<value>[a-z][a-z0-9]*(?:\s+[a-z][a-z0-9]*){0,3})"
    r"(?=\s+(?:and|or|under|below|over|above|at least|in|from|to)\b|[,.;!?]|$)",
)

_STOPWORDS = {
    "a", "an", "and", "are", "at", "after", "above", "below", "before", "book", "by",
    "camera", "course", "find", "flight", "flights", "for", "from", "has", "headphones",
    "in", "is", "it", "laptop", "laptops", "monitor", "of", "on", "or", "power", "recommend",
    "research", "the", "to", "trains", "under", "with", "without", "over", "rank", "only",
    "compare", "exact", "url", "product", "products", "best", "two", "three", "four", "five",
    "search", "tell", "what", "when", "where", "who", "why", "how", "show", "open", "look", "please",
    "published", "starting", "starts", "rupees", "inr", "usd", "eur", "gbp",
}
_NON_UNIT_WORDS = {
    "a", "an", "and", "are", "at", "by", "for", "from", "has", "in", "is", "of", "on", "or",
    "the", "to", "with", "without", "only", "is", "are", "was", "were", "has", "have",
    "reaches", "reached", "costs", "cost", "listed", "available", "version", "release",
    "and", "or", "in", "on", "for", "from", "this", "that", "as", "of",
}


def _normalise(text: str) -> str:
    return str(text or "").translate(_DIGITS)


def _normalise_unit(unit: str | None) -> str | None:
    if not unit:
        return None
    value = unit.strip().lower().rstrip(".,;:")
    if value in _NON_UNIT_WORDS:
        return None
    return {
        "₹": "rupees", "rs": "rupees", "rs.": "rupees", "inr": "rupees", "rupee": "rupees",
        "रुपये": "rupees", "रुपए": "rupees", "$": "usd", "usd": "usd", "€": "eur", "eur": "eur",
        "£": "gbp", "gbp": "gbp", "जीबी": "gb", "gigabyte": "gb", "gigabytes": "gb",
        "hours": "hours", "hour": "hours", "घंटे": "hours", "hrs": "hours", "h": "hours",
    }.get(value, value)


def _number(value: str) -> int | float:
    word = value.lower()
    if word in _NUMBER_WORDS:
        return _NUMBER_WORDS[word]
    parsed = float(value.replace(",", ""))
    return int(parsed) if parsed.is_integer() else parsed


def _polarity(relation: str | None) -> str:
    relation = (relation or "").lower()
    if relation in {"under", "below", "less than", "up to", "at most", "not more than", "से कम", "तक"}:
        return "max"
    if relation in {"over", "above", "more than", "at least", "minimum", "minimum of", "no less than", "से अधिक", "कम से कम"}:
        return "min"
    return "equal"


def _numeric_constraint(match: re.Match[str], text: str) -> Constraint:
    groups = match.groupdict()
    relation = groups.get("relation")
    prefix_unit = _normalise_unit(groups.get("prefix_unit"))
    suffix_unit = _normalise_unit(groups.get("unit"))
    unit = suffix_unit or prefix_unit
    start = match.start("relation") if relation else match.start("number")
    end = match.end("number")
    if suffix_unit:
        end = match.end("unit")
    elif prefix_unit:
        end = match.end("number")
    raw = text[start:end].strip()
    return Constraint("numeric", raw, _number(groups["number"]), unit, _polarity(relation))


def _date_constraints(text: str) -> list[Constraint]:
    found: list[Constraint] = []
    for match in _MONTH.finditer(text):
        before = text[max(0, match.start() - 30):match.start()].lower()
        polarity = "min" if re.search(r"\bafter\s*$", before) else "max" if re.search(r"\bbefore\s*$", before) else "equal"
        found.append(Constraint("date", match.group(0), match.group(0).lower(), None, polarity))
    for match in _YEAR.finditer(text):
        before = text[max(0, match.start() - 30):match.start()].lower()
        if not re.search(r"\b(?:after|before|published|since|until|year|in)\b", before):
            continue
        if any(item.raw.endswith(match.group(0)) for item in found):
            continue
        polarity = "min" if re.search(r"\b(?:after|since)\b", before) else "max" if re.search(r"\b(?:before|until)\b", before) else "equal"
        found.append(Constraint("date", match.group(0), int(match.group(0)), None, polarity))
    return found


def _term_constraints(text: str, used: list[tuple[int, int]]) -> list[Constraint]:
    result: list[Constraint] = []

    def add(raw: str, value: str, polarity: str, span: tuple[int, int] | None = None) -> None:
        value = value.strip().strip("\"'")
        if not value or value.lower() in _STOPWORDS:
            return
        if span and any(span[0] >= start and span[1] <= end for start, end in used):
            return
        result.append(Constraint("term", raw.strip(), value, None, polarity))
        if span:
            used.append(span)

    for match in _QUOTED.finditer(text):
        add(match.group(0), match.group("value"), "required", match.span())
    for match in _EXCLUSION.finditer(text):
        value = match.group("value").strip()
        value = re.split(r"\s+(?:products?|options?|models?)\b", value, maxsplit=1, flags=re.I)[0]
        add(value, value, "excluded", match.span())
    for match in _FEATURE_PHRASE.finditer(text):
        value = match.group("value").strip()
        if value.lower() not in {"the", "best", "one", "two", "three"}:
            add(value, value, "required", match.span("value"))
    for match in re.finditer(r"\b[A-ZÀ-ÖØ-Þ][\wÀ-ÖØ-ÿ-]*(?:\s+[A-ZÀ-ÖØ-Þ][\wÀ-ÖØ-ÿ-]*)*\b", text):
        value = match.group(0).strip()
        before = text[:match.start()]
        if value.lower() in _STOPWORDS or value.lower() in {item.lower() for item in _MONTHS.split("|")}:
            continue
        if re.search(r"\d\s*$", before) or re.search(r"\b(?:in|from|to)\s*$", before.lower()):
            continue
        if not any(char.isdigit() for char in value) and len(value.split()) < 2:
            continue
        add(value, value, "required", match.span())
    return result


def extract_constraints(text: str) -> list[Constraint]:
    """Extract numeric, term, exclusion, date, and place constraints without an LLM."""
    normalised = _normalise(text)
    constraints = _date_constraints(normalised)
    used: list[tuple[int, int]] = []

    for pattern in (_COMPARISON, _SUFFIX_COMPARISON):
        for match in pattern.finditer(normalised):
            if any(match.start() >= start and match.end() <= end for start, end in used):
                continue
            constraints.append(_numeric_constraint(match, normalised))
            used.append(match.span())

    for match in _STANDALONE_NUMBER.finditer(normalised):
        if any(match.start() >= start and match.end() <= end for start, end in used):
            continue
        if not _normalise_unit(match.group("unit")):
            continue
        if match.start() and normalised[match.start() - 1].isalnum():
            continue
        constraints.append(_numeric_constraint(match, normalised))
        used.append(match.span())

    months = {item.lower() for item in _MONTHS.split("|")}
    for match in _PLACE.finditer(normalised):
        place = match.group("place").strip()
        if place.lower() not in months:
            constraints.append(Constraint("place", place, place, None, "required"))

    constraints.extend(_term_constraints(normalised, used))

    unique: list[Constraint] = []
    seen: set[tuple[str, str, str, str]] = set()
    for item in sorted(constraints, key=lambda value: normalised.lower().find(value.raw.lower().strip("\"'"))):
        key = (item.kind, item.raw.lower(), str(item.value).lower(), item.polarity)
        if key not in seen:
            unique.append(item)
            seen.add(key)
    return unique


def _numeric_evidence(evidence: str, constraint: Constraint) -> list[tuple[float, str]]:
    values: list[tuple[float, str]] = []
    for match in _STANDALONE_NUMBER.finditer(_normalise(evidence)):
        unit = _normalise_unit(match.group("unit"))
        if constraint.unit and unit != constraint.unit:
            continue
        if not match.group("unit"):
            continue
        values.append((float(_number(match.group("number"))), match.group(0)))
    return values


def _validate_numeric(constraint: Constraint, evidence: str) -> tuple[str, str]:
    values = _numeric_evidence(evidence, constraint)
    if not values:
        return "missing", ""
    target = float(constraint.value)
    if constraint.polarity == "max":
        good = [value for value in values if value[0] <= target]
        bad = [value for value in values if value[0] > target]
    elif constraint.polarity == "min":
        good = [value for value in values if value[0] >= target]
        bad = [value for value in values if value[0] < target]
    else:
        good = [value for value in values if value[0] == target]
        bad = [value for value in values if value[0] != target]
    if good and not (constraint.polarity == "equal" and bad):
        return "satisfied", good[0][1]
    return "contradicted", (bad[0][1] if bad else values[0][1])


def _validate_date(constraint: Constraint, evidence: str) -> tuple[str, str]:
    lower = _normalise(evidence).lower()
    if isinstance(constraint.value, int):
        years = [int(value) for value in _YEAR.findall(lower)]
        if not years:
            return "missing", ""
        target = constraint.value
        if constraint.polarity == "min":
            good = [year for year in years if year > target]
        elif constraint.polarity == "max":
            good = [year for year in years if year < target]
        else:
            good = [year for year in years if year == target]
        return ("satisfied", str(good[0])) if good else ("contradicted", str(years[0]))
    match = re.match(r"([a-z]+)(?:\s+(\d{4}))?", str(constraint.value).lower())
    if not match:
        return "missing", ""
    month, year = match.groups()
    pattern = rf"\b{re.escape(month)}\b" + (rf"\s+{year}\b" if year else "")
    found = re.search(pattern, lower)
    if found:
        return "satisfied", found.group(0)
    conflicting = re.search(rf"\b(?:{_MONTHS})\b", lower)
    if conflicting:
        return "contradicted", conflicting.group(0)
    return "missing", ""


def validate_constraints(constraints: list[Constraint], evidence_text: str) -> list[Result]:
    """Return one satisfied/missing/contradicted result for every constraint."""
    evidence = _normalise(evidence_text)
    results: list[Result] = []
    for constraint in constraints:
        if constraint.kind == "numeric":
            status, snippet = _validate_numeric(constraint, evidence)
        elif constraint.kind == "date":
            status, snippet = _validate_date(constraint, evidence)
        else:
            found = re.search(re.escape(str(constraint.value).lower()), evidence.lower()) if evidence else None
            if constraint.polarity == "excluded":
                status = "contradicted" if found else ("missing" if not evidence.strip() else "satisfied")
            else:
                status = "satisfied" if found else "missing"
            snippet = found.group(0) if found else ""
        results.append(Result(constraint, status, snippet))
    return results
