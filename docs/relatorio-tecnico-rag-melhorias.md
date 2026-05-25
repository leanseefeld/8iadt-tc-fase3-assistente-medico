# Relatório Técnico — Oportunidades de Melhoria: `rewrite`, `retrieve` e `rerank`

**Repositório:** `8iadt-tc-fase3-assistente-medico`
**Data:** 2026-05-25
**Escopo:** análise estática do código — sem implementação

---

## 1. Visão Geral

### Pipeline atual

```
router → rewrite → retrieve → rerank → generate → guardrail
```

O fluxo RAG percorre os três nós de forma linear, com um loop interno de retry entre `retrieve` e `rerank`:

| Nó | Arquivo do nó | Service principal | Responsabilidade |
|---|---|---|---|
| `rewrite` | `nodes/rewrite.py` | `rag_query_expansion_service.py` | Reescreve a pergunta com LLM (quando há histórico) e expande com o catálogo CONITEC |
| `retrieve` | `nodes/retrieve.py` | `rag_pipeline_service.py:run_retrieve` | Busca candidatos no Chroma (k=30 por padrão), aplica filtro por `disease_normalized` quando confiança ≥ 0.84 |
| `rerank` | `nodes/rerank.py` | `rag_pipeline_service.py:run_rerank_and_validate_context` + `rag_enhancement.py:rerank_documents` | Remove docs da doença errada, aplica rerank heurístico (ou LLM), avalia suficiência do contexto, decide retry ou geração |

**Pontos fortes já implementados:**
- Nós finos com delegação para services — conforme convenção `.cursor/rules/langgraph-node-conventions.mdc`
- Expansão com catálogo CONITEC determinístico (sem LLM no hot path)
- Heurística de rerank explicável com `ranking_reasons` por documento
- Fallback robusto: filtro por doença → heurístico → retry → insufficient_context
- Prioridade correta para query original vs. LLM-reescrita no caso de abreviações clínicas (fix SGB)
- Auditoria JSONL por evento, com `rag_rewrite_done`, `rag_retrieve_done`, `rag_rerank_validate_done`

---

## 2. Melhorias para o nó `rewrite`

### R1 — Catálogo não cacheado em `rag_query_expansion_service.py`

| | |
|---|---|
| **Problema** | `expand_query_for_retrieval` chama `_load_catalog()` a cada invocação. Diferente de `cached_conitec_catalog()` em `rag_pipeline_service.py` (que usa `@lru_cache`), a versão do service de expansão lê o arquivo JSONL do disco a cada pergunta. |
| **Arquivos** | `services/rag_query_expansion_service.py:_load_catalog()`, `services/rag_pipeline_service.py:cached_conitec_catalog()` |
| **Proposta** | Reutilizar `cached_conitec_catalog()` de `rag_pipeline_service` em vez de manter `_load_catalog()` separado, ou decorar `_load_catalog` com `@lru_cache(maxsize=1)`. |
| **Impacto** | Elimina I/O de disco em toda chamada ao rewrite — visível em latência com muitos turnos simultâneos. |
| **Complexidade** | Baixa |
| **Prioridade** | Alta |

---

### R2 — Dois caminhos de rewrite com comportamentos diferentes

| | |
|---|---|
| **Problema** | Existe `run_rewrite_query` em `rag_pipeline_service.py` (usado pelo inspector via debug path) e `rewrite_query_node` + `rag_query_expansion_service.py` (usado pelo grafo real). Os dois têm lógica diferente: `run_rewrite_query` usa `memory_result` com `last_structured_terms` e LLM via `rewrite_debug`; `rewrite_query_node` usa `chat_history` do estado. O inspector pode reproduzir comportamento diferente do chat real. |
| **Arquivos** | `services/rag_pipeline_service.py:run_rewrite_query`, `services/rag_query_expansion_service.py`, `nodes/rewrite.py` |
| **Proposta** | `run_full_graph_debug` já chama `rewrite_query_node` (o nó real) — o caminho do grafo real está correto. Remover ou marcar `run_rewrite_query` como deprecated, pois não é mais chamado pelo fluxo principal, evitando divergência futura. |
| **Impacto** | Elimina risco de divergência entre inspector e produção. Simplifica manutenção. |
| **Complexidade** | Baixa |
| **Prioridade** | Alta |

---

### R3 — LLM de reescrita sem timeout configurável e sem log de latência próprio

