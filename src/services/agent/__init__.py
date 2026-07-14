"""
Modular agent package (was the 1,850-line src/services/agent.py monolith).
Public API preserved — every `from src.services.agent import ...` still works.
"""
from src.services.agent.models import (
    ChannelType, QueryRequest, QueryResponse, BatchEmailRequest, ConversationContext,
)
from src.services.agent.state import AgentState, EntityExtractor
from src.services.agent.conversation import (
    conversation_manager, ConversationManager, AgentMetrics,
)
from src.services.agent.graph import build_economic_advisor_graph
from src.services.agent.runtime import (
    ask_agent, initialize_agent, get_agent_status, reset_question_system,
    get_graph_app, get_conversation_summary, clear_old_conversations,
)
from src.services.agent.email_processor import BatchEmailProcessor, batch_processor

__all__ = [
    "ask_agent", "initialize_agent", "get_agent_status", "batch_processor",
    "BatchEmailProcessor", "reset_question_system", "get_graph_app",
    "get_conversation_summary", "clear_old_conversations", "conversation_manager",
    "ConversationManager", "AgentMetrics", "build_economic_advisor_graph",
    "AgentState", "EntityExtractor", "ChannelType", "QueryRequest",
    "QueryResponse", "BatchEmailRequest", "ConversationContext",
]
