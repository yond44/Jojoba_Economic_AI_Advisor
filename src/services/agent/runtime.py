"""Agent entrypoint: initialization, response builder, ask_agent, status."""
import logging
import uuid
import time
import threading
import asyncio
from typing import Dict, Any, Optional, List
from datetime import datetime
from pathlib import Path

from langchain_core.messages import BaseMessage, AIMessage, HumanMessage
from motor.motor_asyncio import AsyncIOMotorDatabase

from src.config.prompts import (
    detect_gratitude, get_fallback_response,
    get_gratitude_response, get_off_topic_response,
    get_no_data_response, format_response_with_disclaimer,
    format_response_with_sources, get_error_response, detect_greeting,
    detect_language, SYSTEM_PROMPT, DISCLAIMER,
    IntelligentRecommender, format_complete_response, get_rate_limit_response,
    get_greeting_response, detect_human_expression
)

from src.services.rag import query_rag, initialize_rag, get_rag_status, setup_llm
from src.services.validator import validate_query
from src.services.question_manager import (
    get_next_question, remove_first_question, add_question,
    generate_new_question_from_data, get_all_questions,
    get_question_count, reset_question_queue,
    initialize_question_file, get_archive, get_file_paths
)

from src.services.agent.models import (
    QueryRequest, QueryResponse, BatchEmailRequest, ChannelType, ConversationContext,
)
from src.services.agent.state import AgentState, EntityExtractor
from src.services.agent.conversation import conversation_manager
from src.services.agent.graph import build_economic_advisor_graph
from src.services.agent.config import MAX_AGENT_STEPS, MAX_CONTEXTS, CONTEXT_TTL_HOURS
from src.services.agent.util import _utcnow

logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parents[3]

_is_initialized = False
_graph_app = None
_mongo_db = None
_init_lock = threading.Lock()


def initialize_agent(force_reindex: bool = False, mongo_db=None):
    """Initialize the agent and compile the graph.

    PRODUCTION FIX #2 — thread-safe with double-checked locking, exactly
    like rag.py FIX #1: two concurrent cold-start requests must not both
    run the expensive init (RAG attach + graph compile).
    """
    global _is_initialized

    if _is_initialized and not force_reindex:
        if mongo_db is not None:
            _set_default_db(mongo_db)
        return

    with _init_lock:
        if _is_initialized and not force_reindex:
            if mongo_db is not None:
                _set_default_db(mongo_db)
            return
        _do_initialize_agent(force_reindex, mongo_db)

def _set_default_db(mongo_db):
    """FIX #6: the module-level db is a DEFAULT set at initialization —
    it is never mutated per-request anymore (see ask_agent)."""
    global _mongo_db
    _mongo_db = mongo_db

def _do_initialize_agent(force_reindex: bool, mongo_db):
    """The actual init work. Only ever runs while holding _init_lock."""
    global _is_initialized, _graph_app

    if mongo_db is not None:
        _set_default_db(mongo_db)

    try:
        logger.info("🤖 Initializing Multi-Agent Economic Advisor...")
        logger.info(f"📁 Project root: {PROJECT_ROOT}")
        logger.info(f"📁 Question files: {get_file_paths()}")

        initialize_rag(force_reindex=force_reindex)
        logger.info("✅ RAG system (ChromaDB) initialized")

        try:
            count = initialize_question_file(db=_mongo_db) if _mongo_db is not None else 0
            logger.info(f"✅ Question queue (MongoDB) initialized with {count} questions")
        except Exception as e:
            logger.warning(f"⚠️ Question queue initialization warning: {str(e)}")

        _graph_app = build_economic_advisor_graph()
        logger.info("✅ LangGraph multi-agent system compiled")

        _is_initialized = True
        logger.info("✅ Multi-Agent Economic Advisor ready!")

    except Exception as e:
        logger.error(f"❌ Agent initialization failed: {str(e)}")
        raise

