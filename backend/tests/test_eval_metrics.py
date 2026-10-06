"""Matching helpers of the evaluation harness (evaluation/run_eval.py)."""

import importlib.util
from pathlib import Path

_spec = importlib.util.spec_from_file_location(
    "run_eval", Path(__file__).resolve().parents[2] / "evaluation" / "run_eval.py")
run_eval = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(run_eval)


def test_fact_matching_treats_number_words_and_digits_alike():
    norm = run_eval.norm_text
    assert norm("सोह्र वर्ष") in norm("१६ वर्ष उमेर पूरा भएपछि")
    assert norm("१६ वर्ष") in norm("सोह्र वर्ष उमेर पूरा भएपछि")
    assert norm("पन्ध्र वर्ष") in norm("कम्तीमा 15 वर्षसम्म")
    assert norm("तीन जना") in norm("३ जना")
    assert norm("सात") not in norm("साताको")  # number words inside other words are left alone
    assert norm("छ") == "छ"


def test_english_answer_with_bracketed_nepali_terms_counts_as_english():
    answer = ("You need a relation verification letter (नाता प्रमाणित पत्र) and a migration "
              "certificate (बसाइँ सराइको प्रमाणपत्र) from the ward office [3].")
    assert run_eval.language_ok(answer, "en")
    assert not run_eval.language_ok("तपाईंले जिल्ला प्रशासन कार्यालयमा निवेदन दिनुपर्छ।", "en")
    assert run_eval.language_ok("तपाईंले जिल्ला प्रशासन कार्यालयमा निवेदन दिनुपर्छ।", "ne")
    assert not run_eval.language_ok("Please apply at the District Administration Office.", "ne")
