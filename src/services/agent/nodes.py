"""LangGraph agent nodes (supervisor, guard, greeting, gratitude, rag, queue,
analyst) + the router edge. rag_node calls the upgraded, cached query_rag."""
import logging
import threading
import asyncio
from typing import Dict, Any, Optional, List, Literal

from langchain_core.messages import BaseMessage, AIMessage, HumanMessage
from langchain_groq import ChatGroq
from langgraph.graph import END

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

from src.services.agent.state import AgentState, EntityExtractor
from src.services.agent.models import ConversationContext
from src.services.agent.conversation import conversation_manager
from src.services.agent.config import MAX_AGENT_STEPS
from src.services.agent.util import _utcnow

logger = logging.getLogger(__name__)

_llm = None
_llm_lock = threading.Lock()


def supervisor_node(state: AgentState) -> Dict[str, Any]:
    """
    Agent #1: The Orchestrator / Router.
    Analyzes current state and directs execution to specialized workers.
    """
    logger.info(f"--- SUPERVISOR AGENT (User: {state.get('username', 'anonymous')}) ---")

    steps = state.get("step_count", 0) + 1
    if steps > MAX_AGENT_STEPS:
        logger.error(f"❌ Supervisor exceeded {MAX_AGENT_STEPS} steps — "
                     f"breaking potential loop. State keys that never "
                     f"settled should be investigated.")
        return {
            "next_worker": "end",
            "step_count": steps,
            "error": f"Agent loop exceeded {MAX_AGENT_STEPS} steps",
            "response_type": "error",
        }

    if state.get("is_greeting"):
        return {"next_worker": "end", "step_count": steps}
    if state.get("is_gratitude"):
        return {"next_worker": "end", "step_count": steps}

    if state.get("is_valid") is None:
        return {"next_worker": "guard", "step_count": steps}

    if not state.get("is_valid"):
        return {"next_worker": "end", "step_count": steps}

    if "queue" in state["current_question"].lower() and not state.get("queue_data"):
        return {"next_worker": "queue", "step_count": steps}

    if not state.get("retrieved_context"):
        return {"next_worker": "rag", "step_count": steps}

    if not state.get("analysis_result"):
        return {"next_worker": "analyst", "step_count": steps}

    return {"next_worker": "end", "step_count": steps}

def greeting_node(state: AgentState) -> Dict[str, Any]:
    """Agent #1.5: Handles greeting messages (defense-in-depth path)."""
    logger.info("--- GREETING AGENT ---")
    question = state["current_question"]
    language = state.get("language", "en")

    if detect_greeting(question):
        fallback = get_fallback_response(question, language=language)
        response = fallback if fallback else get_greeting_response(language=language)
        return {
            "is_greeting": True,
            "analysis_result": response,
            "response_type": "greeting",
            "messages": [AIMessage(content="Greeting Agent: Greeting message detected and handled.")]
        }

    return {
        "is_greeting": False,
        "messages": [AIMessage(content="Greeting Agent: Not a greeting message.")]
    }

def gratitude_node(state: AgentState) -> Dict[str, Any]:
    """Agent #2: Handles gratitude and social messages (defense-in-depth path)."""
    logger.info("--- GRATITUDE AGENT ---")
    question = state["current_question"]
    language = state.get("language", "en")

    if detect_gratitude(question):
        fallback = get_fallback_response(question, language=language)
        response = fallback if fallback else get_gratitude_response(language=language)
        return {
            "is_gratitude": True,
            "analysis_result": response,
            "response_type": "gratitude",
            "messages": [AIMessage(content="Gratitude Agent: Social message detected and handled.")]
        }

    return {
        "is_gratitude": False,
        "messages": [AIMessage(content="Gratitude Agent: Not a social message.")]
    }

def guard_node(state: AgentState) -> Dict[str, Any]:
    """Agent #3: Evaluates compliance, safety, and domain alignment."""
    logger.info("--- GUARDRAIL AGENT ---")
    validation = validate_query(state["current_question"])
    return {
        "is_valid": validation["allowed"],
        "validation_reason": validation.get("reason", ""),
        "response_type": "validation",
        "messages": [AIMessage(content=f"Guardrail Check Completed. Allowed: {validation['allowed']}")]
    }

