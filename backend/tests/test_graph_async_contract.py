import pytest

from assistente_medico_api.config import Settings
from assistente_medico_api.graph.chat_rag import build_compiled_chat_graph


class FakeStore:
    def similarity_search_with_score(self, _query, k=6):
        return []


@pytest.mark.asyncio
async def test_graph_invoke_fails_when_async_node_present():
    graph = build_compiled_chat_graph(FakeStore(), Settings())
    initial = {
        "query": "teste",
        "patient_id": "p1",
        "retrieved_docs": [],
        "sources": [],
        "reasoning_steps": [],
        "answer": "",
    }
    with pytest.raises(TypeError):
        graph.invoke(initial)

