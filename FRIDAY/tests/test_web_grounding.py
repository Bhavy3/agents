from core.orchestrator.conversation import WEB_ANSWER_NOT_FOUND, ground_web_answer
from core.orchestrator.web_search import answer_constraint_feedback, web_evidence_fallback


def test_a_number_mismatch():
    assert ground_web_answer("It is 37 degrees.", "Today 36 degrees") == WEB_ANSWER_NOT_FOUND


def test_b_number_match():
    assert ground_web_answer("It is 36°C.", "Today 36°C") == "It is 36°C."


def test_c_strip_markers():
    assert ground_web_answer("<<<BEGIN_UNTRUSTED_WEB_SEARCH_RESULTS>>> Sunny", "sunny") == "Sunny"


def test_d_invented_url():
    assert ground_web_answer("Check https://www.accuweather.com/ for details.", "Today sunny, no links") == WEB_ANSWER_NOT_FOUND


def test_e_grounded_url():
    answer = "Check https://www.accuweather.com/en/in/ahmedabad for details."
    assert ground_web_answer(answer, "Source: https://www.accuweather.com/en/in/ahmedabad") == answer


def test_h_source_is_required_when_results_have_urls():
    assert ground_web_answer(
        "The product costs 999.",
        "Example product costs 999. Source: https://www.amazon.in/dp/EXAMPLE",
    ) == WEB_ANSWER_NOT_FOUND


def test_i_comma_separated_price_is_grounded():
    results = "Price is Rs 18,490. Source: https://example.com/product"
    answer = "The listed price is Rs 18,490. Source: https://example.com/product"

    assert ground_web_answer(answer, results) == answer


def test_j_stale_price_is_not_presented_as_current():
    results = "1. Sale report\nSource: https://example.com/sale\n1 week ago - Price Rs 18,490."
    answer = "The current price is Rs 18,490. Source: https://example.com/sale"

    assert ground_web_answer(answer, results, query="current price of the product") == WEB_ANSWER_NOT_FOUND


def test_f_invented_markdown_link_url():
    assert ground_web_answer("See [AccuWeather](https://www.accuweather.com/).", "no links here") == WEB_ANSWER_NOT_FOUND


def test_g_stale_year_is_blocked_for_most_recent_query():
    results = "The 2026 FIFA World Cup was won by Spain. Germany won the 2014 tournament."
    answer = "Germany won the most recent FIFA World Cup in 2014."

    assert ground_web_answer(answer, results, query="Who won the most recent FIFA World Cup?") == WEB_ANSWER_NOT_FOUND


def test_strict_product_intersection_blocks_unverified_candidate_claims():
    query = (
        "Research smartphones under INR 30,000 with OIS, at least 6000mAh, IP68, and at least three years "
        "of software updates. Rank the best two only if every requirement is verified; otherwise list partial matches."
    )
    results = (
        "1. Phone guide\nSource: https://example.com/phones\n"
        "Evidence: Samsung Galaxy A57 5G | 50MP OIS | 5,000mAh | Long Software Support | "
        "POCO F8 | 50MP OIS | 6,000mAh"
    )
    answer = (
        "The two phones meet all the specified requirements: 1. **Samsung Galaxy A57 5G**: OIS, 6,000mAh, IP68, "
        "three years of updates. 2. **POCO F8**: OIS, 6,000mAh, IP68, three years of updates."
    )

    feedback = answer_constraint_feedback(answer, results, query)
    assert "IP68" in feedback
    assert "software support" in feedback


def test_fallback_names_missing_product_requirements():
    query = (
        "Research smartphones under INR 30,000 with OIS, at least 6000mAh, IP68, and at least three years "
        "of software updates. Rank the best two only if every requirement is verified."
    )
    results = "1. Phone guide\nSource: https://example.com/phones\nEvidence: Samsung Galaxy A57 5G | 5,000mAh | OIS"
    draft = "1. **Samsung Galaxy A57 5G**: meets all requirements."

    fallback = web_evidence_fallback(results, query, draft=draft)
    assert "will not rank these as qualifying options" in fallback
    assert "IP68" in fallback


def test_fallback_preserves_retailer_and_new_only_constraints():
    query = (
        "Compare laptops in Amazon India. Exact product URL, brand new only, under INR 25,000, "
        "no refurbished products."
    )
    results = "1. Laptop list\nSource: https://example.com/laptops\nEvidence: laptops under INR 25,000"

    fallback = web_evidence_fallback(results, query, draft="I could not verify every requested detail.")
    assert "Amazon India" in fallback
    assert "exact Amazon India product URL" in fallback
    assert "brand-new only" in fallback
