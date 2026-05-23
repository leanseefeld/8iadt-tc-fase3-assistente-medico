# Pipeline de referência: RAG, dados tabulares e SFT

Este documento descreve uma linha de implementação sugerida após a ingestão em `llm/data/`. Nada disso é obrigatório para rodar os downloaders; serve como referência arquitetural.

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

1. **Extrair**: PDF → sidecar JSONL por página (`processed/pcdt/<nome>.pages.jsonl`, comando `extract-pcdt-markdown`); Markdown combinado opcional com `--with-combined-md`.
2. **Gerar catálogo Conitec**: `build-conitec-catalog` lê a planilha oficial de diretrizes/CID/medicamentos e grava `processed/conitec/pcdt_catalog.jsonl`. Não há download em import time; a URL só é usada via CLI ou função explícita.
3. **Limpar**: normalizar espaços, remover cabeçalhos/rodapés repetidos, tabelas de índice/sumário, formulários, tabelas OCR malformadas, anexos/apêndices e referências finais.
4. **Fragmentar**: `chunk-pcdt` gera `chunks/pcdt/<nome>.chunks.jsonl` a partir dos sidecars limpos quando existem. A fragmentação costura páginas antes de dividir texto, calcula `page_start`/`page_end` por spans globais e normaliza títulos PCDT para preencher melhor `section` e `header_*`. O modo padrão vem de `llm/config.py` e pode ser sobrescrito por `--chunk-strategy recursive|semantic`; o modo `semantic` usa `SemanticChunker` por seção lógica com `nomic-embed-text` via Ollama.
5. **Enriquecer metadados**: quando há match seguro entre o PDF e a `Diretriz` do catálogo, `disease`, `disease_normalized`, `diretriz`, CID-10, medicamentos, portarias e siglas vêm da planilha (`metadata_source = "conitec_xlsx"`). Sem match confiável, a heurística antiga continua ativa (`metadata_source = "heuristic"`).
6. **Embeddings**: lotes com o modelo de embedding escolhido. Metadados estruturados permanecem nos `.chunks.jsonl`; para Chroma, listas são convertidas para JSON string pela etapa de indexação.
7. **Recuperação**: busca híbrida (BM25 + denso) costuma funcionar bem em documentos longos normativos. O catálogo também expõe expansão de query para termos como `HIV`, agregando diretrizes, descrições CID-10, medicamentos e siglas relacionadas.

Fluxo local completo:

```bash
download-pcdt
build-conitec-catalog
extract-pcdt-markdown --workers 6
clean-pcdt-extracted --workers 6
chunk-pcdt --workers 6
build-vectorstore
```

Para depurar a recuperação e a montagem de prompt sem subir backend/frontend, use o RAG Inspector:

```bash
cd llm
ollama pull llama3.2:3b
streamlit run scripts/rag_inspector_app.py
```

O Inspector usa `llama3.2:3b` por padrão e não tenta fallback automático para outro modelo; falhas de geração aparecem como erro da execução.

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
