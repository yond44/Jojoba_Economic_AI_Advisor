"""Unit tests for the topic validator.

Includes regression tests for the substring-matching bug where short
keywords ("us", "oil") matched inside unrelated words ("buses", "boiling").
"""
from src.services.validator import validate_query, MAX_QUESTION_LENGTH


class TestAllowedTopics:
    def test_stock_question_is_allowed(self):
        assert validate_query("What is the best stock to buy right now?")["allowed"]

    def test_indonesian_economy_is_allowed(self):
        assert validate_query("How is inflation affecting the rupiah?")["allowed"]

    def test_crypto_is_allowed(self):
        assert validate_query("Should I invest in bitcoin?")["allowed"]

    def test_commodities_are_allowed(self):
        assert validate_query("What are oil prices doing this week?")["allowed"]


class TestRejectedTopics:
    def test_off_topic_is_rejected(self):
        result = validate_query("What is the best recipe for fried rice?")
        assert not result["allowed"]
        assert result["reason"] == "No matching topic"

    def test_forbidden_topic_is_rejected(self):
        result = validate_query("Which medicine should I take for my economy class flight anxiety?")
        assert not result["allowed"]

    def test_empty_question_is_rejected(self):
        assert not validate_query("")["allowed"]
        assert not validate_query("   ")["allowed"]

    def test_overly_long_question_is_rejected(self):
        result = validate_query("stock " * (MAX_QUESTION_LENGTH // 4))
        assert not result["allowed"]


class TestWordBoundaryRegressions:
    """The old validator used substring matching; these inputs used to misfire."""

    def test_buses_does_not_match_us(self):
        assert not validate_query("Tell me about buses in Jakarta")["allowed"]

    def test_boiling_does_not_match_oil(self):
        assert not validate_query("How long should I keep water boiling?")["allowed"]

    def test_gasoline_context_still_works(self):
        assert validate_query("Why are gas prices rising?")["allowed"]

    def test_case_insensitive(self):
        assert validate_query("BITCOIN price prediction")["allowed"]
