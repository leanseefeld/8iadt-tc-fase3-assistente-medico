"""Configuração carregada de variáveis de ambiente."""

from __future__ import annotations

from pathlib import Path

from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy.engine import make_url

REPO_ROOT = Path(__file__).resolve().parents[3]
BACKEND_ROOT = REPO_ROOT / "backend"


class Settings(BaseSettings):
    """Parâmetros de tempo de execução (prefixo MEDICO_)."""

    model_config = SettingsConfigDict(
        env_prefix="MEDICO_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        populate_by_name=True,
    )

    ollama_base_url: str = "http://127.0.0.1:11434"
    ollama_embed_model: str = "nomic-embed-text"
    ollama_chat_model: str = "llama3.2:3b"
    chroma_persist_dir: Path | None = Field(
        default=None,
        description="Se None, usa vectorstore/chroma na raiz do repositório (via pcdt_ingest.paths).",
    )
    chroma_collection: str = "pcdt"
    retrieval_k: int = 6
    rag_retrieve_candidates_k: int = Field(
        default=30,
        validation_alias=AliasChoices("MEDICO_RAG_RETRIEVE_CANDIDATES_K", "RAG_RETRIEVE_CANDIDATES_K"),
        description="Número inicial de candidatos recuperados antes do reranking.",
    )
    rag_retrieve_final_k: int = Field(
        default=6,
        validation_alias=AliasChoices("MEDICO_RAG_RETRIEVE_FINAL_K", "RAG_RETRIEVE_FINAL_K"),
        description="Número final de documentos enviados ao prompt após reranking.",
    )
    rag_audit_jsonl: Path = Field(
        default=Path("../llm/data/audit/rag_interactions.jsonl"),
        validation_alias=AliasChoices("MEDICO_RAG_AUDIT_JSONL", "RAG_AUDIT_JSONL"),
        description="Arquivo JSONL local para auditoria das interações RAG.",
    )
    rag_audit_enabled: bool = Field(
        default=True,
        validation_alias=AliasChoices("MEDICO_RAG_AUDIT_ENABLED", "RAG_AUDIT_ENABLED"),
        description="Ativa escrita de auditoria RAG em JSONL.",
    )
    rag_use_cross_encoder_rerank: bool = Field(
        default=False,
        validation_alias=AliasChoices("MEDICO_RAG_USE_CROSS_ENCODER_RERANK", "RAG_USE_CROSS_ENCODER_RERANK"),
        description="Ativa reranking opcional com CrossEncoder após o rerank heurístico.",
    )
    rag_cross_encoder_model: str = Field(
        default="cross-encoder/ms-marco-MiniLM-L-6-v2",
        validation_alias=AliasChoices("MEDICO_RAG_CROSS_ENCODER_MODEL", "RAG_CROSS_ENCODER_MODEL"),
        description="Modelo sentence-transformers CrossEncoder usado quando o rerank opcional está ativo.",
    )
    rag_cross_encoder_top_n: int = Field(
        default=15,
        validation_alias=AliasChoices("MEDICO_RAG_CROSS_ENCODER_TOP_N", "RAG_CROSS_ENCODER_TOP_N"),
        description="Número de documentos do ranking heurístico enviados ao CrossEncoder.",
    )
    rag_min_final_score: float = Field(
        default=-5.0,
        validation_alias=AliasChoices("MEDICO_RAG_MIN_FINAL_SCORE", "RAG_MIN_FINAL_SCORE"),
        description="Score final mínimo para retornar um documento ao prompt.",
    )
    rag_require_catalog_match_when_confident: bool = Field(
        default=True,
        validation_alias=AliasChoices(
            "MEDICO_RAG_REQUIRE_CATALOG_MATCH_WHEN_CONFIDENT",
            "RAG_REQUIRE_CATALOG_MATCH_WHEN_CONFIDENT",
        ),
        description="Quando houver candidato de catálogo confiável, retorna apenas documentos compatíveis.",
    )
    rag_min_final_score_with_catalog: float = Field(
        default=0.0,
        validation_alias=AliasChoices("MEDICO_RAG_MIN_FINAL_SCORE_WITH_CATALOG", "RAG_MIN_FINAL_SCORE_WITH_CATALOG"),
        description="Score mínimo aplicado quando há candidato de catálogo confiável.",
    )
    rag_use_llm_rerank: bool = Field(
        default=False,
        validation_alias=AliasChoices("MEDICO_RAG_USE_LLM_RERANK", "RAG_USE_LLM_RERANK"),
        description="Ativa reranking/validação por LLM com fallback heurístico determinístico.",
    )
    rag_llm_rerank_top_n: int = Field(
        default=12,
        validation_alias=AliasChoices("MEDICO_RAG_LLM_RERANK_TOP_N", "RAG_LLM_RERANK_TOP_N"),
        description="Número máximo de candidatos enviados ao LLM reranker.",
    )
    rag_pipeline_version: str = Field(
        default="separated_nodes_v2",
        validation_alias=AliasChoices("MEDICO_RAG_PIPELINE_VERSION", "RAG_PIPELINE_VERSION"),
        description="Versão lógica do pipeline RAG auditada em cada interação.",
    )
    rag_max_retrieve_attempts: int = Field(
        default=2,
        validation_alias=AliasChoices("MEDICO_RAG_MAX_RETRIEVE_ATTEMPTS", "RAG_MAX_RETRIEVE_ATTEMPTS"),
        description="Máximo de buscas Chroma por pergunta (busca inicial + fallback).",
    )
    rag_require_source_for_clinical_answer: bool = Field(
        default=True,
        validation_alias=AliasChoices(
            "MEDICO_RAG_REQUIRE_SOURCE_FOR_CLINICAL_ANSWER",
            "RAG_REQUIRE_SOURCE_FOR_CLINICAL_ANSWER",
        ),
        description="Exige contexto/fonte validada para resposta clínica grounded.",
    )
    rag_debug: bool = Field(
        default=False,
        validation_alias=AliasChoices("MEDICO_RAG_DEBUG", "RAG_DEBUG"),
        description="Expõe diagnóstico RAG adicional em rotas/inspector quando habilitado.",
    )
    enable_medical_nlp: bool = Field(
        default=True,
        validation_alias=AliasChoices("MEDICO_ENABLE_MEDICAL_NLP", "ENABLE_MEDICAL_NLP"),
        description="Ativa resolvedores NLP médicos opcionais no rewrite; catálogo Conitec permanece ativo quando falso.",
    )
    use_medspacy: bool = Field(
        default=False,
        validation_alias=AliasChoices("MEDICO_USE_MEDSPACY", "USE_MEDSPACY"),
        description="Ativa medSpaCy/PyRuSH no resolvedor clínico. Desligado por padrão para evitar travamentos locais.",
    )
    medspacy_model: str = Field(
        default="pt_core_news_sm",
        validation_alias=AliasChoices("MEDICO_MEDSPACY_MODEL", "MEDSPACY_MODEL"),
        description="Modelo spaCy usado pelo medSpaCy quando MEDICO_USE_MEDSPACY=true.",
    )
    medspacy_language_code: str = Field(
        default="pt",
        validation_alias=AliasChoices("MEDICO_MEDSPACY_LANGUAGE_CODE", "MEDSPACY_LANGUAGE_CODE"),
        description="Código de idioma passado ao medSpaCy.",
    )
    use_spacy: bool = Field(
        default=True,
        validation_alias=AliasChoices("MEDICO_USE_SPACY", "USE_SPACY"),
        description="Ativa spaCy NER leve no resolvedor clínico quando modelo local existir.",
    )
    spacy_model: str = Field(
        default="pt_core_news_sm",
        validation_alias=AliasChoices("MEDICO_SPACY_MODEL", "SPACY_MODEL"),
        description="Modelo spaCy local para NER leve quando MEDICO_USE_SPACY=true.",
    )
    database_url: str = "sqlite+aiosqlite:///./assistente_medico.db"
    uploads_dir: Path = Field(
        default=Path("./uploads"),
        description="Diretório para uploads manuais de exames.",
    )
    llm_stream_timeout_s: float = Field(
        default=120.0,
        description="Timeout (segundos) para o streaming do nó de geração via Ollama.",
    )
    log_dir: Path = Field(
        default=Path("./logs"),
        description="Diretório para arquivo rotativo JSONL de auditoria (relativo ao repositório se não absoluto).",
    )
    log_level: str = Field(
        default="INFO",
        description="Nível de log efetivo (ex.: INFO, DEBUG) para pacote assistente_medico.*.",
    )

def resolve_runtime_path(path: Path) -> Path:
    """Resolve paths relativos da configuração a partir da raiz do repositório."""
    return path if path.is_absolute() else REPO_ROOT / path


def resolve_database_url(settings: Settings) -> str:
    """Resolve SQLite file URLs relative to backend/, independent of cwd."""
    url = make_url(settings.database_url)
    if not url.get_backend_name().startswith("sqlite"):
        return settings.database_url
    if url.database in (None, "", ":memory:"):
        return settings.database_url

    database_path = Path(url.database)
    if database_path.is_absolute():
        return settings.database_url

    resolved_path = BACKEND_ROOT / database_path
    return url.set(database=str(resolved_path)).render_as_string(hide_password=False)


def resolve_chroma_persist_dir(settings: Settings) -> Path:
    """Retorna o diretório Chroma efetivo usado pelo backend."""
    if settings.chroma_persist_dir is not None:
        return resolve_runtime_path(settings.chroma_persist_dir)

    from pcdt_ingest.paths import vectorstore_chroma_dir

    return vectorstore_chroma_dir()
