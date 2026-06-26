"""Subgrafo compilado de busca especializada (plan_queries → search).

Isolado do RAG legado e plugado ao grafo principal por flag. Para remover o
caminho legado no futuro, basta deletar os nós legados e a branch ``legacy``
do roteamento — este subpacote é autossuficiente.
"""

from __future__ import annotations

from langchain_chroma import Chroma
from langgraph.graph import END, StateGraph

from assistente_medico_api.config import Settings
from assistente_medico_api.graph.search.nodes import plan_queries_node, search_node
from assistente_medico_api.graph.state import ChatRAGState


def build_specialized_search_graph(store: Chroma, settings: Settings):
    """Compila o subgrafo de busca (2 nós) para ser usado como nó do grafo principal."""

    async def _plan(state: ChatRAGState) -> dict:
        return await plan_queries_node(state, settings)

    def _search(state: ChatRAGState) -> dict:
        return search_node(state, store=store, settings=settings)

    workflow = StateGraph(ChatRAGState)
    workflow.add_node("plan_queries", _plan)
    workflow.add_node("search", _search)
    workflow.set_entry_point("plan_queries")
    workflow.add_edge("plan_queries", "search")
    workflow.add_edge("search", END)
    return workflow.compile()


def decide_search_route(state: ChatRAGState, settings: Settings) -> str:
    """Roteia após o router: resposta direta, busca nova ou fluxo RAG legado."""
    if not state.get("search_needed"):
        return "direct"
    return "new" if getattr(settings, "rag_multi_query_enabled", True) else "legacy"
