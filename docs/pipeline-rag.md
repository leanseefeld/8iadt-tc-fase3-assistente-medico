# Pipeline de referência: RAG, dados tabulares e SFT

Este documento descreve uma linha de implementação sugerida após a ingestão em `llm/data/`. Nada disso é obrigatório para rodar os downloaders; serve como referência arquitetural.

## Escolha de stack (resumo)

| Etapa | Abordagem sugerida |
|--------|---------------------|
| Crawl / PDF / manifestos PCDT | **LangGraph** + **httpx** (+ **Playwright** opcional para JS). Não usar **sklearn `Pipeline`** como orquestrador principal: ele é para `fit`/`transform` em matrizes de features. |
| Download Einstein (CSV/XLSX dentro de ZIP) | **Playwright** (headed, para aceite de termos) ou download manual + flag `--zip`. Extração e catalogação via `zipfile` stdlib. |
| Limpeza e junção Einstein (CSV/XLSX) | **pandas** (ou Polars): dicionário, `ID_PACIENTE`, separador `\|`. Ver [datasource_albert-einstein.md](../../datasource_albert-einstein.md). |
| Modelo supervisionado clássico em cima de features tabulares | Aí sim **sklearn `Pipeline`** (imputação, encoding, escalonamento, classificador/regressor). |
| Texto para vetor / RAG | Extração de PDF (**pymupdf** / **pdfplumber**), chunking (**LangChain** ou código próprio), embeddings, armazenamento (pgvector, Qdrant, Chroma, etc.). |

## Estágios RAG (PCDT e, se aplicável, texto derivado de exames)

1. **Extrair**: PDF → texto por página em `llm/data/processed/pcdt/`.
2. **Limpar**: normalizar espaços, remover cabeçalhos/rodapés repetidos; idioma `pt-BR` na metadata.
3. **Fragmentar**: janelas com sobreposição ou chunking hierárquico; metadata: `doc_id`, `page`, `title`, `source_url`.
4. **Embeddings**: lotes com o modelo de embedding escolhido.
5. **Recuperação**: busca híbrida (BM25 + denso) costuma funcionar bem em documentos longos normativos.

## Fine-tuning supervisionado (SFT)

- **Não** gerar automaticamente todo o corpus como pares instrução/resposta.
- Curadoria em `llm/data/sft/samples/` (ex.: JSONL com tarefas: resumir critérios de elegibilidade, explicar contraindicações), com trechos citáveis do PCDT.
- Manter manifestos de SFT **separados** dos chunks de produção RAG para reduzir confusão treino vs. serviço.

## Dados sensíveis (Einstein)

O conjunto Einstein contém informação clínica anonimizada; respeitar termos de uso do repositório e políticas locais antes de serializar linhas para RAG ou SFT.

O repositório exige aceite de termos (nome, e-mail e concordância) antes de liberar o download. O script `download-clinical-exams` lida com isso de duas formas:

- **Com Playwright** (`pip install -e ".[playwright]"`): abre um navegador real para o usuário preencher os termos; o download é capturado automaticamente, extraído e catalogado.
- **Sem Playwright** (`--zip`): o usuário baixa o ZIP manualmente no navegador e passa o caminho ao script para extração e catalogação.

Em ambos os casos, os arquivos extraídos ficam em `llm/data/raw/clinical_exams/` e o manifesto em `llm/data/manifests/clinical_exams_index.jsonl`.
