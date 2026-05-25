# Dev log (índice compacto)

Formato: lista agregada por data (uma entrada por marco relevante); mais detalhe só em `decisions/` quando necessário.

**Autor:** `git:<email>` quando ligado a commits no histórico; `agent:cursor` quando for registro só do assistente (sem commit). Prefixos facilitam `rg`/filtros.

**Revisão:** commit curto (7 hex) + assunto one-line do `git log`, conforme `.cursor/rules/dev-log.mdc`.

## Overview (histórico git)

Monorepo com **frontend** SPA (“Assistente Médico”), Docker e fachada `clinicalApi`; **backend** FastAPI (chat LangGraph + RAG Chroma, SSE); **pipeline RAG** com download de PCDTs, dataset COVID e ingestão PCDT linear; evolução para **extração MD a partir de PDF**, **chunking** e **visualizador** de chunks; **documentação** (relatório, referências) e **governação Cursor** (dev log + regras `dev-log` e `report-and-wait`).

## Marcos

### 2026-05-25

- **aux-llm-interaction-log** — agent:cursor — Tabela `conversation_message_llm_calls` + `MEDICO_LLM_INTERACTION_LOG_ENABLED`; `llm_client.tracked_ainvoke` (router/rewrite/rerank/guardrail); extração por `messageId` via repo. — Revisão: `c7af82e` Merge branch 'feature/conversations-persistence'

### 2026-05-24

- **chat-conversations-sidebar** — agent:cursor — Chat: lista/retomada/arquivamento no sidebar; GET conversas/mensagens; PATCH archive (`archived_at`/`archived_by`); hidratação do grafo a partir do DB. — Revisão: `231d8f0` feat(chat): feedback de mensagens
- **chat-message-feedback** — agent:cursor — Chat: `messageId` no JSON/SSE `done`; PATCH feedback (`positive`/`negative`/null) em `conversation_messages.feedback_rating`; UI 👍/👎 na barra de meta (direita, hover, toggle). — Revisão: `f5a89b2` feat(chat): persistencia de conversas
- **chat-conversations-db** — agent:cursor — Chat: tabelas `conversations`/`conversation_messages` (médico, paciente, system_prompt, llm_input/output, fontes, raciocínio); `threadId`=PK; `X-User-Id` obrigatório; frontend só `threadId` (sem `messageHistory`). — Revisão: `83bd4f9` feat(generate): simplificação do prompt
- **auditoria-clinica-jsonl-diaria** — agent:cursor — JSONL `audit_clinical_*` com ações clínicas **e** eventos enxutos do RAG/chat/backend (`reescrita_consulta_rag`, `recuperacao_contexto_rag`, etc.); paralelamente reposto `audit()` JSON (retrieve/generate/startup/chat/guardrail); `pytest` não grava JSONL; `RAG_AUDIT_ENABLED` para JSONL técnico. — Revisão: `9ab7006` fix-scispacy

- **startup-jsonl-uma-linha-por-pid** — agent:cursor — `backend_assistente_iniciado`: no máximo **uma** entrada JSONL por processo (lifespan repetida); `audit(rag_backend_startup)` inalterado. — Revisão: `9ab7006` fix-scispacy

- **scispacy-extra-py314** — agent:cursor — `scispacy` sai do núcleo e vira extra `[scispacy]` em `llm/` + `backend/`; README + `--setup-scispacy` no `run-local.py` (fallback clínico continua sem o pacote). — Revisão: `e1ee2a6` feat: contexto do paciente na conversa + melhoria de prompt

- **no-contexto-paciente-rag** — agent:cursor — LangGraph: entrypoint `load_patient_context` com cache por thread + invalidação em PATCH paciente/exame; schema `gender`/`symptoms`/`exams.completed_at`; check-in/TopBar; RAG Inspector simulado. — Revisão: `15df709` feat: CID opcional; preservar sugestões/ações anteriores

### 2026-05-23

- **cid-opcional-admissao-edicao** — agent:cursor — CID opcional no check-in (sem fallback da lista); `CIDEditModal` remove CID; backend não aplica protocolo mock sem código (`patient_service`). — Revisão: `2ccf897` fix: add missing test dependency

### 2026-05-22

- **chat-meta-por-mensagem** — agent:cursor — Chat: fontes e raciocínio por turno em `ChatMessage`; accordion inline (`AssistantMessageMeta`); sem painel lateral; rodapé só após streaming e se houver meta. — Revisão: `4856e6a` feat: fine tuning v1

### 2026-05-21

- **logging-auditoria-estruturada** — agent:cursor — Logging JSON (stdout + arquivo rotativo `logs/assistente_medico.jsonl`), `JsonFormatter`, `RequestContextMiddleware` com `X-Request-Id`; `audit()` nos nós LangGraph, chat/decision-flow e ações clínicas (prescrições, alertas, vitals/exames/upload).

### 2026-04-26