| | |
|---|---|
| **Problema** | `resolve_retrieval_query` usa `_build_llm(settings)` que aplica `llm_stream_timeout_s` (padrão 240s) — timeout pensado para streaming de geração, excessivo para uma reescrita de query. A latência do rewrite LLM não é medida individualmente (apenas o nó inteiro é medido). |
| **Arquivos** | `services/rag_query_expansion_service.py:resolve_retrieval_query`, `config.py` |
| **Proposta** | Adicionar `llm_rewrite_timeout_s: float = Field(default=15.0)` em `Settings`. Medir e logar a latência específica da chamada LLM dentro do service. |
| **Impacto** | Evita que um LLM lento trave o pipeline por 240s numa reescrita que falhou. Melhora observabilidade. |
| **Complexidade** | Baixa |
| **Prioridade** | Alta |

---

### R4 — Follow-ups sem doença não propagam `structured_terms` do turno anterior

| | |
|---|---|
| **Problema** | Quando o médico pergunta "e os critérios de exclusão?" sem mencionar a doença, `expand_query_for_retrieval` tenta a query LLM-reescrita como fallback (`_has_disease`). Porém, o estado do grafo carrega `structured_terms` do turno anterior — esses `last_structured_terms` poderiam ser injetados diretamente para resolver o follow-up sem depender do LLM. |
| **Arquivos** | `services/rag_query_expansion_service.py:expand_query_for_retrieval`, `services/rag_pipeline_service.py:run_rewrite_query` (que já faz isso via `last_disease`) |
| **Proposta** | `expand_query_for_retrieval` receber o `structured_terms` do estado anterior como parâmetro opcional e usá-lo quando a query original e a reescrita não detectarem doença. |
| **Impacto** | Follow-ups clínicos mais precisos sem depender de LLM adicional para inferência de contexto. |
| **Complexidade** | Média |
| **Prioridade** | Alta |

---

### R5 — `reasoning_steps` no rewrite não registra qual doença foi detectada

| | |
|---|---|
| **Problema** | O step atual é `"Busca: consulta expandida com termos clínicos estruturados."` — genérico demais. O médico e o debugger não conseguem ver qual doença/CID foi detectado sem inspecionar `structured_terms`. |
| **Arquivos** | `nodes/rewrite.py` |
| **Proposta** | Adicionar step com: doença detectada, confiança, intent e query enviada ao Chroma. Ex: `"Rewrite: SGB (G61.0) detectado, intent=criterios_inclusao, query='Síndrome de Guillain-Barré critérios de inclusão'"` |
| **Impacto** | Melhora rastreabilidade e explicabilidade no frontend sem custo adicional. |
| **Complexidade** | Baixa |
| **Prioridade** | Média |

---

### R6 — Nó rewrite não retorna `linked_entities` e `catalog_candidates` como campos de estado de nível superior

| | |
|---|---|
| **Problema** | `ChatRAGState` define `linked_entities: list` e `catalog_candidates: list` como campos de estado de primeiro nível. O nó `rewrite` retorna esses dados embutidos em `structured_terms` mas não os escreve explicitamente nos campos de estado — o `generate` e outros nós que queiram acessar `state.get("linked_entities")` receberão `None`. |
| **Arquivos** | `nodes/rewrite.py`, `graph/state.py` |
| **Proposta** | Adicionar ao `return` do nó: `"linked_entities": expansion.structured_terms.get("linked_entities") or []`, `"catalog_candidates": expansion.structured_terms.get("catalog_candidates") or []`. |
| **Impacto** | Contrato do estado consistente; campos usáveis por nós futuros sem re-parsear `structured_terms`. |
| **Complexidade** | Baixa |
| **Prioridade** | Média |

---

### R7 — Ausência de testes para o caminho de fallback do LLM no rewrite

| | |
|---|---|
| **Problema** | `test_rewrite_node_behavior.py` testa o caminho feliz (sem histórico, com histórico e LLM funcionando), mas não cobre: LLM timeout, resposta vazia, resposta igual à query original. O `error` é retornado em `RetrievalQueryResolution` mas não é logado como warning na auditoria. |
| **Arquivos** | `tests/test_rewrite_node_behavior.py`, `services/rag_query_expansion_service.py` |
| **Proposta** | Adicionar testes para cada ramo de fallback; adicionar `audit("rag_rewrite_llm_error", ...)` quando `resolution.error is not None`. |
| **Impacto** | Aumenta confiança na robustez do rewrite em produção. |
| **Complexidade** | Baixa |
| **Prioridade** | Média |

---

