# Pacote `llm` — ingestão de dados para RAG

Este diretório contém o pacote Python **assistente-medico-llm**, com:

- **PCDT (CONITEC)**: grafo **LangGraph** que descobre links em `gov.br`, baixa PDFs para `llm/data/raw/pcdt/` e grava manifestos em `llm/data/manifests/`.
- **Exames (Einstein / USP)**: script que baixa artefatos listados para [Dados COVID Hospital Israelita Albert Einstein](https://repositoriodatasharingfapesp.uspdigital.usp.br/handle/item/98) para `llm/data/raw/clinical_exams/` para exemplos de exames clínicos.

## Instalação

Na raiz do repositório (com venv ativado):

```bash
cd llm && pip install -e ".[dev]"
```

Opcional (HTML via browser):

```bash
pip install -e ".[playwright]"
playwright install chromium
```

## Uso

```bash
download-pcdt --max-pages 40 --max-files 200
download-pcdt --playwright   # se o site exigir JS (logs no stderr; `networkidle` pode demorar)
download-pcdt --quiet          # menos mensagens

# Por padrão o crawl segue a **árvore da listagem PCDT** e os PDFs aceitos incluem qualquer link **com ``/conitec/``** no path (ex.: ``/midias/…``), marcadores PCDT no URL ou PDFs em ``saude.gov.br``. Use `--all-conitec-pdfs` para aceitar também outros PDFs `gov.br` encontrados no crawl amplo.
download-clinical-exams
```

Manifestos: `llm/data/manifests/pcdt_index.jsonl`, `download_run.json`, `clinical_exams_index.jsonl`.

### Einstein (USP)

O repositório pode exigir **aceite de termos no navegador** antes do bitstream real. Se `clinical_exams_index.jsonl` mostrar `status=error` com mensagem HTML, conclua o fluxo manualmente no site e copie os arquivos para `llm/data/raw/clinical_exams/`, ou estenda o script com cookies de sessão.

Documentação do dataset: [docs/datasource_albert-einstein.md](../docs/datasource_albert-einstein.md)

## Documentação do pipeline RAG

Ver [docs/pipeline-rag.md](../docs/pipeline-rag.md).