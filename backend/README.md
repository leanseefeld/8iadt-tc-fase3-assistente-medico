# API do Assistente Médico (FastAPI)

Serviço HTTP em FastAPI: orquestração LangGraph para **chat com RAG** sobre PCDTs indexados no Chroma (`vectorstore/chroma` na raiz do repositório). Modelo de chat padrão: **Ollama** `gemma4:e4b-it-q4_K_M`; embeddings de consulta: **mesmo** modelo usado na ingestão (`nomic-embed-text`), servido pelo Ollama.

## Pré-requisitos

1. Python **≥ 3.11** e ambiente virtual (ex.: `.venv` na raiz do monorepo).
2. Pacote da pipeline instalado (fornece `pcdt_ingest`):
  ```bash
   pip install -e llm/
  ```
3. **Ollama** em execução com `nomic-embed-text` e `gemma4:e4b-it-q4_K_M` (ou ajuste `MEDICO_OLLAMA_`*).
4. Vector store populado (a partir da raiz do repositório):
  ```bash
   build-vectorstore
  ```

## Instalação

Na raiz do repositório:

```bash
source .venv/bin/activate
pip install -e llm/
pip install -e backend/
```

## Executar

```bash
source .venv/bin/activate
# Nota: se você estiver rodando Chroma separado em 8000, use outra porta pro FastAPI (ex.: 8001).
uvicorn assistente_medico_api.main:app --reload --host 0.0.0.0 --port 8000
```

- Documentação interativa: `http://127.0.0.1:8000/docs`
- Chat JSON: `POST http://127.0.0.1:8000/api/assistant/chat` com `Accept: application/json`
- Chat SSE: mesma URL com `Accept: text/event-stream`

## Variáveis de ambiente (prefixo `MEDICO_`)


| Variável                    | Exemplo                  | Descrição                                                                               |
| --------------------------- | ------------------------ | --------------------------------------------------------------------------------------- |
| `MEDICO_OLLAMA_BASE_URL`    | `http://127.0.0.1:11434` | URL base do Ollama                                                                      |
| `MEDICO_OLLAMA_EMBED_MODEL` | `nomic-embed-text`       | Modelo de embedding (igual à ingestão)                                                  |
| `MEDICO_OLLAMA_CHAT_MODEL`  | `gemma4:e4b-it-q4_K_M`   | Modelo de conversação                                                                   |
| `MEDICO_CHROMA_PERSIST_DIR` | *(opcional)*             | Caminho absoluto do Chroma; se omitido, usa `vectorstore/chroma` na raiz do repositório |
| `MEDICO_CHROMA_COLLECTION`  | `pcdt`                   | Nome da coleção                                                                         |
| `MEDICO_RETRIEVAL_K`        | `6`                      | Top-k na recuperação                                                                    |


## Frontend

Com o backend rodando, no frontend: `VITE_CLINICAL_API_HTTP=true` e, se necessário, `VITE_API_BASE_URL=http://localhost:8000/api`. Apenas o **chat** usa HTTP; o restante do protótipo permanece em memória até novas rotas.

Ver [frontend/API_ASSUMPTIONS.md](../frontend/API_ASSUMPTIONS.md).