def _build_response(
    *,
    question: str,
    answer: str,
    start_time: float,
    thread_id: str,
    language: str,
    response_type: str,
    success: bool,
    validated: bool = True,
    greeting: bool = False,
    gratitude: bool = False,
    sources: Optional[List[Dict[str, Any]]] = None,
    recommendations: Optional[List[str]] = None,
    queue_info: Optional[Dict[str, Any]] = None,
    user_id: Optional[str] = None,
    error: Optional[str] = None,
    attempts: int = 1,
    groundedness: Optional[Dict[str, Any]] = None,
    record_metrics: bool = True,
) -> Dict[str, Any]:
    processing_time = time.time() - start_time

    if record_metrics:
        conversation_manager.metrics.record(
            response_type=response_type,
            success=success,
            processing_time=processing_time,
        )

    return {
        "question": question,
        "answer": answer,
        "processing_time": processing_time,
        "thread_id": thread_id,
        "language_detected": language,
        "response_type": response_type,
        "success": success,
        "validated": validated,
        "greeting": greeting,
        "gratitude": gratitude,
        "sources": sources or [],
        "recommendations": recommendations or [],
        "queue_info": queue_info or {},
        "user_id": user_id,
        "error": error,
        "attempts": attempts,
        "groundedness": groundedness,
        "timestamp": _utcnow().isoformat(),
    }

async def ask_agent(
    question: str,
    thread_id: Optional[str] = None,
    db: Optional[AsyncIOMotorDatabase] = None,
    user_id: Optional[str] = None,
    username: Optional[str] = None,
    language: Optional[str] = None,
    channel: str = "api"
) -> dict:
    """
    Main entry point for agent queries.
    Returns markdown-formatted responses for proper rendering.
    """
    start_time = time.time()
    effective_db = db if db is not None else _mongo_db

    if not _is_initialized or _graph_app is None:
        await asyncio.to_thread(initialize_agent, False, effective_db)

    try:
        request = QueryRequest(
            question=question,
            thread_id=thread_id,
            user_id=user_id,
            username=username,
            language=language or detect_language(question),
            channel=ChannelType(channel)
        )

        detected_language = request.language
        user_context = f"{username or user_id or 'anonymous'}"
        logger.info(f"📨 Processing question from {user_context}: {question[:100]}...")

        if detect_greeting(question):
            return _build_response(
                question=question,
                answer=get_greeting_response(detected_language),
                start_time=start_time,
                thread_id=request.thread_id,
                language=detected_language,
                response_type="greeting",
                success=True,
                greeting=True,
                user_id=user_id,
            )

        if detect_gratitude(question):
            return _build_response(
                question=question,
                answer=get_gratitude_response(detected_language),
                start_time=start_time,
                thread_id=request.thread_id,
                language=detected_language,
                response_type="gratitude",
                success=True,
                gratitude=True,
                user_id=user_id,
            )

        human_expression_result = detect_human_expression(question, detected_language)
        if human_expression_result:
            return _build_response(
                question=question,
                answer=human_expression_result['response'],
                start_time=start_time,
                thread_id=request.thread_id,
                language=detected_language,
                response_type="human_expression",
                success=True,
                user_id=user_id,
            )

        context = conversation_manager.get_or_create_context(request)
        entities = EntityExtractor.extract(question)

        initial_state = {
            "messages": [HumanMessage(content=question)],
            "current_question": question,
            "language": request.language,
            "is_greeting": False,
            "is_gratitude": False,
            "is_valid": None,
            "validation_reason": "",
            "retrieved_context": "",
            "sources": [],
            "analysis_result": "",
            "recommendations": [],
            "queue_data": {},
            "next_worker": "supervisor",
            "error": None,
            "db": effective_db,
            "user_id": user_id,
            "username": username,
            "start_time": start_time,
            "response_type": "initial",
            "entities": entities,
            "step_count": 0,
        }

        logger.info("🔄 Starting multi-agent graph execution...")
        final_state = await _graph_app.ainvoke(initial_state)

        response_type = final_state.get("response_type", "answer")
        conversation_manager.update_context(context, question, response_type, entities)

        if not final_state.get("is_valid"):
            return _build_response(
                question=question,
                answer=get_off_topic_response(language=request.language),
                start_time=start_time,
                thread_id=request.thread_id,
                language=request.language,
                response_type="off_topic",
                success=False,
                validated=False,
                user_id=user_id,
                error=final_state.get("validation_reason"),
            )

        if final_state.get("error"):
            return _build_response(
                question=question,
                answer=get_error_response(language=request.language),
                start_time=start_time,
                thread_id=request.thread_id,
                language=request.language,
                response_type="error",
                success=False,
                user_id=user_id,
                error=final_state.get("error"),
                attempts=len(final_state.get("messages", [])),
            )

        answer = final_state.get("analysis_result", get_no_data_response(language=request.language))
        answer = format_response_with_disclaimer(answer, language=request.language)
        answer = format_response_with_sources(answer, final_state.get("sources", []))


        logger.info(f"✅ Successfully processed question in {request.language}")

        return _build_response(
            question=question,
            answer=answer,
            start_time=start_time,
            thread_id=request.thread_id,
            language=request.language,
            response_type=final_state.get("response_type", "answer"),
            success=True,
            sources=final_state.get("sources", []),
            recommendations=final_state.get("recommendations", []),
            queue_info=final_state.get("queue_data", {}),
            user_id=user_id,
            attempts=len(final_state.get("messages", [])),
            groundedness=final_state.get("groundedness"),
        )

    except Exception as e:
        logger.error(f"❌ Multi-Agent Graph execution failed: {str(e)}")
        detected_language = detect_language(question) if question else "en"

        return _build_response(
            question=question,
            answer=get_error_response(language=detected_language),
            start_time=start_time,
            thread_id=thread_id or str(uuid.uuid4()),
            language=detected_language,
            response_type="error",
            success=False,
            user_id=user_id,
            error=str(e),
        )


