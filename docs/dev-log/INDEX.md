# Dev log (índice compacto)

Formato: uma linha por marco relevante; mais detalhe só em `decisions/` quando necessário.

**Autor:** `git:<email>` quando ligado a commits no histórico; `agent:cursor` quando for registo só do assistente (sem commit). Prefixos facilitam `rg`/filtros.

**Revisão:** commit curto (7 hex) + assunto one-line do `git log`, conforme `.cursor/rules/dev-log.mdc`.

## Overview (histórico git)

Monorepo com **frontend** SPA (“Assistente Médico IA”), Docker e fachada `clinicalApi`; **pipeline RAG** com download de PCDTs, dataset COVID e ingestão PCDT linear; evolução para **extração MD a partir de PDF**, **chunking** e **visualizador** de chunks; **documentação** (relatório, referências) e **governação Cursor** (dev log + regras `dev-log` e `report-and-wait`).

| Data (ISO) | ID | Autor | Resumo | Revisão-Anterior |
|------------|-----|-------|--------|---------|
| 2026-04-02 | repo-spa-inicial | git:leander@nomadmacaw.com | Estrutura do repo, SPA, mocks, Docker, páginas, docs de referência, UI alinhada e `clinicalApi`. | `effc8e0` feat(frontend): align UI with reference and add clinicalApi facade |
| 2026-04-06 | pipeline-pcdt-docs | git:leander@nomadmacaw.com | Download de PCDTs e documentação do pipeline RAG. | `7faa982` feat(pipeline-rag): download PCDTs and document pipeline |
| 2026-04-06 | docs-relatorio | git:leander@nomadmacaw.com | Relatório de implementação em `docs/`. | `3128b97` docs: relatório de implementação |
| 2026-04-07 | dataset-covid | git:leander@nomadmacaw.com | Download e extração do dataset COVID no pipeline. | `987e403` feat(pipeline-rag): download and extract COVID dataset |
| 2026-04-08 | pcdt-ingest-linear | git:leander@nomadmacaw.com | Refactor da ingestão PCDT para fluxo linear. | `e749a15` refactor(pipeline-rag): ingestão PCDT linear |
| 2026-04-12 | pcdt-pdf-chunk-viz | git:leander@nomadmacaw.com | Markdown a partir de PDFs, chunking PCDT e ferramenta de visualização de chunks. | `6fde7c4` feat: PCDT chunks visualizer |
| 2026-04-12 | dev-log-regras-cursor | git:leander@nomadmacaw.com | Índice do dev log, regra `dev-log.mdc` e regra `report-and-wait-before-implement.mdc`. | `2843ab3` chore(cursor): add report-and-wait-before-implement rule |
| 2026-04-12 | dev-log-sistema-adocao | Leander Seefeld | Criação do sistema (`docs/dev-log/`, `decisions/`, regra `dev-log.mdc`) e adoção formal: overview, marcos via `git log`, Autor `git:email` e coluna Revisão. | `5ea7645` docs(dev-log): regista criação e adoção do sistema de dev log |
| 2026-04-12 | chroma-embed-pcdt | agent:cursor | CLI `build-vectorstore`, `embed.py`, Chroma em `vectorstore/chroma`, manifesto `pcdt_embed_index.jsonl`, deps langchain-chroma/ollama/chromadb. | `be5a299` docs(dev-log): registra criação e adoção do sistema de dev log |
| 2026-04-13 | build-vectorstore-verbose | agent:cursor | CLI `build-vectorstore --verbose`: log id/stem/tokens Ollama por fragmento e confirmação por lote Chroma (`embed.py`, `logutil.py`). | `d3375e0` fix: chunk visualizer "jump to page" with incorrect index |
| 2026-04-13 | chunk-size-400-tokens | git:leander@nomadmacaw.com | Reduz estimativa de tokens por chunk no chunking PCDT: de 800 para 400 (`chunk.py`). | `de1531f` feat: log token count per embedded chunk |


## `decisions/` (opcional)

Ficheiros `YYYYMMDD-id-curto.md` só quando uma linha no índice não chega (API, ADR mini).
