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
| `RAG_REQUIRE_CATALOG_MATCH_WHEN_CONFIDENT` ou `MEDICO_RAG_REQUIRE_CATALOG_MATCH_WHEN_CONFIDENT` | `true` | Quando há candidato de catálogo confiável, só retorna documentos compatíveis |
| `RAG_MIN_FINAL_SCORE_WITH_CATALOG` ou `MEDICO_RAG_MIN_FINAL_SCORE_WITH_CATALOG` | `0.0` | Score mínimo quando o filtro de catálogo confiante está ativo |
| `RAG_USE_CROSS_ENCODER_RERANK` ou `MEDICO_RAG_USE_CROSS_ENCODER_RERANK` | `false` | Liga reranking opcional por CrossEncoder após o rerank heurístico |
| `RAG_CROSS_ENCODER_MODEL` ou `MEDICO_RAG_CROSS_ENCODER_MODEL` | `cross-encoder/ms-marco-MiniLM-L-6-v2` | Modelo `sentence-transformers` usado quando CrossEncoder está ativo |
| `RAG_CROSS_ENCODER_TOP_N` ou `MEDICO_RAG_CROSS_ENCODER_TOP_N` | `15` | Quantos documentos heurísticos são enviados ao CrossEncoder |
| `MEDICO_RAG_MAX_RETRIEVE_ATTEMPTS` | `2` | Máximo de buscas por pergunta: tentativa inicial + um fallback |
| `MEDICO_RAG_USE_LLM_RERANK` | `false` | Liga rerank/validação por LLM com fallback heurístico validado |
| `MEDICO_RAG_LLM_RERANK_TOP_N` | `12` | Número de candidatos enviados ao LLM reranker quando habilitado |
| `MEDICO_RAG_REQUIRE_SOURCE_FOR_CLINICAL_ANSWER` | `true` | Impede geração clínica grounded sem contexto validado suficiente |
| `MEDICO_RAG_DEBUG` | `false` | Habilita diagnóstico adicional em rotas/ferramentas de debug |
| `MEDICO_ENABLE_MEDICAL_NLP` | `true` | Ativa resolvedores NLP médicos opcionais no rewrite; catálogo Conitec continua ativo quando `false` |
| `MEDICO_USE_MEDSPACY` | `false` | Ativa medSpaCy/PyRuSH. Desligado por padrão para evitar travamentos locais |
| `MEDICO_MEDSPACY_MODEL` | `pt_core_news_sm` | Modelo spaCy em português usado pelo medSpaCy quando habilitado |
| `MEDICO_MEDSPACY_LANGUAGE_CODE` | `pt` | Código de idioma passado ao medSpaCy |
| `MEDICO_USE_SPACY` | `true` | Ativa spaCy NER leve quando modelo local existir |
| `MEDICO_SPACY_MODEL` | `pt_core_news_sm` | Modelo spaCy local usado no fallback leve |
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

## Grafo RAG do chat

O chat real (`POST /api/assistant/chat`, tanto JSON quanto SSE) passa pelo mesmo grafo:

```text
router
-> generate (direct_answer) -> guardrail
-> rewrite -> retrieve -> rerank
   -> generate (grounded_answer | insufficient_context) -> guardrail
```

Contratos principais no estado:

- `router_result`: decisão conservadora sobre necessidade de RAG. Perguntas clínicas e follow-ups clínicos seguem para busca.
- `rewrite_result`: `retrieval_query`, `expanded_query`, `structured_terms`, candidatos de catálogo e entendimento clínico.
- `retrieve_result`: tentativa, query enviada ao Chroma, filtro de metadata, candidatos e configuração efetiva.
- `rerank_result`: documentos finais, `context_quality` (`sufficient`, `partial`, `insufficient`), `failure_type`, seções esperadas/encontradas e debug do rerank.
- `generation_mode`, `guardrail_status` e `guardrail_reason`: estratégia de geração e avaliação final de segurança.
- `reasoning_steps`, `router_decision`, `query_expansion`, `retrieve_result`, `rerank_result`, `generation_mode`, `guardrail_status` e `guardrail_reason`: trilha funcional do fluxo RAG.

