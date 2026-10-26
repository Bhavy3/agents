from core.tools.constraints import extract_constraints, validate_constraints


def _statuses(question: str, evidence: str):
    constraints = extract_constraints(question)
    results = validate_constraints(constraints, evidence)
    return [(result.constraint.raw, result.status) for result in results]


def test_laptop_budget_and_memory_are_satisfied():
    statuses = _statuses(
        "Recommend laptops under 60000 rupees with 16 GB RAM",
        "The laptop has 16 GB RAM and is listed at 58999 rupees.",
    )
    assert [status for _, status in statuses] == ["satisfied", "satisfied"]


def test_laptop_memory_requirement_is_contradicted_by_eight_gb():
    statuses = _statuses(
        "Recommend laptops under 60000 rupees with 16 GB RAM",
        "The laptop has 8 GB RAM and is listed at 58999 rupees.",
    )
    assert [status for _, status in statuses] == ["satisfied", "contradicted"]


def test_excluded_headphone_brand_and_battery_are_satisfied():
    statuses = _statuses(
        "Find headphones not Sony with 30 hours battery",
        "The Acme headphones provide 30 hours of battery life.",
    )
    assert [status for _, status in statuses] == ["satisfied", "satisfied"]


def test_excluded_headphone_brand_is_contradicted():
    statuses = _statuses(
        "Find headphones not Sony with 30 hours battery",
        "The Sony headphones provide 30 hours of battery life.",
    )
    assert [status for _, status in statuses] == ["contradicted", "satisfied"]


def test_route_places_and_month_are_satisfied():
    statuses = _statuses(
        "Find flights from Pune to Dubai in March",
        "The itinerary departs from Pune and arrives in Dubai in March.",
    )
    assert [status for _, status in statuses] == ["satisfied", "satisfied", "satisfied"]


def test_publication_date_after_2019_is_satisfied():
    statuses = _statuses(
        "Find a book published after 2019",
        "The book was published in 2021.",
    )
    assert [status for _, status in statuses] == ["satisfied"]


def test_publication_date_after_2019_is_contradicted_by_2018():
    statuses = _statuses(
        "Find a book published after 2019",
        "The book was published in 2018.",
    )
    assert [status for _, status in statuses] == ["contradicted"]


def test_exact_price_is_contradicted_by_conflicting_prices():
    statuses = _statuses(
        "Find a camera priced at 50000 rupees",
        "The listing shows two conflicting prices: 49999 rupees and 51000 rupees.",
    )
    assert [status for _, status in statuses] == ["contradicted"]


def test_empty_evidence_marks_every_constraint_missing():
    statuses = _statuses(
        'Find a "quiet keyboard" with 120 Hz refresh rate',
        "",
    )
    assert [status for _, status in statuses] == ["missing", "missing"]


def test_quoted_term_is_satisfied_when_present():
    statuses = _statuses(
        'Find a monitor with "eye comfort mode"',
        "This monitor includes an eye comfort mode.",
    )
    assert [status for _, status in statuses] == ["satisfied"]


def test_exclusion_without_lithium_is_contradicted_when_lithium_is_present():
    statuses = _statuses(
        "Find a power bank without lithium",
        "The power bank uses a lithium-ion cell.",
    )
    assert [status for _, status in statuses] == ["contradicted"]


def test_unicode_and_hindi_numerals_are_supported():
    constraints = extract_constraints("कैमरा २०००० रुपये से कम और ८ जीबी स्टोरेज")
    statuses = validate_constraints(constraints, "The camera costs 18000 rupees and has 8 GB storage.")
    assert [status for status in (result.status for result in statuses)] == ["satisfied", "satisfied"]


def test_conflicting_month_is_contradicted():
    statuses = _statuses(
        "Find a course starting in April 2027",
        "The course starts in May 2027.",
    )
    assert [status for _, status in statuses] == ["contradicted"]


def test_missing_destination_is_missing():
    statuses = _statuses(
        "Find trains from Kyoto to Osaka",
        "The train departs from Kyoto.",
    )
    assert [status for _, status in statuses] == ["satisfied", "missing"]
