# Pipeline de referência: RAG, dados tabulares e SFT

Este documento descreve uma linha de implementação sugerida após a ingestão em `llm/data/`. Nada disso é obrigatório para rodar os downloaders; serve como referência arquitetural.

## Escolha de stack (resumo)

| Etapa | Abordagem sugerida |
|--------|---------------------|
| Crawl / PDF / manifestos PCDT | **LangGraph** + **httpx** (+ **Playwright** opcional). Não usar **sklearn `Pipeline`** como orquestrador principal: ele é para `fit`/`transform` em matrizes de features. |
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

O endpoint de bitstream pode devolver **HTML de termos de uso** em vez do arquivo até que haja aceite (navegador ou sessão). O script `download-clinical-exams` registra isso no manifesto (`status=error`, detalhe explicativo) em vez de gravar HTML com extensão incorreta.