`retrieve` é executado inicialmente e pode ser repetido como retry interno até `MEDICO_RAG_MAX_RETRIEVE_ATTEMPTS`. Se uma pergunta pede seção específica, por exemplo `CRITÉRIOS DE INCLUSÃO`, e só há chunk de `CID-10`, o contexto fica `partial`, `context_sufficient=false` e o retry é acionado. Depois da última tentativa, contexto ainda parcial/insuficiente gera resposta controlada, sem LLM inventar conteúdo clínico.

Localização dos nós:

- `graph/nodes/router.py`: decide `search_needed` de forma conservadora.
- `graph/nodes/rewrite.py`: restaura o LLM rewrite da `main`; usa `chat_history` para produzir `retrieval_query` e depois aplica expansão estruturada.
- `graph/nodes/retrieve.py`: busca apenas candidatos no Chroma.
- `graph/nodes/rerank.py`: filtra, reranqueia e valida suficiência.
- `graph/nodes/generate.py`: único nó público de geração; escolhe `grounded_answer`, `direct_answer` ou `insufficient_context` por `generation_mode`.
- `graph/nodes/guardrail.py`: avalia segurança da resposta final.

O rewrite combina três fontes:

1. LLM rewrite conversacional com transcript do histórico, preservado da `main`.
2. `last_structured_terms` da memória para resolver follow-ups sem regex de doenças.
3. Catálogo Conitec e `clinical_entity_resolver` para `linked_entities`, `catalog_candidates`, `structured_terms` e `expanded_query`.

O `clinical_entity_resolver` usa o catálogo Conitec como fallback permanente. Por padrão, ele tenta spaCy leve quando houver modelo local e não carrega medSpaCy/PyRuSH. Para usar medSpaCy com modelo em português, instale o modelo spaCy localmente e configure:

```bash
python -m spacy download pt_core_news_sm
export MEDICO_ENABLE_MEDICAL_NLP=true
export MEDICO_USE_MEDSPACY=true
export MEDICO_MEDSPACY_MODEL=pt_core_news_sm
export MEDICO_MEDSPACY_LANGUAGE_CODE=pt
```

Com o orquestrador local:

```bash
python run-local.py --setup-medical-nlp
python run-local.py --use-medspacy-pt
```

Nenhum modelo é baixado em runtime; se medSpaCy/spaCy não estiver instalado ou configurado, o backend continua funcionando pelo catálogo.

## Recuperação RAG

O fluxo de recuperação do chat agora é:

```text
pergunta
-> ClinicalIntentClassifier
-> BiomedicalEntityResolver
-> CatalogConceptResolver
-> QueryExpansionFromCatalog
-> Chroma k=30
-> reranking consciente de catálogo
-> top final
-> prompt
-> auditoria
```

A expansão usa apenas o catálogo local `llm/data/processed/conitec/pcdt_catalog.jsonl`; a planilha da Conitec não é baixada em tempo de requisição. O chat interpreta a pergunta médica antes da busca, detectando intenção clínica, entidades biomédicas linkadas quando houver backend disponível, CID-10 explícito e candidatos de diretriz/doença do catálogo quando houver match forte.

A saída da expansão tem dois canais:

- `expanded_query`: texto limpo enviado ao Chroma, com pergunta original, diretriz/doença canônica, um CID-10 quando houver um único código relevante, e seção preferencial. Não contém JSON, nomes de campos ou listas serializadas.
- `structured_terms`: dados serializáveis usados por filtro, rerank, prompt e auditoria, incluindo doença, diretriz, CID-10, intenção, seções preferenciais, candidatos do catálogo, entidades linkadas e confiança.

Medicamentos e CIDs múltiplos ficam em `structured_terms`; eles não entram automaticamente no texto vetorial quando isso poluiria a busca.

O resolvedor biomédico tenta, nessa ordem, scispaCy com EntityLinker, QuickUMLS apontado por `QUICKUMLS_FP`/`QUICKUMLS_PATH`, e spaCy apenas como NER. Se nada estiver instalado ou configurado, ele retorna lista vazia; o fallback continua pelo matching semântico contra o catálogo, nunca pela primeira palavra da pergunta ou por sigla extraída isoladamente. Modelos não são baixados em runtime.

