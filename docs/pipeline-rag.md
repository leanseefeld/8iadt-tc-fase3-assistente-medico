# Pipeline de referência: RAG, dados tabulares e SFT

Este documento descreve o pipeline RAG **tal como implementado** (ingestão em `llm/` e recuperação em `backend/`), além de pontos de referência arquitetural para evolução. A tabela de stack abaixo lista escolhas adotadas e algumas alternativas de referência; as etapas e a recuperação refletem o comportamento atual do código.

## Escolha de stack (resumo)

| Etapa | Abordagem sugerida |
|--------|---------------------|
| Listagem / PDF / manifestos PCDT | **httpx** + **BeautifulSoup**: uma página de listagem CONITEC, tabela PCDT, `download-pcdt`. Não usar **sklearn `Pipeline`** como orquestrador principal: ele é para `fit`/`transform` em matrizes de features. |
| Catálogo Conitec PCDT/CID/medicamentos | **pandas + openpyxl**: leitura explícita da planilha oficial da Conitec via `build-conitec-catalog`, cache em `llm/data/processed/conitec/pcdt_catalog.jsonl` e uso no chunking para enriquecer metadados. |
| Download Einstein (CSV/XLSX dentro de ZIP) | **Playwright** (headed, para aceite de termos) ou download manual + flag `--zip`. Extração e catalogação via `zipfile` stdlib. |
| Limpeza e junção Einstein (CSV/XLSX) | **pandas** (ou Polars): dicionário, `ID_PACIENTE`, separador `\|`. Ver [datasource_albert-einstein.md](../../datasource_albert-einstein.md). |
| Modelo supervisionado clássico em cima de features tabulares | Aí sim **sklearn `Pipeline`** (imputação, encoding, escalonamento, classificador/regressor). |
| Texto para vetor / RAG | Extração de PDF (**pymupdf** / **pdfplumber**), chunking (**LangChain** ou código próprio), embeddings, armazenamento (pgvector, Qdrant, Chroma, etc.). |

## Estágios RAG (PCDT e, se aplicável, texto derivado de exames)

1. **Extrair**: PDF → sidecar JSONL por página (`processed/pcdt/<nome>.pages.jsonl`, comando `extract-pcdt-markdown`); Markdown combinado opcional com `--with-combined-md`. A extração usa `pymupdf4llm.to_markdown(..., page_chunks=True)` (`llm/src/pcdt_ingest/extract.py`). A fidelidade de **tabelas, figuras e diagramas** é limitada nessa conversão — uma reavaliação dessa etapa está prevista (ver [agente-busca-especializado.md](handoff/agente-busca-especializado.md)).
2. **Gerar catálogo Conitec**: `build-conitec-catalog` lê a planilha oficial de diretrizes/CID/medicamentos e grava `processed/conitec/pcdt_catalog.jsonl`. Não há download em import time; a URL só é usada via CLI ou função explícita.
3. **Limpar**: normalizar espaços, remover cabeçalhos/rodapés repetidos, tabelas de índice/sumário, formulários, anexos/apêndices e referências finais (`llm/src/pcdt_ingest/clean/heuristics.py`). **Atenção:** a limpeza atual também **descarta** placeholders de imagem, legendas de figura/tabela e tabelas consideradas malformadas — ou seja, imagens, figuras e diagramas não chegam ao chunking. Isso é adequado para texto corrido, mas conflita com o objetivo de preservar estrutura (tabelas/figuras/hierarquia); a mudança proposta está descrita em [agente-busca-especializado.md](handoff/agente-busca-especializado.md).
4. **Fragmentar**: `chunk-pcdt` gera `chunks/pcdt/<nome>.chunks.jsonl` a partir dos sidecars limpos quando existem. A fragmentação costura páginas antes de dividir texto, calcula `page_start`/`page_end` por spans globais e normaliza títulos PCDT para preencher melhor `section` e `header_*`. O modo padrão vem de `llm/config.py` e pode ser sobrescrito por `--chunk-strategy recursive|semantic`; o modo `semantic` usa `SemanticChunker` por seção lógica com `nomic-embed-text` via Ollama.
5. **Enriquecer metadados**: quando há match seguro entre o PDF e a `Diretriz` do catálogo, `disease`, `disease_normalized`, `diretriz`, CID-10, medicamentos, portarias e siglas vêm da planilha (`metadata_source = "conitec_xlsx"`). Sem match confiável, a heurística antiga continua ativa (`metadata_source = "heuristic"`).
6. **Embeddings**: lotes com o modelo de embedding escolhido. Metadados estruturados permanecem nos `.chunks.jsonl`; para Chroma, listas são convertidas para JSON string pela etapa de indexação.
7. **Recuperação** (backend, grafo `chat_rag`): o fluxo real é
   1. **Rewrite por LLM** da pergunta (inclusive no 1º turno) → query única autocontida (`services/rag_query_expansion_service.py`).
   2. **Expansão por catálogo Conitec** sobre a query, agregando diretrizes, descrições CID-10, medicamentos e siglas relacionadas, e produzindo `structured_terms` (doença, intenção, seções preferidas, candidatos do catálogo).
   3. **Busca densa** no Chroma (`similarity_search_with_score`, embeddings `nomic-embed-text`), `k = rag_retrieve_candidates_k` (30 por padrão), com filtro de metadados por `disease_normalized` quando a confiança é alta (com fallback sem filtro).
   4. **Rerank** dos candidatos até `rag_retrieve_final_k` (6 por padrão): heurístico por padrão (match de doença/CID/seção + relevância de query); **LLM rerank** e **CrossEncoder** são opcionais (desligados por padrão).
   5. **Grading de suficiência de contexto** (`sufficient`/`partial`/`insufficient`) com **loop de retry** de retrieval, e exigência de fonte para resposta clínica.

   > Nota: a recuperação atual é **somente densa**. Busca híbrida (BM25 + denso) **não** está implementada — fica registrada como inspiração futura em [agente-busca-especializado.md](handoff/agente-busca-especializado.md).