## 3. Melhorias para o nó `retrieve`

### RT1 — Filtro de metadados muito restritivo: apenas `disease_normalized`, igualdade exata

| | |
|---|---|
| **Problema** | `_metadata_filter` aplica `{"disease_normalized": disease_norm}` somente. Se o nome da doença no documento divergir minimamente da normalização da query (ex.: variação de acento, nome longo vs. abreviação), todos os documentos são removidos pelo filtro, forçando o fallback para busca sem filtro — que pode trazer documentos irrelevantes. |
| **Arquivos** | `services/rag_pipeline_service.py:_metadata_filter` |
| **Proposta** | Manter o filtro atual como primeira tentativa. Na lógica de fallback já existente (quando Chroma lança exceção), adicionar também o caso de retorno vazio com filtro como trigger para descartar o filtro sem relançar a exceção. |
| **Impacto** | Reduz casos em que o filtro descarta documentos válidos silenciosamente. |
| **Complexidade** | Baixa |
| **Prioridade** | Alta |

---

### RT2 — Sem deduplicação de chunks no retrieve

| | |
|---|---|
| **Problema** | Um mesmo trecho PCDT pode aparecer múltiplas vezes como chunks diferentes (ex.: o mesmo parágrafo em um chunk de sobreposição). O Chroma retorna os k=30 mais próximos sem deduplicar por origem. Isso reduz diversidade efetiva dos documentos. |
| **Arquivos** | `services/rag_pipeline_service.py:run_retrieve` |
| **Proposta** | Após `_with_dense_metadata`, deduplicar por `source_stem + section + page_start`, mantendo o de maior score. Implementar em `run_retrieve`, antes de retornar `candidate_docs`. |
| **Impacto** | Aumenta diversidade de documentos; reduz custo de rerank processando menos candidatos redundantes. |
| **Complexidade** | Baixa |
| **Prioridade** | Alta |

---

### RT3 — Threshold de score mínimo não aplicado no retrieve

| | |
|---|---|
| **Problema** | Todos os k=30 documentos são retornados independente do score de similaridade. Para queries sem match no Chroma (doença não indexada), o pipeline recebe 30 documentos com scores baixíssimos, que passam pelo rerank e podem ser selecionados indevidamente. |
| **Arquivos** | `services/rag_pipeline_service.py:run_retrieve`, `config.py` |
| **Proposta** | Adicionar `rag_retrieve_min_score: float = Field(default=-1.0)` em `Settings` (desabilitado por padrão) e filtrar `pairs` com `score >= threshold` antes de `_with_dense_metadata`. |
| **Impacto** | Reduz custo de rerank e melhora qualidade do contexto quando a doença não está indexada. |
| **Complexidade** | Baixa |
| **Prioridade** | Média |

---

### RT4 — Fallback query no retry é rudimentar

| | |
|---|---|
| **Problema** | `_fallback_query` concatena `diretriz/disease + preferred_sections + cid10_codes + query_original`. Essa string pode ser longa, redundante e pior para busca vetorial do que a `expanded_query` original. O retry com query pior pode piorar o resultado. |
| **Arquivos** | `nodes/retrieve.py:_fallback_query` |
| **Proposta** | Estratégia de fallback baseada em `failure_type` do rerank: se `missing_preferred_section`, usar `"diretriz + section_label"` como fallback; se `wrong_disease`, não fazer retry. O tipo de falha vem de `rerank_result["failure_type"]` que está no estado. |
| **Impacto** | Retry mais efetivo — especialmente no caso de seção ausente. |
| **Complexidade** | Média |
| **Prioridade** | Alta |

---

### RT5 — Ausência de diversidade forçada entre documentos

| | |
|---|---|
| **Problema** | O retrieve pode retornar vários chunks do mesmo documento PCDT (mesma seção, páginas consecutivas). Mesmo após deduplicação por página, a concentração em um único documento reduz a cobertura do contexto. |
| **Arquivos** | `services/rag_pipeline_service.py:run_retrieve` |
| **Proposta** | Após deduplicação (RT2), aplicar diversidade mínima: no máximo N chunks do mesmo `source_stem` por busca (N configurável, ex.: `rag_max_chunks_per_source: int = 5`). |
| **Impacto** | Contexto mais variado; reduz risco de resposta baseada em único trecho. |
| **Complexidade** | Baixa |
| **Prioridade** | Média |

---

### RT6 — `retrieve_attempt` é incrementado no nó `rerank`, não no `retrieve`