async def get_agent_status(db=None) -> Dict[str, Any]:
    """Get comprehensive agent status."""
    rag_status = get_rag_status()

    question_count = 0
    questions = []
    file_paths = []

    if db is not None:
        try:
            question_count = await db.questions.count_documents({})
            cursor = db.questions.find({}).limit(5)
            questions = await cursor.to_list(length=5)
            file_paths = []
        except Exception as e:
            logger.error(f"Error getting question data: {e}")

    return {
        "initialized": _is_initialized,
        "graph_compiled": _graph_app is not None,
        "rag": rag_status,
        "question_queue": {
            "total": question_count,
            "questions": questions,
            "file_paths": file_paths
        },
        "metrics": conversation_manager.metrics.snapshot(),
        "mode": "Multi-Agent Business, Investment, Economy Advisor",
        "agents": {
            "supervisor": "Orchestrator - Routes requests to specialized workers",
            "greeting": "Greeting handler",
            "gratitude": "Social message handler",
            "guard": "Query validation and compliance",
            "rag": "Vector database retrieval",
            "queue": "Question backlog manager",
            "analyst": "LLM-based analysis and synthesis"
        },
        "features": {
            "multi_agent_routing": True,
            "greeting_detection": True,
            "gratitude_detection": True,
            "query_validation": True,
            "rag_retrieval": True,
            "queue_management": True,
            "llm_synthesis": True,
            "source_citation": True,
            "intelligent_recommendations": True,
            "conversation_context": True,
            "bilingual_support": True,
            "disclaimer": True
        },
        "conversation_contexts": len(conversation_manager.contexts)
    }

def reset_question_system(db=None) -> Dict[str, Any]:
    """Reset the question queue system."""
    effective_db = db if db is not None else _mongo_db

    try:
        count = reset_question_queue(db=effective_db) if effective_db is not None else 0
    except Exception as e:
        logger.warning(f"Reset error: {str(e)}")
        count = 0

    return {
        "status": "success",
        "message": f"Question queue reset with {count} questions",
        "file_paths": get_file_paths()
    }

def get_graph_app():
    """Get the compiled graph application."""
    if _graph_app is None:
        initialize_agent()
    return _graph_app

def get_conversation_summary(thread_id: str) -> Optional[Dict[str, Any]]:
    """Get conversation summary for a thread."""
    return conversation_manager.get_summary(thread_id)

def clear_old_conversations(max_age_hours: int = 24) -> int:
    """Clear old conversation contexts. (Now works — see FIX #1a/#3.)"""
    return conversation_manager.clear_old_contexts(max_age_hours)