- **chat-thread-checkpointer-rewrite** — Chat: `threadId` + `MemorySaver` (`ainvoke`/`astream_events` com config); `rewrite`→`retrieve`→`generate`; `retrieval_query` e reescrita via LLM com histórico; `generate` persiste turnos no estado; resposta JSON/SSE com `threadId`; frontend guarda thread por paciente. — Revisão: `844e734` adiciona memoria de conversa do chat
- **chat-message-history** — Chat: corpo opcional `messageHistory` (máx. 20 turnos) em `POST /api/assistant/chat`; `ChatRAGState.chat_history`; `generate` monta Human/Ai + última Human com PCDT; frontend envia histórico em `ChatPage`/`clinicalApi.http.ts`. — Revisão: `515092e` refactor: remove implementation plan for medication extraction from documentation

### 2026-04-02

- **repo-spa-inicial** — git:[leander@nomadmacaw.com](mailto:leander@nomadmacaw.com) — Estrutura do repo, SPA, mocks, Docker, páginas, docs de referência, UI alinhada e `clinicalApi`. — Revisão: `effc8e0` feat(frontend): align UI with reference and add clinicalApi facade

### 2026-04-06

- **pipeline-pcdt-docs** — git:[leander@nomadmacaw.com](mailto:leander@nomadmacaw.com) — Download de PCDTs e documentação do pipeline RAG. — Revisão: `7faa982` feat(pipeline-rag): download PCDTs and document pipeline
- **docs-relatorio** — git:[leander@nomadmacaw.com](mailto:leander@nomadmacaw.com) — Relatório de implementação em `docs/`. — Revisão: `3128b97` docs: relatório de implementação

### 2026-04-07

- **dataset-covid** — git:[leander@nomadmacaw.com](mailto:leander@nomadmacaw.com) — Download e extração do dataset COVID no pipeline. — Revisão: `987e403` feat(pipeline-rag): download and extract COVID dataset

### 2026-04-08

- **pcdt-ingest-linear** — git:[leander@nomadmacaw.com](mailto:leander@nomadmacaw.com) — Refactor da ingestão PCDT para fluxo linear. — Revisão: `e749a15` refactor(pipeline-rag): ingestão PCDT linear

### 2026-04-12

- **pcdt-pdf-chunk-viz** — git:[leander@nomadmacaw.com](mailto:leander@nomadmacaw.com) — Markdown a partir de PDFs, chunking PCDT e ferramenta de visualização de chunks. — Revisão: `6fde7c4` feat: PCDT chunks visualizer
- **dev-log-regras-cursor** — git:[leander@nomadmacaw.com](mailto:leander@nomadmacaw.com) — Índice do dev log, regra `dev-log.mdc` e regra `report-and-wait-before-implement.mdc`. — Revisão: `2843ab3` chore(cursor): add report-and-wait-before-implement rule
- **dev-log-sistema-adocao** — Leander Seefeld — Criação do sistema (`docs/dev-log/`, `decisions/`, regra `dev-log.mdc`) e adoção formal: overview, marcos via `git log`, Autor `git:email` e campo Revisão. — Revisão: `5ea7645` docs(dev-log): registra criação e adoção do sistema de dev log
- **chroma-embed-pcdt** — agent:cursor — CLI `build-vectorstore`, `embed.py`, Chroma em `vectorstore/chroma`, manifesto `pcdt_embed_index.jsonl`, deps langchain-chroma/ollama/chromadb. — Revisão: `be5a299` docs(dev-log): registra criação e adoção do sistema de dev log

### 2026-04-13

- **build-vectorstore-verbose** — agent:cursor — CLI `build-vectorstore --verbose`: log id/stem/tokens Ollama por fragmento e confirmação por lote Chroma (`embed.py`, `logutil.py`). — Revisão: `d3375e0` fix: chunk visualizer "jump to page" with incorrect index
- **chunk-size-400-tokens** — git:[leander@nomadmacaw.com](mailto:leander@nomadmacaw.com) — Reduz estimativa de tokens por chunk no chunking PCDT: de 800 para 400 (`chunk.py`). — Revisão: `de1531f` feat: log token count per embedded chunk
- **cleanup-cli-script-plan-defer** — Leander Seefeld — Plano em `.cursor/plans/cleanup_cli_script.plan.md` para limpar artefatos da ingestão; decisão de não implementar por agora. — Revisão: `af88e78` docs: atualizando relatório com conclusão da pipeline de ingestão
- **fastapi-chat-sse-rag** — agent:cursor — Pacote `backend/` FastAPI: chat LangGraph (retrieve→generate), SSE + JSON; `clinicalApi` híbrido (só chat HTTP); `API_ASSUMPTIONS`, `sseChat.ts`, Chroma/`pcdt_ingest`. — Revisão: `985642c` doc: execução completa da pipeline de ingestão
- **checkin-readmit-seed** — agent:cursor — Check-in: campos opcionais + defaults mock; 5 pacientes `discharged` em `seedDischargedPatients`; busca/readmissão `reAdmitPatientMock`; `CreatePatientRequestBody` parcial. — Revisão: `985642c` doc: execução completa da pipeline de ingestão
- **checkin-comorb-lookup-multi** — agent:cursor — Nova admissão: comorbidades como lookup (lista + filtro, multi-seleção, fechar fora), chips; `CheckInPage.tsx`. — Revisão: `985642c` doc: execução completa da pipeline de ingestão
- **pt-br-tone-fix** — agent:cursor — Localização: PT-PT → PT-BR em UI e docs; "registro", "paciente", "arquivo", gerúndios; `brazilian-tone-fixer`. — Revisão: `985642c` doc: execução completa da pipeline de ingestão
- **chat-markdown-render** — agent:cursor — Renderização de Markdown no chat com `react-markdown` e `remark-gfm`; estilos básicos para listas e blocos de código. — Revisão: `985642c` doc: execução completa da pipeline de ingestão
- **checkin-direct-dash** — agent:cursor — Check-in: remove spinner fake, redireciona direto para dashboard (`/`) após admissão. — Revisão: `985642c` doc: execução completa da pipeline de ingestão
- **graph-astream-events-sse** — agent:cursor — SSE via `graph.astream_events(version="v2")`: remove `_merge_retrieve`/`astream_answer`; `generate_node` async com `llm.astream`; tokens via `on_chat_model_stream`, metadados via `on_chain_end(name="retrieve")`. Decisão: `decisions/20260413-graph-astream-events-sse.md`. — Revisão: `1e7fd7b` chore(cursor): subagent to fix portuguese to brazilian
- **chat-json-ainvoke** — agent:cursor — Corrige caminho JSON: grafo tem nó async, então usar `graph.ainvoke` (não `invoke` em thread). — Revisão: `1e7fd7b` chore(cursor): subagent to fix portuguese to brazilian