| | |
|---|---|
| **Problema** | O `retrieve_attempt` começa em 1 e é incrementado pelo nó `rerank` quando decide `retry_retrieve`. O nó `retrieve` lê `state.get("retrieve_attempt") or 1`. Correto em execução, mas contraintuitivo para manutenção. |
| **Arquivos** | `nodes/rerank.py`, `nodes/retrieve.py` |
| **Proposta** | Documentar explicitamente nos dois nós que `retrieve_attempt` é o índice de tentativas gerenciado pelo `rerank`. Sem mudança de comportamento. |
| **Impacto** | Manutenibilidade e clareza. |
| **Complexidade** | Baixa |
| **Prioridade** | Baixa |

---

### RT7 — Logs de retrieve não informam taxa de hit do filtro por sessão

| | |
|---|---|
| **Problema** | O `audit("rag_retrieve_done", ...)` não registra quantos documentos foram retornados com vs. sem filtro quando há fallback. Impossível saber se o filtro por doença ajuda ou prejudica nos logs de produção. |
| **Arquivos** | `nodes/retrieve.py`, `services/rag_pipeline_service.py:run_retrieve` |
| **Proposta** | Adicionar ao `retrieve_debug`: `candidate_count_with_filter` e `candidate_count_without_filter` quando há fallback. |
| **Impacto** | Permite análise offline de eficácia do filtro por doença. |
| **Complexidade** | Baixa |
| **Prioridade** | Média |

---

### RT8 — Sem testes cobrindo comportamento de retry com `failure_type` específico

| | |
|---|---|
| **Problema** | Não há testes que verifiquem o comportamento do nó `retrieve` no segundo attempt (fallback_query, attempt=2) nem que `filter_applied=False` quando confiança < 0.84. |
| **Arquivos** | `tests/test_rag_pipeline_flow.py`, `nodes/retrieve.py` |
| **Proposta** | Adicionar testes para: (a) second attempt usa `fallback_query`; (b) `filter_applied=False` quando confiança < 0.84; (c) fallback para busca sem filtro quando Chroma retorna vazio com filtro. |
| **Complexidade** | Média |
| **Prioridade** | Média |

---

## 4. Melhorias para o nó `rerank`

### RK1 — Números mágicos no scoring heurístico sem calibração documentada

| | |
|---|---|
| **Problema** | `rerank_documents` em `rag_enhancement.py` usa boosts hardcoded: `10.0` (disease match com catálogo confiante), `5.0` (CID explícito), `8.0` (seção + doença com catálogo), `0.2` (seção sem catálogo), etc. Não há documentação de como esses valores foram derivados. |
| **Arquivos** | `graph/rag_enhancement.py:rerank_documents` |
| **Proposta** | Extrair os pesos para uma `dataclass RerankWeights` ou dicionário de constantes nomeado no topo do arquivo, com comentário explicando a relação de escala. Nenhuma mudança de comportamento. |
| **Impacto** | Facilita calibração futura; torna explícita a hierarquia de sinais. |
| **Complexidade** | Baixa |
| **Prioridade** | Alta |

---

### RK2 — `context_sufficient` é `True` mesmo com docs de baixíssima relevância

| | |
|---|---|
| **Problema** | Se há documentos da doença correta e da seção certa, `context_quality = "sufficient"` independente do score final dos documentos. Um documento com score `0.001` é considerado "contexto suficiente". O generate usa esse contexto fraco para uma resposta clínica. |
| **Arquivos** | `services/rag_pipeline_service.py:run_rerank_and_validate_context`, `config.py` |
| **Proposta** | Adicionar `rag_context_min_score: float = Field(default=0.0)` em `Settings`. Após selecionar `selected_docs`, verificar se o `final_score` médio ou do top-1 satisfaz o mínimo antes de marcar `context_quality = "sufficient"`. |
| **Impacto** | Previne geração clínica com contexto de baixa qualidade. |
| **Complexidade** | Baixa |
| **Prioridade** | Alta |

---

### RK3 — LLM reranker recebe snippets truncados sem metadados estruturados suficientes