async def rag_node(state: AgentState) -> Dict[str, Any]:
    """Agent #4: RAG data retrieval agent."""
    logger.info("--- RAG DATA AGENT ---")

    language = state.get("language", "en")
    bucket_key = state.get("user_id") or state.get("username") or "anon"

    result = await query_rag(
        state["current_question"],
        language=language,
        history=None,
        bucket_key=bucket_key,
    )

    context = ""
    sources = []

    if result.get("success"):
        sources = result.get("sources", [])
        for s in sources[:3]:
            context += s.get("text", "") + "\n\n"
        cache_status = "💾 CACHED" if result.get("from_cache") else "🔄 FRESH"
        logger.info(
            f"{cache_status} - {len(sources)} sources - "
            f"prompt={result.get('prompt_version','?')}"
        )

    if not context:
        context = "No relevant context found"

    answer = result.get("answer") if result.get("success") else None

    if not answer or not str(answer).strip():
        return {
            "retrieved_context": context,
            "sources": sources,
            "messages": [AIMessage(content=f"RAG found {len(sources)} chunks (no answer)")],
        }

    recommendations_text = IntelligentRecommender.generate_recommendations(
        state["current_question"], user_level="beginner", language=language
    )
    recommendations = [
        line.strip("• ").strip()
        for line in (recommendations_text or "").split("\n")
        if line.strip("• ")
    ]

    return {
        "retrieved_context": context,
        "sources": sources,
        "analysis_result": answer,
        "recommendations": recommendations,
        "groundedness": result.get("groundedness"),
        "prompt_version": result.get("prompt_version", "v1"),
        "response_type": "analysis",
        "messages": [AIMessage(content=f"RAG answered from {len(sources)} chunks")],
    }

def queue_node(state: AgentState) -> Dict[str, Any]:
    """Agent #5: Question queue manager agent."""
    logger.info("--- QUEUE MANAGER AGENT ---")

    db = state.get("db")

    try:
        count = get_question_count(db=db) if db is not None else 0
        next_q = get_next_question(db=db) if db is not None else None
        all_q = get_all_questions(db=db)[:5] if db is not None else []
    except Exception as e:
        logger.warning(f"Queue fetch error: {str(e)}")
        count, next_q, all_q = 0, None, []

    data = {
        "total_backlog": count,
        "next_up": next_q,
        "sample_queue": all_q
    }

    return {
        "queue_data": data,
        "messages": [AIMessage(content=f"Queue Agent: Synced pipeline. Remaining backlog: {count}")]
    }

def _get_llm():
    global _llm
    if _llm is None:
        with _llm_lock:
            if _llm is None:
                _llm = setup_llm()
                logger.info("🔌 LLM client created (cached for reuse)")
    return _llm

def analyst_node(state: AgentState) -> Dict[str, Any]:
    """Agent #6: Financial analyst using LLM synthesis."""
    logger.info("--- FINANCIAL ANALYST AGENT ---")

    context = state.get("retrieved_context", "")
    question = state["current_question"]
    language = state.get("language", "en")

    try:
        llm = _get_llm()

        prompt = SYSTEM_PROMPT.format(
            context=context or "No specific data found.",
            question=question
        )

        try:
            response = llm.complete(prompt)
            answer = str(response)
        except AttributeError:
            try:
                from llama_index.core.llms import ChatMessage
                messages = [ChatMessage(role="user", content=prompt)]
                response = llm.chat(messages)
                answer = response.message.content
            except Exception as e:
                logger.warning(f"LLM call failed: {str(e)}")
                answer = get_no_data_response(language=language)

        if not answer or not answer.strip():
            logger.warning("⚠️ LLM returned empty answer — using fallback")
            answer = get_no_data_response(language=language)

        recommendations_text = IntelligentRecommender.generate_recommendations(
            question,
            user_level="beginner",
            language=language
        )

        recommendations = []
        if recommendations_text:
            recommendations = [line.strip("• ").strip()
                               for line in recommendations_text.split("\n")
                               if line.strip("• ")]

        return {
            "analysis_result": answer,
            "recommendations": recommendations,
            "response_type": "analysis",
            "messages": [AIMessage(content="Analyst Agent: Business interpretation generation complete.")]
        }
    except Exception as e:
        logger.error(f"Analyst node error: {str(e)}")
        return {
            "analysis_result": get_no_data_response(language=state.get("language", "en")),
            "error": str(e),
            "response_type": "error",
            "messages": [AIMessage(content=f"Analyst Agent Error: {str(e)}")]
        }

def router_edge(state: AgentState) -> Literal["greeting", "gratitude", "guard", "rag", "queue", "analyst", "__end__"]:
    """Reads state calculations from Supervisor to decide the next node."""
    decision = state.get("next_worker", "end")

    if state.get("is_greeting"):
        return "greeting"
    if state.get("is_gratitude"):
        return "gratitude"
    if decision == "end":
        return END
    return decision
