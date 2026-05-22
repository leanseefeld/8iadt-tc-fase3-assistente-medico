# API do Assistente Médico (FastAPI)

Serviço HTTP em FastAPI: orquestração LangGraph para **chat com RAG** sobre PCDTs indexados no Chroma (`vectorstore/chroma` na raiz do repositório). Modelo de chat padrão: **Ollama** `gemma4:e4b-it-q4_K_M`; embeddings de consulta: **mesmo** modelo usado na ingestão (`nomic-embed-text`), servido pelo Ollama.

## Pré-requisitos

1. Python **≥ 3.11** e ambiente virtual (ex.: `.venv` na raiz do monorepo).
2. Pacote da pipeline instalado (fornece `pcdt_ingest`):
  ```bash
   pip install -e llm/
  ```
3. **Ollama** em execução com `nomic-embed-text` e `gemma4:e4b-it-q4_K_M` (ou ajuste `MEDICO_OLLAMA_`*).
4. Vector store populado (a partir da raiz do repositório). A pipeline atual pode gerar o catálogo Conitec antes dos chunks, enriquecendo documentos indexados com metadados de diretriz, CID-10 e medicamentos:
  ```bash
   build-conitec-catalog
   chunk-pcdt --force
   build-vectorstore
  ```

## Instalação

Na raiz do repositório:

```bash
source .venv/bin/activate
pip install -e llm
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
- **Memória de conversa:** envie `threadId` devolvido na resposta anterior (JSON `threadId` ou SSE `event: done`) para persistir o histórico no servidor (**LangGraph** + `MemorySaver`). Opcional: `messageHistory` — até **20** itens `{ "role", "content" }` anteriores à `message` atual (fallback se o thread ainda não tem estado ou cliente legado). O PCDT entra só no turno final da geração. Com histórico, o grafo **reescreve** a pergunta antes do retrieve no Chroma.

## Variáveis de ambiente (prefixo `MEDICO_`)


| Variável                    | Exemplo                  | Descrição                                                                               |
| --------------------------- | ------------------------ | --------------------------------------------------------------------------------------- |
| `MEDICO_OLLAMA_BASE_URL`    | `http://127.0.0.1:11434` | URL base do Ollama                                                                      |
| `MEDICO_OLLAMA_EMBED_MODEL` | `nomic-embed-text`       | Modelo de embedding (igual à ingestão)                                                  |
| `MEDICO_OLLAMA_CHAT_MODEL`  | `gemma4:e4b-it-q4_K_M`   | Modelo de conversação                                                                   |
| `MEDICO_CHROMA_PERSIST_DIR` | *(opcional)*             | Caminho absoluto do Chroma; se omitido, usa `vectorstore/chroma` na raiz do repositório |
| `MEDICO_CHROMA_COLLECTION`  | `pcdt`                   | Nome da coleção                                                                         |
| `MEDICO_RETRIEVAL_K`        | `6`                      | Top-k na recuperação                                                                    |
| `RAG_RETRIEVE_CANDIDATES_K` ou `MEDICO_RAG_RETRIEVE_CANDIDATES_K` | `30` | Quantidade inicial de candidatos Chroma antes do reranking |
| `RAG_RETRIEVE_FINAL_K` ou `MEDICO_RAG_RETRIEVE_FINAL_K` | `6` | Quantidade final de documentos enviados ao prompt |
| `RAG_AUDIT_JSONL` ou `MEDICO_RAG_AUDIT_JSONL` | `../llm/data/audit/rag_interactions.jsonl` | Arquivo JSONL de auditoria RAG |
| `RAG_AUDIT_ENABLED` ou `MEDICO_RAG_AUDIT_ENABLED` | `true` | Liga/desliga escrita da auditoria RAG |
| `RAG_MIN_FINAL_SCORE` ou `MEDICO_RAG_MIN_FINAL_SCORE` | `-5.0` | Score mínimo para um documento entrar no prompt final |
| `RAG_USE_CROSS_ENCODER_RERANK` ou `MEDICO_RAG_USE_CROSS_ENCODER_RERANK` | `false` | Liga reranking opcional por CrossEncoder após o rerank heurístico |
| `RAG_CROSS_ENCODER_MODEL` ou `MEDICO_RAG_CROSS_ENCODER_MODEL` | `cross-encoder/ms-marco-MiniLM-L-6-v2` | Modelo `sentence-transformers` usado quando CrossEncoder está ativo |
| `RAG_CROSS_ENCODER_TOP_N` ou `MEDICO_RAG_CROSS_ENCODER_TOP_N` | `15` | Quantos documentos heurísticos são enviados ao CrossEncoder |
| `MEDICO_DATABASE_URL`       | `sqlite+aiosqlite:///./assistente_medico.db` | URL do banco (SQLite assíncrono por padrão)                              |
| `MEDICO_LOG_DIR`            | `./logs`                  | Diretório (relativo à raiz do repositório se não absoluto) para `assistente_medico.jsonl` |
| `MEDICO_LOG_LEVEL`          | `INFO`                   | Nível efetivo dos loggers `assistente_medico.*` (ex.: `DEBUG`, `INFO`)                    |

## Logging e auditoria

O backend registra eventos estruturados em **JSON**, linha a linha:

- **Stdout** (via handler do logger `assistente_medico`): útil com `uvicorn` e gravação pelo orquestrador.
- **Arquivo rotativo** `assistente_medico.jsonl` em `MEDICO_LOG_DIR` (padrão `./logs` na raiz do repo; diretório criado na subida do processo).

Middleware `RequestContextMiddleware`:

- Lê ou gera `X-Request-Id` e devolve o mesmo id no header de resposta para correlação cliente/servidor.
- Emite `event: http_request` com `latency_ms`, método, path HTTP e status.

