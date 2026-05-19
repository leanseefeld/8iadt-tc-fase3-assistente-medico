"""Configuração central da pipeline RAG local."""

from __future__ import annotations

# Chunking
CHUNK_STRATEGY = "semantic"
CHUNK_TOKENS = 400
CHUNK_OVERLAP_TOKENS = 50
CHARS_PER_TOKEN = 4
SEMANTIC_BREAKPOINT_PERCENTILE = 85
SEMANTIC_MAX_WORKERS = 6

# Embeddings
OLLAMA_BASE_URL = "http://127.0.0.1:11434"
OLLAMA_EMBED_MODEL = "nomic-embed-text"
CHROMA_COLLECTION_PCDT = "pcdt"
EMBED_ADD_BATCH_SIZE = 64

# Sidecars
CHUNK_JSONL_SUFFIX = ".chunks.jsonl"
