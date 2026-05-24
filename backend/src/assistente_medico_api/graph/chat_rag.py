"""Compila o grafo RAG do chat médico com roteamento e fallback controlado."""

from __future__ import annotations

from langchain_chroma import Chroma
from langgraph.graph import END, StateGraph

from assistente_medico_api.config import Settings
from assistente_medico_api.graph.nodes.generate import (
    generate_direct_answer_node,
    generate_grounded_answer_node,
    generate_insufficient_context_node,
)
from assistente_medico_api.graph.nodes.guardrail import guardrail_node
from assistente_medico_api.graph.nodes.pipeline import (
    context_quality_router,
    fallback_retrieve_node,
    load_memory_node,
    rerank_and_validate_context_node,
    retrieve_attempt_1_node,
    route_search_needed,
    router_search_needed_node,
    save_memory_node,
)
from assistente_medico_api.graph.nodes.rewrite import rewrite_query_node
from assistente_medico_api.graph.state import ChatRAGState


def build_compiled_chat_graph(store: Chroma, settings: Settings, checkpointer=None):
    """
    Fluxo:
    memory -> router -> direct|rag -> rewrite -> retrieve -> rerank -> quality route
    with at most one fallback retrieve before insufficiency generation.
    """

    def _load_memory(state: ChatRAGState) -> dict:
        return load_memory_node(state)

    def _router(state: ChatRAGState) -> dict:
        return router_search_needed_node(state, settings=settings)

    async def _rewrite(state: ChatRAGState) -> dict:
        return await rewrite_query_node(state, settings)

    def _retrieve_attempt_1(state: ChatRAGState) -> dict:
        return retrieve_attempt_1_node(state, store=store, settings=settings)

    async def _rerank(state: ChatRAGState) -> dict:
        return await rerank_and_validate_context_node(state, settings=settings)

    def _fallback_retrieve(state: ChatRAGState) -> dict:
        return fallback_retrieve_node(state, store=store, settings=settings)

    async def _generate_grounded(state: ChatRAGState) -> dict:
        return await generate_grounded_answer_node(state, settings)

    async def _generate_insufficient(state: ChatRAGState) -> dict:
        return await generate_insufficient_context_node(state, settings)

    async def _generate_direct(state: ChatRAGState) -> dict:
        return await generate_direct_answer_node(state, settings)

    async def _guardrail(state: ChatRAGState) -> dict:
        return await guardrail_node(state, settings)

    def _save_memory(state: ChatRAGState) -> dict:
        return save_memory_node(state, settings=settings)

    workflow = StateGraph(ChatRAGState)
    workflow.add_node("load_memory", _load_memory)
    workflow.add_node("router_search_needed", _router)
    workflow.add_node("rewrite_query", _rewrite)
    workflow.add_node("retrieve_attempt_1", _retrieve_attempt_1)
    workflow.add_node("rerank_and_validate_context", _rerank)
    workflow.add_node("fallback_retrieve_attempt_2", _fallback_retrieve)
    workflow.add_node("generate_grounded_answer", _generate_grounded)
    workflow.add_node("generate_insufficient_context", _generate_insufficient)
    workflow.add_node("generate_direct_answer", _generate_direct)
    workflow.add_node("guardrail", _guardrail)
    workflow.add_node("save_memory", _save_memory)

    workflow.set_entry_point("load_memory")
    workflow.add_edge("load_memory", "router_search_needed")
    workflow.add_conditional_edges(
        "router_search_needed",
        route_search_needed,
        {
            "direct": "generate_direct_answer",
            "rag": "rewrite_query",
        },
    )
    workflow.add_edge("rewrite_query", "retrieve_attempt_1")
    workflow.add_edge("retrieve_attempt_1", "rerank_and_validate_context")
    workflow.add_conditional_edges(
        "rerank_and_validate_context",
        context_quality_router,
        {
            "generate_grounded": "generate_grounded_answer",
            "fallback_retrieve": "fallback_retrieve_attempt_2",
            "generate_insufficient": "generate_insufficient_context",
        },
    )
    workflow.add_edge("fallback_retrieve_attempt_2", "rerank_and_validate_context")
    workflow.add_edge("generate_grounded_answer", "guardrail")
    workflow.add_edge("generate_insufficient_context", "guardrail")
    workflow.add_edge("generate_direct_answer", "guardrail")
    workflow.add_edge("guardrail", "save_memory")
    workflow.add_edge("save_memory", END)

    compiled = workflow.compile(checkpointer=checkpointer)
    print(compiled.get_graph().draw_ascii())
    return compiled