### 2026-04-17

- **comorb-backend-endpoint** — agent:copilot — Migração de comorbidades: endpoint backend `GET /api/assistant/comorbidities` (lista em memória, sem banco), schema Pydantic `schemas/comorbidities.py`, frontend via `clinicalApi.comorbidities.ts`, check-in remove constante local, 22 opções expandidas. Proxy Vite para `/api`. — Implementação completa, 10/10 testes backend ✅.
- **padrao-criar-novas-tabelas** — agent:copilot — Documentação completa em `docs/dev-log/padrao-criar-novas-tabelas.md`: 7 passos (Model, Schema, Repository, Service, API, Migração, Registro); convenções nomes (tabelas, colunas, IDs, aliases); exemplo prático `Medications`; checklist implementação; boas práticas para IA. — Referência estruturada para novas entidades.

### 2026-05-09

- **prescricoes-rce-soft-delete** — agent:cursor — Prescrições RCE: tabela `prescriptions`, API `GET/POST /patients/{id}/prescriptions`, `GET/PATCH archive /prescriptions/{id}`, migração `20260509_1100`, testes `test_prescriptions_endpoint_contract.py`; UI `/prescriptions`, login fake (médico na TopBar), impressão CSS, integração «Criar prescrição» nas ações sugeridas; colunas `chat_thread_id` / `decision_flow_run_id` para auditoria futura. — Revisão: `69a118e` Cria guardrail de sugestões impróprias
- **login-fake-demo** — agent:cursor — Login demo `/login` com `fakeAuth.ts` + credenciais em `doctors.ts`; `ProtectedLayout`; TopBar com médico logado e **Sair**; remove seletor de médico. — Revisão: `69a118e` Cria guardrail de sugestões impróprias
- **ui-sem-atribuicao-ia** — agent:cursor — Remove na UI menção a conteúdo «por IA» (badge lista, faixa na RCE); «Criar prescrição» passa a emitir como médico logado; legado «Assistente Médico IA» exibido como «Médico responsável»; título do app só «Assistente Médico» (`LoginPage`, `Sidebar`, `index.html`). — Revisão: `c0576a8` adiciona prescrição

### 2026-05-03

- **guardrail-respostas** — agent:cursor — Novo nó `guardrail` no pipeline LangGraph (generate→guardrail→END): classifica via LLM (SEGURO/AVISO/BLOQUEAR), fallback por keywords regex, regeneração com `_STRICT_SYSTEM_PROMPT`, log estruturado JSON em `assistente_medico.guardrail`; `guardrail_status`/`guardrail_reason` no estado, schema e evento SSE `guardrail` em `api/chat.py`. — Revisão: `8537de3` Merge pull request #2 from leanseefeld/task/adicionar-memória-de-conversa-do-chat
- **guardrail-sse-fix** — agent:cursor — Corrige guardrail no caminho SSE: `chat_history` movido de `generate_node` para `guardrail_node` (usa `final_answer`); evento SSE `guardrail` inclui `answer`; `sseChat.ts` substitui texto acumulado se `status != safe`; `guardrail_reason` exposto na resposta JSON; imports `main.py` reorganizados. — Revisão: `8537de3` Merge pull request #2 from leanseefeld/task/adicionar-memória-de-conversa-do-chat

## `decisions/` (opcional)

Arquivos `YYYYMMDD-id-curto.md` só quando uma linha no índice não chega (API, ADR mini).