Fluxo local completo:

```bash
download-pcdt
build-conitec-catalog
extract-pcdt-markdown --workers 6
clean-pcdt-extracted --workers 6
chunk-pcdt --workers 6
build-vectorstore
```

## Ferramentas de inspeção do retrieval

Para depurar a recuperação e a montagem de prompt sem subir backend/frontend:

- **RAG Inspector** (Streamlit) — inspeção ponta a ponta do pipeline (router → rewrite → retrieve → rerank → generate → guardrail), com scores e motivos por documento, estatísticas de embedding e aba de Vectorstore (listar coleções, contagem, amostras). Por trás chama `run_full_graph_debug()` em `backend/.../services/rag_pipeline_service.py`.

  ```bash
  cd llm
  ollama pull llama3.2:3b
  streamlit run scripts/rag_inspector_app.py
  ```

  O Inspector usa `llama3.2:3b` por padrão e não tenta fallback automático para outro modelo; falhas de geração aparecem como erro da execução.

- **Consulta direta ao vectorstore** (`scripts/example_vectorstore_rag_query.py`) — exemplo mínimo de `similarity_search_with_score` com scores e metadados por chunk:

  ```bash
  cd llm && python scripts/example_vectorstore_rag_query.py -q "critérios de inclusão para sepse" -k 6
  ```

- **Estatísticas de tokens por PCDT** (`scripts/chroma_token_stats.py`) — contagem de chunks e tokens por `source_stem`, tokenizador por caractere ou `tiktoken`:

  ```bash
  cd llm && python scripts/chroma_token_stats.py --tokenizer tiktoken --sort tokens
  ```

- **Orçamento de tokens do bloco de retrieval p/ Llama 3.2** (`scripts/chroma_llama_token_analysis.py`, também como `.ipynb`) — quanto cabe no contexto conforme `k`, chunks grandes, e estimativa de VRAM por quantização:

  ```bash
  cd llm && python scripts/chroma_llama_token_analysis.py --max-documents 30
  ```

Outras formas de inspeção em runtime:
- **Eventos SSE** de `POST /assistant/chat` emitem `sources` e `reasoning_steps` antes dos tokens (UI mostra em "🔍 Fontes" / "🧠 Raciocínio", `frontend/.../AssistantMessageMeta.tsx`).
- **Auditoria técnica RAG** em JSONL quando `MEDICO_RAG_AUDIT_ENABLED=true` (query expandida, `structured_terms`, documentos recuperados, scores de rerank, qualidade de contexto).

## Fine-tuning supervisionado (SFT)

- **Não** gerar automaticamente todo o corpus como pares instrução/resposta.
- Curadoria em `llm/data/sft/samples/` (ex.: JSONL com tarefas: resumir critérios de elegibilidade, explicar contraindicações), com trechos citáveis do PCDT.
- Manter manifestos de SFT **separados** dos chunks de produção RAG para reduzir confusão treino vs. serviço.

## Dados sensíveis (Einstein)

O conjunto Einstein contém informação clínica anonimizada; respeitar termos de uso do repositório e políticas locais antes de serializar linhas para RAG ou SFT.

O repositório exige aceite de termos (nome, e-mail e concordância) antes de liberar o download. O script `download-clinical-exams` lida com isso de duas formas:

- **Com Playwright** (`pip install -e .` a partir de `llm/`, depois `playwright install chromium`): abre um navegador real para o usuário preencher os termos; o download é capturado automaticamente, extraído e catalogado.
- **Sem Playwright** (`--zip`): o usuário baixa o ZIP manualmente no navegador e passa o caminho ao script para extração e catalogação.

Em ambos os casos, os arquivos extraídos ficam em `llm/data/raw/clinical_exams/` e o manifesto em `llm/data/manifests/clinical_exams_index.jsonl`.
