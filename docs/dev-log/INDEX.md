# Dev log (índice compacto)

Formato: lista agregada por data (uma entrada por marco relevante); mais detalhe só em `decisions/` quando necessário.

**Autor:** `git:<email>` quando ligado a commits no histórico; `agent:cursor` quando for registro só do assistente (sem commit). Prefixos facilitam `rg`/filtros.

**Revisão:** commit curto (7 hex) + assunto one-line do `git log`, conforme `.cursor/rules/dev-log.mdc`.

## Overview (histórico git)

Monorepo com **frontend** SPA (“Assistente Médico IA”), Docker e fachada `clinicalApi`; **backend** FastAPI (chat LangGraph + RAG Chroma, SSE); **pipeline RAG** com download de PCDTs, dataset COVID e ingestão PCDT linear; evolução para **extração MD a partir de PDF**, **chunking** e **visualizador** de chunks; **documentação** (relatório, referências) e **governação Cursor** (dev log + regras `dev-log` e `report-and-wait`).

## Marcos

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

## `decisions/` (opcional)

Arquivos `YYYYMMDD-id-curto.md` só quando uma linha no índice não chega (API, ADR mini).