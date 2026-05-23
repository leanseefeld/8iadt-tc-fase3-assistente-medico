"""Aplicação FastAPI: CORS, lifespan (Chroma + grafo) e routers."""

from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from langgraph.checkpoint.memory import MemorySaver

from assistente_medico_api.api.alerts import router as alerts_router
from assistente_medico_api.api.chat import router as chat_router
from assistente_medico_api.api.cids import router as cids_router
from assistente_medico_api.api.comorbidities import router as comorbidities_router
from assistente_medico_api.api.medications import router as medications_router
from assistente_medico_api.api.patients import router as patients_router
from assistente_medico_api.api.prescriptions import router as prescriptions_router
from assistente_medico_api.config import Settings, resolve_chroma_persist_dir
from assistente_medico_api.graph.chat_rag import build_compiled_chat_graph
from assistente_medico_api.observability.audit import audit
from assistente_medico_api.observability.logging_setup import configure_logging
from assistente_medico_api.observability.middleware import RequestContextMiddleware


configure_logging(Settings())

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Abre Chroma e compila o LangGraph uma vez por processo."""
    settings = Settings()
    # Import tardio: depende do pacote llm instalado.
    from pcdt_ingest.embed import build_ollama_embeddings, open_chroma_vectorstore

    chroma_path = resolve_chroma_persist_dir(settings)
    embeddings = build_ollama_embeddings(
        model=settings.ollama_embed_model,
        base_url=settings.ollama_base_url,
    )
    store = open_chroma_vectorstore(
        persist_directory=chroma_path,
        embedding_function=embeddings,
        collection_name=settings.chroma_collection,
    )
    try:
        chroma_count = int(store._collection.count())  # type: ignore[attr-defined]
    except Exception:
        chroma_count = None
    try:
        from pcdt_ingest.paths import data_root
        from pcdt_ingest.reference_data.conitec_catalog import DEFAULT_CATALOG_RELATIVE_PATH

        catalog_path = data_root() / DEFAULT_CATALOG_RELATIVE_PATH
    except Exception:
        catalog_path = None
    audit(
        "rag_backend_startup",
        kind="rag",
        chroma_persist_dir=str(chroma_path),
        chroma_collection=settings.chroma_collection,
        chroma_document_count=chroma_count,
        ollama_base_url=settings.ollama_base_url,
        ollama_embed_model=settings.ollama_embed_model,
        ollama_chat_model=settings.ollama_chat_model,
        conitec_catalog_path=str(catalog_path) if catalog_path else "",
        conitec_catalog_exists=bool(catalog_path and catalog_path.is_file()),
    )
    app.state.settings = settings
    app.state.chroma_store = store
    app.state.chat_checkpointer = MemorySaver()
    app.state.chat_graph = build_compiled_chat_graph(
        store, settings, app.state.chat_checkpointer
    )

    yield

    app.state.chroma_store = None
    app.state.chat_graph = None
    app.state.chat_checkpointer = None
    app.state.settings = None


def create_app() -> FastAPI:
    """Factory para testes e uvicorn."""
    app = FastAPI(
        title="Assistente Médico API",
        version="0.1.0",
        lifespan=lifespan,
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    # Deve ficar como último `add_middleware` para ser a camada externa mais próxima do ASGI,
    # capturando toda latência até a resposta.
    app.add_middleware(RequestContextMiddleware)
    app.include_router(chat_router, prefix="/api")
    app.include_router(comorbidities_router, prefix="/api")
    app.include_router(cids_router, prefix="/api")
    app.include_router(medications_router, prefix="/api")
    app.include_router(patients_router, prefix="/api")
    app.include_router(alerts_router, prefix="/api")
    app.include_router(prescriptions_router, prefix="/api")
    return app


app = create_app()
