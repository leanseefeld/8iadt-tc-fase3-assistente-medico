"""Aplicação FastAPI: CORS, lifespan (Chroma + grafo) e routers."""

from __future__ import annotations

from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from assistente_medico_api.api.alerts import router as alerts_router
from assistente_medico_api.api.cids import router as cids_router
from assistente_medico_api.api.chat import router as chat_router
from assistente_medico_api.api.comorbidities import router as comorbidities_router
from assistente_medico_api.api.patients import router as patients_router
from assistente_medico_api.config import Settings
from assistente_medico_api.graph.chat_rag import build_compiled_chat_graph

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Abre Chroma e compila o LangGraph uma vez por processo."""
    settings = Settings()
    # Import tardio: depende do pacote llm instalado.
    from pcdt_ingest.embed import build_ollama_embeddings, open_chroma_vectorstore
    from pcdt_ingest.paths import vectorstore_chroma_dir

    chroma_path = settings.chroma_persist_dir or vectorstore_chroma_dir()
    embeddings = build_ollama_embeddings(
        model=settings.ollama_embed_model,
        base_url=settings.ollama_base_url,
    )
    store = open_chroma_vectorstore(
        persist_directory=chroma_path,
        embedding_function=embeddings,
        collection_name=settings.chroma_collection,
    )
    app.state.settings = settings
    app.state.chroma_store = store
    app.state.chat_graph = build_compiled_chat_graph(store, settings)

    yield

    app.state.chroma_store = None
    app.state.chat_graph = None
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
    app.include_router(chat_router, prefix="/api")
    app.include_router(comorbidities_router, prefix="/api")
    app.include_router(cids_router, prefix="/api")
    app.include_router(patients_router, prefix="/api")
    app.include_router(alerts_router, prefix="/api")
    return app


app = create_app()
