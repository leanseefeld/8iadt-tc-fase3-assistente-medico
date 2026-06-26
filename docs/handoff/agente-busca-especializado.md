# Ideação: Agente de busca especializado + ingestão estruturada

> Documento de **design/ideação**. Serve de ponto de partida para discussão.
> ADR correspondente: [`docs/dev-log/decisions/20260624-agente-busca-especializado.md`](../dev-log/decisions/20260624-agente-busca-especializado.md).
>
> **Status — Pilar 1 (busca por N queries) implementado** atrás da flag `MEDICO_RAG_MULTI_QUERY_ENABLED` (**default ON**). Versão minimalista e desacoplada do RAG legado: **sem** catálogo Conitec, `structured_terms` ou expansão de query. Subgrafo isolado em `backend/src/assistente_medico_api/graph/search/` (`plan_queries` via LLM/CoT → `search` com fusão RRF). Com a flag OFF, roda o fluxo RAG legado intacto. Avaliação: `llm/scripts/rag_eval_multiquery.py` sobre `llm/data/eval/rag_questions.jsonl`. Pilares 2 e 3 e a Parte C seguem como ideação.

## Problema

O pipeline RAG atual (ver [pipeline-rag.md](../pipeline-rag.md)) tem três limitações que travam a qualidade da recuperação em documentos normativos longos:

1. **Query única.** A pergunta do médico vira **uma** query reescrita por LLM. Perguntas clínicas frequentemente exigem múltiplas buscas (critérios de inclusão *e* esquema terapêutico *e* contraindicações), que uma query só não cobre bem.
2. **Estrutura perdida na ingestão.** A extração (`pymupdf4llm`) tem fidelidade limitada para tabelas/figuras, e a limpeza (`clean/heuristics.py`) **descarta** imagens, figuras, diagramas e tabelas malformadas. Muito do conteúdo clínico crítico de um PCDT está exatamente em **tabelas** (doses, critérios) e **fluxogramas**.
3. **Sem controle operacional.** Adicionar um PCDT novo ou reexecutar o pipeline a partir de uma etapa é um processo de linha de comando, sem visão de estado nem avaliação de saídas.

## Objetivos

- Recuperação dirigida por LLM com **chain-of-thought** que gera **até N queries** Chroma a partir de uma pergunta clínica.
- Ingestão que **preserva e expõe** hierarquia: cabeçalhos, seções, tabelas, imagens, diagramas.
- Operação do pipeline por **interface web**: adicionar PCDTs, reexecutar a partir de uma etapa, avaliar saídas.

---

## Pilar 1 — Geração de queries por LLM (chain-of-thought)

Substituir/estender o rewrite de query única (`services/rag_query_expansion_service.py`) por um **agente gerador de queries**:

- **Entrada:** pergunta do médico + contexto do paciente + `structured_terms` já derivados do catálogo Conitec.
- **Raciocínio (CoT):** o LLM decompõe a intenção clínica (diagnóstico? tratamento? critérios? monitoramento?) e identifica facetas a cobrir (doença, CID-10, medicamentos, seção-alvo).
- **Saída estruturada:** **até N queries** (`N` configurável), cada uma com:
  - texto da query (para busca densa),
  - seções-alvo / filtros de metadados sugeridos (`disease_normalized`, `header_*`),
  - justificativa curta (para auditoria/raciocínio).
- **Execução:** cada query roda no Chroma; resultados são **fundidos e deduplicados** antes do rerank existente.

**Pontos de integração:** encaixa entre os nós `rewrite` → `retrieve` do grafo `chat_rag` (`backend/.../graph/chat_rag.py`). O `retrieve` passa a iterar sobre N queries; o `rerank` e o grading de suficiência permanecem.

**Inspiração (não implementado hoje):** fan-out **denso + lexical/BM25** — as N queries alimentam tanto o canal denso (Chroma) quanto um índice lexical, com fusão (ex.: Reciprocal Rank Fusion). Era citado como "busca híbrida" na doc antiga, mas nunca foi construído.

**Questões em aberto:** valor default de N e teto de latência; quando vale gerar N queries vs. cair no rewrite simples; como pontuar/fundir resultados de queries distintas antes do rerank.

---

## Pilar 2 — Chunking e surfacing estruturado

Preservar a estrutura do documento e **expô-la ao LLM** como grounding.

