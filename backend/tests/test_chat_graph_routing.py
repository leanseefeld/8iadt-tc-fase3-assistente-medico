"""Testes do roteamento entre busca nova, RAG legado e resposta direta."""

from assistente_medico_api.config import Settings
from assistente_medico_api.graph.search import decide_search_route


def test_route_direct_when_no_search():
    assert decide_search_route({"search_needed": False}, Settings()) == "direct"


def test_route_new_when_flag_enabled():
    settings = Settings(rag_multi_query_enabled=True)
    assert decide_search_route({"search_needed": True}, settings) == "new"


def test_route_legacy_when_flag_disabled():
    settings = Settings(rag_multi_query_enabled=False)
    assert decide_search_route({"search_needed": True}, settings) == "legacy"
