# Pacote `llm` — ingestão de dados para RAG

Este diretório contém o pacote Python **assistente-medico-llm**, com:

- **PCDT (CONITEC)**: script `download-pcdt` que lê a **tabela** da página oficial de listagem PCDT, baixa cada documento ligado na segunda coluna e grava PDFs em `llm/data/raw/pcdt/` e manifestos em `llm/data/manifests/` (`pcdt_index.jsonl`, `pcdt_run.json`). Uma única URL HTTP (sem crawl nem navegador headless para este fluxo).
- **Exames (Einstein / USP)**: script que obtém artefatos do [Dados COVID Hospital Israelita Albert Einstein](https://repositoriodatasharingfapesp.uspdigital.usp.br/handle/item/98) em `llm/data/raw/clinical_exams/` para exemplos de exames clínicos.

## Instalação

Na raiz do repositório (com venv ativado):

```bash
cd llm && pip install -e .
```

Para usar o download Einstein com navegador (Playwright), instale também o Chromium:

```bash
playwright install chromium
```

## Uso

```bash
download-pcdt --max-files 200
download-pcdt --quiet
```

Manifestos PCDT: `llm/data/manifests/pcdt_index.jsonl`, `llm/data/manifests/pcdt_run.json`.

### Extração Markdown (PCDT)

Converte cada PDF em `llm/data/raw/pcdt/` para um **sidecar JSONL** por documento: `llm/data/processed/pcdt/<nome>.pages.jsonl` (uma linha JSON por página, campos `page` e `markdown`). Esse ficheiro é a fonte por página para um passo futuro de chunking (`page_range`).

```bash
extract-pcdt-markdown
extract-pcdt-markdown --max-files 5
extract-pcdt-markdown --only-manifest
extract-pcdt-markdown --force
extract-pcdt-markdown --workers 4   # vários PDFs em paralelo (uma thread por ficheiro)
```

O ficheiro **Markdown combinado** (`processed/pcdt/<nome>.md`, todas as páginas em sequência) **só** é gerado se usar a flag:

```bash
extract-pcdt-markdown --with-combined-md
```

Manifesto desta extração: `llm/data/manifests/pcdt_md_extract.jsonl` (uma linha por PDF processado, com caminhos relativos a `llm/data/`, `wrote_combined_md`, `status`, etc.).

### Fragmentação de chunks (PCDT)

Após existir `processed/pcdt/<nome>.pages.jsonl`, gera `chunks/pcdt/<nome>.chunks.jsonl` (uma linha por chunk: `text` + `metadata` com `source_stem`, `source_pdf`, `section`, `header_1`/`header_2`, `page_start`/`page_end`, `chunk_index`, etc.). Usa LangChain (`MarkdownHeaderTextSplitter` + `RecursiveCharacterTextSplitter`).

```bash
chunk-pcdt
chunk-pcdt --max-files 10
chunk-pcdt --only-manifest
chunk-pcdt --force
chunk-pcdt --workers 4
```

Manifesto: `llm/data/manifests/pcdt_chunk_index.jsonl`.

### Einstein (USP)

```bash
download-clinical-exams              # abre navegador para aceite de termos (requer playwright)
download-clinical-exams --zip FILE   # extrai ZIP já baixado manualmente
```

O repositório exige **aceite de termos** (nome, e-mail e concordância) antes de liberar o download. Há duas opções:

#### Opção A — download automático (Playwright)

Com `pip install -e .` e `playwright install chromium`:

```bash
download-clinical-exams
```

Um navegador Chromium será aberto na página do repositório. Preencha os dados solicitados e aceite os termos; o download será capturado automaticamente, extraído em `llm/data/raw/clinical_exams/` e catalogado em `llm/data/manifests/clinical_exams_index.jsonl`.

#### Opção B — download manual (sem Playwright)

1. Acesse <https://repositoriodatasharingfapesp.uspdigital.usp.br/handle/item/98> no navegador.
2. Clique em **View/Open**, preencha nome, e-mail e aceite os termos.
3. Salve o arquivo `EINSTEINAgosto.zip` em qualquer local.
4. Execute:

```bash
download-clinical-exams --zip caminho/para/EINSTEINAgosto.zip
```

O resultado é o mesmo: arquivos extraídos em `llm/data/raw/clinical_exams/` e manifesto em `llm/data/manifests/clinical_exams_index.jsonl`.

Documentação do dataset: [docs/datasource_albert-einstein.md](../docs/datasource_albert-einstein.md)

## Documentação do pipeline RAG

Ver [docs/pipeline-rag.md](../docs/pipeline-rag.md).