| | |
|---|---|
| **Problema** | `_llm_rerank` envia snippets de 900 chars com campos `disease`, `section`, `pages` — mas não envia `cid10_codes`, `medicamentos`, `ranking_reasons` do heurístico, nem `dense_score`. O LLM decide sem ver os sinais mais relevantes. |
| **Arquivos** | `services/rag_pipeline_service.py:_llm_rerank` |
| **Proposta** | Enriquecer os itens enviados com: `cid10_codes`, `dense_score`, `heuristic_score` e `ranking_reasons`. Expandir o prompt system com instruções sobre o catálogo CONITEC e prioridade de seção. |
| **Impacto** | Melhora qualidade do LLM reranker quando ativado; reduz erros de seleção de doença errada. |
| **Complexidade** | Média |
| **Prioridade** | Média |

---

### RK4 — Fallback do LLM reranker para heurístico não é logado como warning

| | |
|---|---|
| **Problema** | Quando o LLM reranker falha (JSON inválido, timeout, sem docs selecionados), o código faz silencioso fallback para heurístico com `llm_debug = {"used": True, "error": ..., "fallback": "heuristic"}`. Esse erro não dispara `_logger.warning` nem incrementa nenhuma métrica. |
| **Arquivos** | `services/rag_pipeline_service.py:run_rerank_and_validate_context` |
| **Proposta** | Adicionar `_logger.warning("llm_rerank_fallback_to_heuristic; error=%s", exc)` no bloco de exception. Incluir `llm_rerank_fallback` no `audit("rag_rerank_validate_done", ...)`. |
| **Impacto** | Visibilidade de falhas silenciosas do LLM reranker. |
| **Complexidade** | Baixa |
| **Prioridade** | Alta |

---

### RK5 — `context_quality_router` está no arquivo do nó em vez de no service

| | |
|---|---|
| **Problema** | `context_quality_router` em `nodes/rerank.py` contém lógica de decisão (attempt vs. max_attempts) que pertence ao domínio do serviço. O nó também incrementa `retrieve_attempt`, misturando responsabilidades. |
| **Arquivos** | `nodes/rerank.py:context_quality_router`, `graph/chat_rag.py` |
| **Proposta** | Manter a função no arquivo do nó (necessário para `add_conditional_edges`), mas extrair a lógica de "qual attempt atual vs. max" para uma função auxiliar em `services/rag_pipeline_service.py`. |
| **Impacto** | Separação de responsabilidades; facilita teste unitário da decisão de routing. |
| **Complexidade** | Baixa |
| **Prioridade** | Baixa |

---

### RK6 — Penalização de doença errada usa igualdade exata de `disease_normalized`

| | |
|---|---|
| **Problema** | `_matches_structured_disease` usa `doc_norm == disease_norm` — igualdade exata após normalização. Dois nomes equivalentes para a mesma doença (ex.: "artrite reumatoide" vs. "artrite reumatoide do adulto") produzem falso mismatch, removendo documentos válidos. |
| **Arquivos** | `services/rag_pipeline_service.py:_matches_structured_disease`, `graph/rag_enhancement.py:_document_matches_disease` |
| **Proposta** | Adicionar correspondência por substring ou prefixo como fallback quando igualdade exata falhar, com threshold configurável. Usar o `CatalogConceptResolver` que já usa RapidFuzz para fuzzy matching. |
| **Impacto** | Reduz falsos negativos no filtro de doença; aumenta recall de documentos relevantes. |
| **Complexidade** | Média |
| **Prioridade** | Alta |

---

### RK7 — `CONTEXT_PARTIAL` não distingue "seção ausente mas doc disponível" de "nenhum doc"

| | |
|---|---|
| **Problema** | `failure_type = "missing_preferred_section"` pode levar a retry quando a seção simplesmente não existe no vectorstore (ex.: PCDT antigo sem seção CRITÉRIOS DE INCLUSÃO estruturada). O retry sempre falha igual, desperdiçando uma chamada Chroma e um ciclo de rerank. |
| **Arquivos** | `services/rag_pipeline_service.py:run_rerank_and_validate_context`, `nodes/rerank.py:context_quality_router` |
| **Proposta** | Adicionar `"missing_section_no_retry"` como sub-caso quando `retrieve_attempt >= max_retrieve_attempts - 1`: ir diretamente para `generate` com `context_sufficient=False`. Ou expor `skip_retry_for_section: bool` no `rerank_result` para o router decidir. |
| **Impacto** | Elimina retry inútil; reduz latência em ~30–50% nos casos de seção ausente no corpus. |
| **Complexidade** | Média |
| **Prioridade** | Alta |

---

### RK8 — Ausência de testes para o LLM reranker e seus fallbacks

