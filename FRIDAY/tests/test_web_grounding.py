from core.orchestrator.conversation import WEB_ANSWER_NOT_FOUND, ground_web_answer


def test_a_number_mismatch():
    assert ground_web_answer("It is 37 degrees.", "Today 36 degrees") == WEB_ANSWER_NOT_FOUND


def test_b_number_match():
    assert ground_web_answer("It is 36°C.", "Today 36°C") == "It is 36°C."


def test_c_strip_markers():
    assert ground_web_answer("<<<BEGIN_UNTRUSTED_WEB_SEARCH_RESULTS>>> Sunny", "sunny") == "Sunny"


def test_d_invented_url():
    assert ground_web_answer("Check https://www.accuweather.com/ for details.", "Today sunny, no links") == WEB_ANSWER_NOT_FOUND


def test_e_grounded_url():
    assert ground_web_answer("Check https://www.accuweather.com/ for details.", "Source: https://www.accuweather.com/en/in/ahmedabad") == "Check https://www.accuweather.com/ for details."


def test_f_invented_markdown_link_url():
    assert ground_web_answer("See [AccuWeather](https://www.accuweather.com/).", "no links here") == WEB_ANSWER_NOT_FOUND
