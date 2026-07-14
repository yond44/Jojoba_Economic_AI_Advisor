"""Compile the multi-agent LangGraph."""
from langgraph.graph import StateGraph, END

from src.services.agent.state import AgentState
from src.services.agent.nodes import (
    supervisor_node, greeting_node, gratitude_node, guard_node,
    rag_node, queue_node, analyst_node, router_edge,
)


def build_economic_advisor_graph():
    """Build and compile the multi-agent LangGraph."""
    workflow = StateGraph(AgentState)

    workflow.add_node("supervisor", supervisor_node)
    workflow.add_node("greeting", greeting_node)
    workflow.add_node("gratitude", gratitude_node)
    workflow.add_node("guard", guard_node)
    workflow.add_node("rag", rag_node)
    workflow.add_node("queue", queue_node)
    workflow.add_node("analyst", analyst_node)

    workflow.set_entry_point("supervisor")

    workflow.add_conditional_edges(
        "supervisor",
        router_edge,
        {
            "greeting": "greeting",
            "gratitude": "gratitude",
            "guard": "guard",
            "rag": "rag",
            "queue": "queue",
            "analyst": "analyst",
            "__end__": END
        }
    )

    workflow.add_edge("greeting", "supervisor")
    workflow.add_edge("gratitude", "supervisor")
    workflow.add_edge("guard", "supervisor")
    workflow.add_edge("rag", "supervisor")
    workflow.add_edge("queue", "supervisor")
    workflow.add_edge("analyst", "supervisor")

    return workflow.compile()