Eventos principais (campo `event` no JSON):

- **Chat:** `chat_request_received`, `chat_response_done` (JSON ou SSE, com contagem aproximada de chunks em `tokens_streamed` no modo stream).
- **Decision flow:** `decision_flow_run`, `decision_flow_done`.
- **RAG (LangGraph):** `rag_rewrite_done`, `rag_retrieve_done`, `rag_generate_done`, `guardrail_*` (classificação e bloqueios).
- **Clínico:** `prescription_created`, `prescription_archived`, `clinical_alert_created`, `vitals_recorded`, `vitals_critical_detected`, `exam_status_changed`, `exam_attachment_uploaded`, etc.

Consulta rápida (exemplos):

```bash
grep '"event":"guardrail_blocked"' logs/assistente_medico.jsonl
grep '"event":"chat_response_done"' logs/assistente_medico.jsonl | head
```

## Recuperação RAG

O fluxo de recuperação do chat agora é:

```text
pergunta -> entendimento clínico -> expansão restritiva Conitec -> Chroma k=30 -> reranking por intenção -> top 6 -> prompt -> auditoria
```

A expansão usa apenas o catálogo local `llm/data/processed/conitec/pcdt_catalog.jsonl`; a planilha da Conitec não é baixada em tempo de requisição. O chat interpreta a pergunta médica antes da busca, detectando intenção clínica, CID-10 explícito, medicamento explícito e uma diretriz/doença do catálogo quando houver match forte. A expansão é restritiva e sensível à intenção: perguntas de critérios de inclusão/exclusão adicionam apenas a doença canônica e a seção esperada, sem CIDs ou medicamentos automáticos.

O reranking é heurístico e explicável. Quando uma doença é detectada com confiança alta, há pós-filtro rígido por `metadata.disease_normalized`: se sobrarem documentos da doença correta, doenças diferentes não entram no prompt só para completar o top 6. Ele mantém a posição original do Chroma como base, mas aplica boosts por doença/diretriz detectada, seção compatível com a intenção, CID explícito e medicamento explícito. CIDs vindos apenas da expansão recebem peso fraco ou são ignorados em perguntas de critérios. Para perguntas de critérios de inclusão, seções como CID-10, Fármacos, Tratamento e Diagnóstico diferencial são penalizadas em relação à seção `CRITÉRIOS DE INCLUSÃO`.

Depois do rerank heurístico, é possível habilitar reranking por `sentence-transformers` CrossEncoder para reordenar os candidatos já recuperados. As bibliotecas clínicas e de reranking (`medspacy`, `spacy`, `rapidfuzz`, `sentence-transformers`) são dependências obrigatórias do backend; o modelo CrossEncoder só é carregado se `RAG_USE_CROSS_ENCODER_RERANK=true`. Se o modelo configurado falhar ao carregar, o fluxo mantém o ranking heurístico.

O prompt enviado ao LLM inclui metadados ricos por documento:

- diretriz e doença;
- CID-10;
- medicamentos relacionados, com limite de itens;
- seção;
- portaria e data;
- fonte e páginas;
- score final e motivos do ranking.
- entendimento clínico da pergunta (intenção, doença, CID e medicamento explícitos).

A resposta continua citando documentos pelo identificador `[n]`. A política de segurança de doses/posologia permanece sob o guardrail existente.

Auditoria: cada interação RAG grava uma linha JSON em `RAG_AUDIT_JSONL`, com pergunta original, entendimento clínico, query expandida, termos adicionados, `k` inicial/final, status do filtro por doença, contagem antes/depois do filtro, uso de CrossEncoder, documentos usados, scores, motivos de ranking e resposta final pós-guardrail. Falha de auditoria é registrada em log e não derruba a resposta.

Exemplos rápidos para testar:

```text
Quais critérios de inclusão para insuficiência adrenal?
O que o PCDT fala sobre E27.1?
HIV criança
Tratamento com hidrocortisona
```

## Configurar SQLite

Por padrão, o backend usa SQLite local com arquivo no diretório `backend/assistente_medico.db`.

1. Defina a URL no `.env` do backend:

```bash
MEDICO_DATABASE_URL=sqlite+aiosqlite:///./assistente_medico.db
```

2. Se quiser usar outro caminho de arquivo SQLite:

```bash
MEDICO_DATABASE_URL=sqlite+aiosqlite:////caminho/absoluto/assistente_medico.db
```

3. Teste rápido da configuração (na pasta `backend/`):

```bash
python -c "from assistente_medico_api.config import Settings; print(Settings().database_url)"
```

## Migrations e Seed

Com ambiente virtual ativo e dependências instaladas:

```bash
source .venv/bin/activate
pip install -e llm/
pip install -e backend/
```

Na pasta `backend/`, execute:

```bash
alembic upgrade head
python scripts/seed_patients.py
```

Verificação rápida:

```bash
sqlite3 assistente_medico.db ".tables"
```

Comandos úteis do Alembic:

```bash
# gerar nova migration
alembic revision --autogenerate -m "descricao_da_mudanca"

# aplicar migration
alembic upgrade head

# voltar um passo
alembic downgrade -1
```

Observações:

- O seed deve ser idempotente (não duplicar dados quando já existir paciente).
- Em ambiente de produção, prefira aplicar migrations no deploy e não via `create_all`.


## Frontend

Com o backend rodando, no frontend: `VITE_CLINICAL_API_HTTP=true` e, se necessário, `VITE_API_BASE_URL=http://localhost:8000/api`.

Ver [frontend/API_ASSUMPTIONS.md](../frontend/API_ASSUMPTIONS.md).