O reranking é heurístico e explicável. Ele usa `structured_terms`, não parseia a string expandida, para decidir doença/diretriz, CIDs, intenção e seções preferenciais. Quando há candidato de catálogo confiável, documentos da mesma diretriz/doença têm prioridade e documentos de outra doença não sobem apenas por seção; se o filtro por catálogo não encontra documentos compatíveis, o fluxo registra baixa confiança e evita completar o top final com documentos errados. A posição original do Chroma continua como base, mas `catalog_candidate_match` pesa mais que `section_intent_match`. CIDs explícitos na pergunta geram `cid_explicit_match`; CIDs vindos do catálogo entram como reforço leve (`cid_catalog_hint`) e não dominam critérios de inclusão.

Depois do rerank heurístico, é possível habilitar reranking por `sentence-transformers` CrossEncoder para reordenar os candidatos já recuperados. As dependências biomédicas (`spacy`, `medspacy`, `scispacy`) fazem parte da instalação padrão do backend. O reranking por CrossEncoder continua opcional:

```bash
pip install -e "backend[rerank]"
```

O modelo CrossEncoder só é carregado se `RAG_USE_CROSS_ENCODER_RERANK=true`. Se o modelo configurado falhar ao carregar, o fluxo mantém o ranking heurístico.

O prompt enviado ao LLM inclui metadados ricos por documento:

- diretriz e doença;
- CID-10;
- medicamentos relacionados, com limite de itens;
- seção;
- portaria e data;
- fonte e páginas;
- score final e motivos do ranking.
- entendimento clínico da pergunta (intenção, doença, CID e medicamento explícitos).
- entidades biomédicas linkadas e candidatos do catálogo.

A resposta continua citando documentos pelo identificador `[n]`. A política de segurança de doses/posologia permanece sob o guardrail existente.

Auditoria: cada interação RAG grava uma linha JSON em `RAG_AUDIT_JSONL`, com `original_query`, `retrieval_query`, `expanded_query`, `structured_terms`, documentos candidatos, documentos finais, `rerank_result`, modo de geração e resposta final pós-guardrail. Falha de auditoria é registrada em log e não derruba a resposta. Para depurar o fluxo, confira `router_decision`, `query_expansion`, `retrieve_result`, `rerank_result`, `generation_mode`, `sources`, `guardrail_status` e `guardrail_reason` no retorno/stream do chat ou use o RAG Inspector em `llm/scripts/rag_inspector_app.py`.

### Troubleshooting RAG

- Inspector diferente do chat: confirme `MEDICO_CHROMA_PERSIST_DIR`, `MEDICO_CHROMA_COLLECTION`, `MEDICO_OLLAMA_EMBED_MODEL` e se o inspector está mostrando `uses_shared_debug_pipeline=true`.
- Catálogo achou doença, mas Chroma não achou chunks: confira se `build-conitec-catalog`, `chunk-pcdt --force` e `build-vectorstore --force` foram executados na mesma base.
- LLM rerank desligado: por padrão `MEDICO_RAG_USE_LLM_RERANK=false` por desempenho; o rerank heurístico continua determinístico. Habilite para auditoria adicional quando houver Ollama disponível.
- Pergunta clínica sem fonte: com `MEDICO_RAG_REQUIRE_SOURCE_FOR_CLINICAL_ANSWER=true`, o backend retorna resposta de contexto insuficiente em vez de gerar resposta clínica sem documentos validados.
- Ollama indisponível no rewrite: o nó registra fallback e usa a pergunta atual com `last_structured_terms` quando houver memória, preservando auditoria do erro.
- Chat pendurado antes do retrieve: rode com `MEDICO_ENABLE_MEDICAL_NLP=false` e `MEDICO_USE_MEDSPACY=false`. Os logs `rewrite: before_entity_resolver` e `rewrite: after_entity_resolver` mostram se travou no NLP médico.

Exemplos rápidos para testar:

```text
Quais critérios de inclusão para insuficiência adrenal?
O que o PCDT fala sobre E27.1?
Como tratar HIV em crianças?
Quais são os critérios de inclusão para sgb?
Como eu reconheço uma criança com lupus?
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