| | |
|---|---|
| **Problema** | `_llm_rerank`, `LLMRerankResult`, `_extract_first_json_object` não têm testes unitários. A função `_extract_first_json_object` é crítica (parseamento de JSON embebido em texto livre do LLM) mas sem cobertura. |
| **Arquivos** | `services/rag_pipeline_service.py:_llm_rerank`, `tests/` |
| **Proposta** | Adicionar testes unitários para: (a) `_extract_first_json_object` com JSON válido, JSON embebido em texto, JSON incompleto; (b) `run_rerank_and_validate_context` com LLM mockado retornando JSON válido; (c) fallback quando LLM retorna JSON inválido. |
| **Complexidade** | Baixa |
| **Prioridade** | Alta |

---

## 5. Melhorias Transversais

### T1 — Estado do grafo sem tipagem forte em campos críticos

| | |
|---|---|
| **Problema** | `ChatRAGState(TypedDict, total=False)` tem todos os campos opcionais. Não há distinção entre "campo ainda não preenchido" e "campo intencionalmente ausente". Nós usam `state.get("X") or default` em vez de acessar campos garantidos por fase do pipeline. |
| **Proposta** | Documentar quais campos são garantidos após cada nó. Não requer mudança de TypedDict — basta um comentário de contrato por nó no módulo do nó. |
| **Complexidade** | Baixa |
| **Prioridade** | Média |

---

### T2 — Sem `trace_id` unificado atravessando todos os eventos de auditoria

| | |
|---|---|
| **Problema** | `audit("rag_rewrite_done", ...)`, `audit("rag_retrieve_done", ...)` e `clinical_audit(...)` não compartilham um `trace_id` comum por turno de conversa. Correlacionar eventos de uma mesma pergunta requer join por `patient_id` + timestamp. |
| **Arquivos** | `nodes/retrieve.py`, `nodes/rewrite.py`, `nodes/rerank.py`, `observability/audit.py` |
| **Proposta** | Adicionar `trace_id` (ex.: `str(uuid4())` gerado no início do turno pelo router ou pela API) ao estado do grafo e propagá-lo em todos os `audit()` e `clinical_audit()` calls. |
| **Complexidade** | Média |
| **Prioridade** | Alta |

---

### T3 — RAG Inspector não cobre o nó `load_patient_context`

| | |
|---|---|
| **Problema** | `run_full_graph_debug` em `rag_pipeline_service.py` começa do `router_search_needed_node`, pulando `load_patient_context_node`. O inspector nunca mostra dados de contexto do paciente. |
| **Arquivos** | `services/rag_pipeline_service.py:run_full_graph_debug` |
| **Proposta** | Adicionar chamada a `load_patient_context_node` no início de `run_full_graph_debug`, com `patient_id` configurável no inspector. |
| **Complexidade** | Baixa |
| **Prioridade** | Média |

---

### T4 — Ausência de dataset de golden questions para avaliação offline

| | |
|---|---|
| **Problema** | Não existe arquivo de golden questions (perguntas clínicas com resposta esperada, doença esperada, seção esperada, fontes esperadas). Todas as melhorias são validadas manualmente ou por testes unitários com mocks — não há avaliação de recall/precision do pipeline end-to-end. |
| **Proposta** | Criar `llm/data/eval/golden_questions.jsonl` com 30–50 perguntas cobrindo: abreviações (SGB, LES, AR), follow-ups, CID explícito, tratamento, critérios. Cada linha: `{query, expected_disease, expected_intent, expected_section, expected_cid10}`. Script de avaliação offline em `llm/scripts/eval_rag.py`. |
| **Complexidade** | Média |
| **Prioridade** | Alta |

---

### T5 — Sem métrica de `context_quality` agregada

| | |
|---|---|
| **Problema** | Cada interação produz `context_quality: sufficient | partial | insufficient` no JSONL de auditoria. Mas não há script ou query que agregue essa métrica por período, por doença, ou por intent — impossibilitando monitoramento de degradação do RAG. |
| **Proposta** | Script `llm/scripts/analyze_audit.py` que lê `audit_clinical_*.jsonl`, filtra eventos `rag_rerank_validate_done` e produz tabela: `{date, context_quality, count, diseases_most_failing}`. |
| **Complexidade** | Baixa |
| **Prioridade** | Média |

---

### T6 — `_as_list` duplicada em três módulos

