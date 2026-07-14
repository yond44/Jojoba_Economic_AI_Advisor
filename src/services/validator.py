"""Topic validation for incoming questions.

Uses word-boundary matching so short keywords like "us" or "oil"
only match whole words, not substrings of unrelated words.
"""
import re

ALLOWED_TOPICS = [
    "stock", "stocks", "equity", "equities", "shares", "idx", "market",
    "markets", "trading", "pe ratio", "dividend", "earnings", "profit",

    "economy", "economic", "economics", "inflation", "gdp", "growth",
    "interest rate", "central bank", "bi rate", "fed",
    "bank indonesia", "federal reserve", "recession", "monetary", "fiscal",

    "crypto", "cryptocurrency", "bitcoin", "ethereum", "blockchain",
    "defi", "nft", "token", "stablecoin",

    "commodity", "commodities", "gold", "silver", "oil", "petroleum",
    "gas", "palm oil", "nickel", "coal", "copper", "lithium",

    "invest", "investment", "investing", "portfolio", "asset", "assets",
    "diversify", "return", "returns", "risk", "yield", "bond", "bonds",
    "treasury",

    "indonesia", "indonesian", "rupiah", "idr", "exchange rate",
    "trade balance", "export", "exports", "import", "imports",
    "current account", "foreign reserve",

    "trade", "tariff", "tariffs", "supply chain", "geopolitics",
    "sanction", "sanctions", "trade war", "agreement",
    "asean", "china", "usa", "europe", "eu",
]

FORBIDDEN_TOPICS = [
    "medical", "health", "doctor", "medicine",
    "legal", "lawyer", "attorney", "court",
    "dating", "drugs", "weapons", "crime", "terrorism",
]

OFF_TOPIC_RESPONSE = """I can only help with questions about:
- Economics and macroeconomics
- Stock markets and equities
- Crypto and DeFi
- Commodities
- Business and corporate news
- Global trade and geopolitics

For questions outside these topics, I cannot provide answers.

Any other questions about economics or investments?"""

MAX_QUESTION_LENGTH = 2000


def _contains_keyword(text: str, keyword: str) -> bool:
    """Whole-word / whole-phrase match, case-insensitive."""
    pattern = r"\b" + re.escape(keyword) + r"\b"
    return re.search(pattern, text, re.IGNORECASE) is not None


def validate_query(question: str) -> dict:
    if not question or not question.strip():
        return {
            "allowed": False,
            "response": "Please provide a valid question.",
            "reason": "Empty question",
        }

    if len(question) > MAX_QUESTION_LENGTH:
        return {
            "allowed": False,
            "response": f"Question is too long (max {MAX_QUESTION_LENGTH} characters).",
            "reason": "Question exceeds length limit",
        }

    for topic in FORBIDDEN_TOPICS:
        if _contains_keyword(question, topic):
            return {
                "allowed": False,
                "response": OFF_TOPIC_RESPONSE,
                "reason": f"Contains forbidden topic: {topic}",
            }

    if not any(_contains_keyword(question, topic) for topic in ALLOWED_TOPICS):
        return {
            "allowed": False,
            "response": OFF_TOPIC_RESPONSE,
            "reason": "No matching topic",
        }

    return {"allowed": True}
