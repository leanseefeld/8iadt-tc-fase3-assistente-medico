"""Compila o grafo linear de recuperação → geração."""

from __future__ import annotations

from langchain_chroma import Chroma
from langgraph.graph import END, StateGraph

from assistente_medico_api.config import Settings
from assistente_medico_api.graph.nodes.generate import generate_node
from assistente_medico_api.graph.nodes.retrieve import retrieve_node
from assistente_medico_api.graph.state import ChatRAGState


def build_compiled_chat_graph(store: Chroma, settings: Settings):
    """
    Monta o StateGraph com nós que operam com store/settings.

    Ambos os caminhos (JSON e SSE) usam o mesmo grafo compilado:
    - JSON: graph.ainvoke()
    - SSE:  graph.astream_events() → emite on_chat_model_stream por token.
    """

    def _retrieve(state: ChatRAGState) -> dict:
        return retrieve_node(state, store=store, settings=settings)

    async def _generate(state: ChatRAGState) -> dict:
        return await generate_node(state, settings)

    workflow = StateGraph(ChatRAGState)
    workflow.add_node("retrieve", _retrieve)
    workflow.add_node("generate", _generate)
    workflow.set_entry_point("retrieve")
    workflow.add_edge("retrieve", "generate")
    workflow.add_edge("generate", END)

    compiled = workflow.compile()

    print(compiled.get_graph().draw_ascii())

    return compiled