| | |
|---|---|
| **Problema** | `_as_list` existe em: `graph/rag_enhancement.py`, `graph/clinical_query_understanding.py`, e também em `pcdt_ingest/`. Versões ligeiramente diferentes. |
| **Arquivos** | `graph/rag_enhancement.py:_as_list`, `graph/clinical_query_understanding.py:_as_list` |
| **Proposta** | Consolidar em `graph/rag_enhancement.py` e importar nos demais. |
| **Complexidade** | Baixa |
| **Prioridade** | Baixa |

---

## 6. Plano de Evolução Sugerido

### Fase 1 — Baixo risco / alto impacto (1–2 semanas)

Melhorias isoladas, sem mudança de comportamento externo:

1. **R1** — Cachear catálogo no `rag_query_expansion_service`
2. **R5** — Enriquecer `reasoning_steps` com doença detectada e intent
3. **R6** — Escrever `linked_entities` e `catalog_candidates` como campos de estado de nível superior no rewrite
4. **RK1** — Extrair pesos heurísticos do rerank para constantes nomeadas
5. **RK4** — Logar warning quando LLM reranker cai para heurístico
6. **RT2** — Deduplicação de chunks por `source_stem + section + page_start` no retrieve
7. **R3** — Timeout separado para LLM de reescrita
8. **RK8** — Testes unitários para `_extract_first_json_object` e LLM reranker

### Fase 2 — Qualidade de recuperação (2–4 semanas)

Mudanças que afetam o comportamento do pipeline:

1. **RK6** — Fuzzy match no filtro de doença (substring/prefixo) para reduzir falsos negativos
2. **RT4** — Estratégia de fallback query no retry baseada em `failure_type`
3. **RK7** — Detectar retry inútil por seção ausente e ir direto ao generate
4. **RT5** — Diversidade mínima entre documentos de mesma fonte
5. **R4** — Injetar `structured_terms` do turno anterior em follow-ups sem doença detectada
6. **RK2** — Score mínimo para declarar `context_sufficient`
7. **RT1** — Tratar retorno vazio com filtro como trigger de fallback (não só exceção)

### Fase 3 — Avaliação e MLOps (3–5 semanas)

1. **T4** — Criar dataset de golden questions (`llm/data/eval/golden_questions.jsonl`)
2. **T5** — Script de análise de auditoria agregada por `context_quality`
3. **T2** — `trace_id` unificado em todos os eventos de auditoria
4. Script de avaliação offline: taxa de detecção correta de doença, intent, seção por pergunta do golden set
5. Baseline das métricas atuais antes de qualquer mudança de Fase 2

### Fase 4 — Otimizações avançadas (4–8 semanas)

1. **RK3** — Enriquecer prompt e payload do LLM reranker com scores heurísticos
2. **T3** — Incluir `load_patient_context` no `run_full_graph_debug`
3. Experimento de retrieval híbrido: dense + BM25 sparse (avaliação offline obrigatória antes)
4. Calibração dos pesos heurísticos com base nos dados do golden set (análise de erro por categoria)
5. Análise de erro sistemática: quais doenças têm maior taxa de `wrong_disease` ou `missing_preferred_section`

---

## 7. Backlog Priorizado

