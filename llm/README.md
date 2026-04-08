# Pacote `llm` — ingestão de dados para RAG

Este diretório contém o pacote Python **assistente-medico-llm**, com:

- **PCDT (CONITEC)**: script `download-pcdt` que lê a **tabela** da página oficial de listagem PCDT, baixa cada documento ligado na segunda coluna e grava PDFs em `llm/data/raw/pcdt/` e manifestos em `llm/data/manifests/` (`pcdt_index.jsonl`, `pcdt_run.json`). Uma única URL HTTP (sem crawl nem navegador headless para este fluxo).
- **Exames (Einstein / USP)**: script que obtém artefatos do [Dados COVID Hospital Israelita Albert Einstein](https://repositoriodatasharingfapesp.uspdigital.usp.br/handle/item/98) em `llm/data/raw/clinical_exams/` para exemplos de exames clínicos.

## Instalação

Na raiz do repositório (com venv ativado):

```bash
cd llm && pip install -e ".[dev]"
```

Opcional (somente para **download-clinical-exams** com navegador):

```bash
pip install -e ".[playwright]"
playwright install chromium
```

## Uso

```bash
download-pcdt --max-files 200
download-pcdt --quiet
```

Manifestos PCDT: `llm/data/manifests/pcdt_index.jsonl`, `llm/data/manifests/pcdt_run.json`.

```bash
download-clinical-exams              # abre navegador para aceite de termos (requer playwright)
download-clinical-exams --zip FILE   # extrai ZIP já baixado manualmente
```

### Einstein (USP)

O repositório exige **aceite de termos** (nome, e-mail e concordância) antes de liberar o download. Há duas opções:

#### Opção A — download automático (Playwright)

Requer a dependência opcional `playwright`:

```bash
pip install -e ".[playwright]"
playwright install chromium
```

Depois basta executar:

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