- **Preservar na ingestão:** cabeçalhos e hierarquia (já parcialmente em `header_1`/`header_2`/`section`), **tabelas** (como estrutura, não texto achatado), **figuras/diagramas** (legenda + referência à imagem; OCR/descrição quando relevante).
- **Metadados/conteúdo do chunk:** marcar tipo de bloco (`texto`, `tabela`, `figura`, `fluxograma`), caminho hierárquico completo, e referência à imagem original quando aplicável.
- **Surfacing no prompt:** o resultado da busca entregue ao LLM deve sinalizar explicitamente quando um chunk é uma tabela/figura e preservar sua estrutura (ex.: tabela em Markdown íntegro), em vez de texto corrido degradado.

**Conflito a resolver:** a limpeza atual (`clean/heuristics.py`) remove justamente imagens/figuras/tabelas. Será preciso uma trilha de limpeza que **separe** ruído (cabeçalho/rodapé/índice) de **conteúdo estrutural** a preservar.

---

## Pilar 3 — Reavaliação da conversão dos PDFs (extração `pcdt-ingest`)

A qualidade do Pilar 2 é limitada pelo que a extração preserva. Reavaliar a etapa `extract-pcdt-markdown` (`llm/src/pcdt_ingest/extract.py`, hoje `pymupdf4llm.to_markdown(..., page_chunks=True)`):

- **Avaliar abordagens layout-aware** que capturem tabelas como estrutura e detectem figuras/diagramas (ex.: extratores de tabela dedicados, parsing de layout, OCR de figuras quando o texto vetorial falha).
- **Critério de avaliação:** comparar, num conjunto de PCDTs representativos, a fidelidade de tabelas de dose/critérios e a preservação de fluxogramas.
- **Acoplamento com Pilar 2:** o formato de saída da extração precisa carregar a marcação de blocos (tabela/figura) para o chunking aproveitar.

---

## Parte C — Interface e fluxo web de operação do pipeline

Proposta de **UI web** para operar a ingestão/RAG sem linha de comando, reaproveitando os manifestos JSONL por etapa já existentes em `llm/data/manifests/` (`pcdt_index` → `pcdt_md_extract` → `pcdt_clean_index` → `pcdt_chunk_index` → `pcdt_embed_index`).

**Fluxo principal:**
1. **Adicionar PCDTs** — upload manual e/ou seleção a partir de listagens descobertas (ver inspiração abaixo).
2. **Reexecutar a partir de uma etapa** — download → extrair → limpar → fragmentar → embeddings → vectorstore, retomando de qualquer ponto com base no estado dos manifestos (status `ok`/erro por documento).
3. **Avaliar saídas** — inspecionar, por etapa e por documento: sidecars de página, chunks gerados, e o retrieval resultante (reaproveitando o **RAG Inspector** como base de visualização).

**Inspirações registradas (futuro):**
- **Gestão de PCDTs e outros protocolos** com **scrapers específicos por fonte**, que listam os documentos encontrados numa página para curadoria/seleção. Fontes-exemplo:
  - Conitec (já há `download-pcdt` / `build-conitec-catalog`).
  - Sites de prefeituras, ex.: POPs da Prefeitura de Florianópolis — `https://portal.pmf.sc.gov.br/entidades/saude/index.php?cms=procedimentos+operacionais+padrao+++pops&menu=10&submenuid=1478`.
- **Perfis profissionais** (enfermagem, farmácia e outros) com seus próprios **POPs** e bases de conhecimento/prompts dedicados. (Também anotado como reminder para a extensão do relatório — ver [sugestoes-relatorio-implementacao.md](sugestoes-relatorio-implementacao.md).)

---

## Resumo dos pontos de integração no código

| Pilar | Arquivos-chave atuais a evoluir |
|-------|--------------------------------|
| 1 — N queries (CoT) | `backend/.../services/rag_query_expansion_service.py`, `graph/chat_rag.py` (nós `rewrite`/`retrieve`), `services/rag_pipeline_service.py` (`run_retrieve`) |
| 2 — Chunking estruturado | `llm/src/pcdt_ingest/chunk.py`, `clean/heuristics.py`, `embed.py`; formatação em `backend/.../graph/context_formatting.py` / `rag_enhancement.py` |
| 3 — Conversão de PDF | `llm/src/pcdt_ingest/extract.py` |
| C — UI/operação | manifestos `llm/data/manifests/*`, CLIs `pcdt_ingest`, base no `llm/scripts/rag_inspector_app.py` |