| Prioridade | Nó | Melhoria | Impacto | Complexidade | Arquivos afetados |
|---|---|---|---|---|---|
| Alta | rewrite | R1 — Cachear catálogo em `_load_catalog` | Latência | Baixa | `rag_query_expansion_service.py` |
| Alta | rewrite | R2 — Remover/deprecar `run_rewrite_query` obsoleto | Manutenibilidade | Baixa | `rag_pipeline_service.py` |
| Alta | rewrite | R3 — Timeout separado para LLM de reescrita | Robustez | Baixa | `config.py`, `rag_query_expansion_service.py` |
| Alta | rewrite | R4 — Propagar `structured_terms` do turno anterior em follow-ups | Precisão clínica | Média | `rag_query_expansion_service.py`, `nodes/rewrite.py` |
| Alta | retrieve | RT1 — Tratar retorno vazio com filtro como fallback | Recall | Baixa | `rag_pipeline_service.py:run_retrieve` |
| Alta | retrieve | RT2 — Deduplicação de chunks | Diversidade | Baixa | `rag_pipeline_service.py:run_retrieve` |
| Alta | retrieve | RT4 — Fallback query baseado em `failure_type` | Precisão retry | Média | `nodes/retrieve.py:_fallback_query` |
| Alta | rerank | RK1 — Extrair pesos para constantes nomeadas | Manutenibilidade | Baixa | `rag_enhancement.py:rerank_documents` |
| Alta | rerank | RK2 — Score mínimo para `context_sufficient` | Qualidade | Baixa | `rag_pipeline_service.py`, `config.py` |
| Alta | rerank | RK4 — Log de warning quando LLM reranker falha | Observabilidade | Baixa | `rag_pipeline_service.py` |
| Alta | rerank | RK6 — Fuzzy match no filtro de doença | Recall | Média | `rag_pipeline_service.py`, `rag_enhancement.py` |
| Alta | rerank | RK7 — Evitar retry inútil por seção ausente | Latência | Média | `rag_pipeline_service.py`, `nodes/rerank.py` |
| Alta | rerank | RK8 — Testes para LLM reranker e fallbacks | Confiabilidade | Baixa | `tests/test_rag_pipeline_flow.py` |
| Alta | transversal | T2 — `trace_id` unificado na auditoria | Observabilidade | Média | `nodes/*.py`, `observability/audit.py` |
| Alta | transversal | T4 — Dataset de golden questions | Avaliação | Média | `llm/data/eval/`, `llm/scripts/` |
| Média | rewrite | R5 — `reasoning_steps` com doença e intent detectados | Explicabilidade | Baixa | `nodes/rewrite.py` |
| Média | rewrite | R6 — Escrever `linked_entities`/`catalog_candidates` no estado | Contrato | Baixa | `nodes/rewrite.py` |
| Média | rewrite | R7 — Testes para fallbacks do rewrite LLM | Confiabilidade | Baixa | `tests/test_rewrite_node_behavior.py` |
| Média | retrieve | RT3 — Score mínimo configurável no retrieve | Qualidade | Baixa | `rag_pipeline_service.py`, `config.py` |
| Média | retrieve | RT5 — Diversidade mínima por `source_stem` | Diversidade | Baixa | `rag_pipeline_service.py:run_retrieve` |
| Média | retrieve | RT7 — Log de hit/miss do filtro | Observabilidade | Baixa | `nodes/retrieve.py`, `rag_pipeline_service.py` |
| Média | retrieve | RT8 — Testes de retry com `failure_type` | Confiabilidade | Média | `tests/test_rag_pipeline_flow.py` |
| Média | rerank | RK3 — Enriquecer payload do LLM reranker | Precisão | Média | `rag_pipeline_service.py:_llm_rerank` |
| Média | transversal | T1 — Documentar contrato de campos de estado por fase | Manutenibilidade | Baixa | `graph/state.py`, `nodes/*.py` |
| Média | transversal | T3 — `load_patient_context` no debug | Fidelidade | Baixa | `rag_pipeline_service.py:run_full_graph_debug` |
| Média | transversal | T5 — Script de análise de `context_quality` agregada | Observabilidade | Baixa | `llm/scripts/analyze_audit.py` |
| Baixa | rerank | RK5 — Extrair lógica de routing para service | Separação de responsabilidades | Baixa | `nodes/rerank.py` |
| Baixa | retrieve | RT6 — Documentar contrato de `retrieve_attempt` | Clareza | Baixa | `nodes/rerank.py`, `nodes/retrieve.py` |
| Baixa | transversal | T6 — Consolidar `_as_list` duplicada | DRY | Baixa | `rag_enhancement.py`, `clinical_query_understanding.py` |

---

## 8. Recomendações Finais

**Implementar primeiro (semana 1):**

1. **R1 (cachear catálogo)** e **R3 (timeout de reescrita)** — alto impacto, zero risco, mudanças de 3–5 linhas cada.
2. **RK4 (log de fallback do LLM reranker)** — o sistema pode estar silenciosamente degradado sem que se saiba.
3. **RT2 (deduplicação de chunks)** — melhora qualidade do contexto sem risco, implementação simples.
4. **RK8 (testes do LLM reranker)** — a função `_extract_first_json_object` é crítica para robustez em produção e não tem cobertura.

**Implementar a seguir (semana 2–3):**

5. **RK6 (fuzzy match no filtro de doença)** — maior risco de regressão, precisa de testes antes de ir para produção. É o responsável por falsos negativos mais frequentes no rerank.
6. **RK7 (evitar retry inútil)** — reduz latência significativamente nos casos de seção ausente no corpus.
7. **T4 (golden questions)** — sem esse dataset, é impossível medir o impacto real de qualquer mudança nas fases seguintes.

**Não implementar ainda sem avaliação offline:**
- Retrieval híbrido (BM25 + dense) — mudança arquitetural com risco de regressão.
- Calibração de pesos heurísticos — requer o dataset de golden questions como base.
