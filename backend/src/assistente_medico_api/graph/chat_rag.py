"""Compila o grafo linear de recuperação → geração."""

from __future__ import annotations

from langchain_chroma import Chroma
from langgraph.graph import END, StateGraph

from assistente_medico_api.config import Settings
from assistente_medico_api.graph.nodes.generate import generate_node
from assistente_medico_api.graph.nodes.guardrail import guardrail_node
from assistente_medico_api.graph.nodes.patient_context import load_patient_context_node
from assistente_medico_api.graph.nodes.retrieve import retrieve_node
from assistente_medico_api.graph.nodes.rewrite import rewrite_query_node
from assistente_medico_api.graph.state import ChatRAGState


def build_compiled_chat_graph(store: Chroma, settings: Settings, checkpointer=None):
    """
    Monta o StateGraph com nós que operam com store/settings.

    Ambos os caminhos (JSON e SSE) usam o mesmo grafo compilado:
    - JSON: graph.ainvoke()
    - SSE:  graph.astream_events() → emite on_chat_model_stream por token.
    """

    def _retrieve(state: ChatRAGState) -> dict:
        return retrieve_node(state, store=store, settings=settings)

    async def _load_patient_context(state: ChatRAGState) -> dict:
        return await load_patient_context_node(state, settings)

    async def _rewrite(state: ChatRAGState) -> dict:
        return await rewrite_query_node(state, settings)

    async def _generate(state: ChatRAGState) -> dict:
        return await generate_node(state, settings)

    async def _guardrail(state: ChatRAGState) -> dict:
        return await guardrail_node(state, settings)

    workflow = StateGraph(ChatRAGState)
    workflow.add_node("load_patient_context", _load_patient_context)
    workflow.add_node("rewrite", _rewrite)
    workflow.add_node("retrieve", _retrieve)
    workflow.add_node("generate", _generate)
    workflow.add_node("guardrail", _guardrail)
    workflow.set_entry_point("load_patient_context")
    workflow.add_edge("load_patient_context", "rewrite")
    workflow.add_edge("rewrite", "retrieve")
    workflow.add_edge("retrieve", "generate")
    workflow.add_edge("generate", "guardrail")
    workflow.add_edge("guardrail", END)

    compiled = workflow.compile(checkpointer=checkpointer)

    print(compiled.get_graph().draw_ascii())

    return compiled
