"""Entity extraction + the LangGraph shared state schema."""
import re
from typing import Dict, Any, Optional, List, Annotated, Sequence

from langchain_core.messages import BaseMessage
from langgraph.graph.message import add_messages
from typing_extensions import TypedDict
from motor.motor_asyncio import AsyncIOMotorDatabase


class EntityExtractor:
    """Extract entities from questions"""

    TICKER_STOPWORDS = {
        "I", "A", "AN", "THE", "IS", "IT", "IN", "ON", "AT", "TO", "OF",
        "OR", "AND", "BUT", "FOR", "NOT", "ARE", "WAS", "CAN", "HOW",
        "WHAT", "WHY", "WHO", "WHEN", "OK", "YES", "NO", "PLEASE",
        "AI", "ML", "API", "GDP", "CPI", "PPI", "IPO", "ETF", "CEO",
        "CFO", "USD", "IDR", "EUR", "JPY", "WIB", "BI", "OJK", "IMF",
        "US", "UK", "EU", "PE", "PBV", "ROE", "ROA", "YOY", "QOQ", "YTD",
        "Q", "FAQ", "PDF", "HTML", "APBD", "DPRD", "RAG", "LLM",
    }

    @staticmethod
    def extract(question: str) -> Dict[str, Any]:
        """Extract key entities from question"""
        entities = {
            "companies": [],
            "sectors": [],
            "assets": [],
            "metrics": [],
            "time_periods": []
        }

        ticker_pattern = r'\b[A-Z]{2,5}\b'
        tickers = [
            t for t in re.findall(ticker_pattern, question)
            if t not in EntityExtractor.TICKER_STOPWORDS
        ]
        entities["companies"] = tickers

        sectors = ["tech", "technology", "healthcare", "finance", "financial", "energy",
                   "consumer", "industrial", "real estate", "utilities", "materials"]
        question_lower = question.lower()
        entities["sectors"] = [s for s in sectors if s in question_lower]

        assets = {
            "stocks": ["stock", "equity", "share", "company"],
            "crypto": ["crypto", "bitcoin", "ethereum", "blockchain"],
            "commodities": ["gold", "oil", "copper", "commodity"],
            "forex": ["currency", "dollar", "euro", "yen"]
        }
        for asset_type, keywords in assets.items():
            if any(kw in question_lower for kw in keywords):
                entities["assets"].append(asset_type)

        metrics = ["pe ratio", "revenue", "earnings", "profit", "margin", "dividend", "yield"]
        entities["metrics"] = [m for m in metrics if m in question_lower]

        time_periods = ["today", "yesterday", "week", "month", "quarter", "year", "year to date"]
        entities["time_periods"] = [tp for tp in time_periods if tp in question_lower]

        return entities

class AgentState(TypedDict):
    """Tracks the total operational memory of our multi-agent network."""
    messages: Annotated[Sequence[BaseMessage], add_messages]
    current_question: str
    language: str
    is_greeting: bool
    is_gratitude: bool
    is_valid: bool
    validation_reason: str
    retrieved_context: str
    sources: List[Dict[str, Any]]
    analysis_result: str
    recommendations: List[str]
    queue_data: Dict[str, Any]
    next_worker: str
    error: Optional[str]
    db: Optional[AsyncIOMotorDatabase]
    user_id: Optional[str]
    username: Optional[str]
    start_time: float
    response_type: str
    entities: Dict[str, Any]
    step_count: int
    groundedness: Optional[Dict[str, Any]]
    prompt_version: str
