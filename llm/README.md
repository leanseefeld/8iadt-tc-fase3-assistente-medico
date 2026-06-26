# Pacote `llm` — ingestão de dados para RAG

Este diretório contém o pacote Python **assistente-medico-llm**, com:

- **PCDT (CONITEC)**: script `download-pcdt` que lê a **tabela** da página oficial de listagem PCDT, baixa cada documento ligado na segunda coluna e grava PDFs em `llm/data/raw/pcdt/` e manifestos em `llm/data/manifests/` (`pcdt_index.jsonl`, `pcdt_run.json`). Uma única URL HTTP (sem crawl nem navegador headless para este fluxo).
- **Exames (Einstein / USP)**: script que obtém artefatos do [Dados COVID Hospital Israelita Albert Einstein](https://repositoriodatasharingfapesp.uspdigital.usp.br/handle/item/98) em `llm/data/raw/clinical_exams/` para exemplos de exames clínicos. (não utilizado na entrega final)

## Fine tuning

Para informações sobre o processo de ajuste do modelo, consulte [fine-tuning/README.md](./fine-tuning/README.md).

## Análise de tokens

Para uma análise de uso de tokens em uma base chroma já construída, use o notebook [chroma_llama_token_analysis.ipynb](./chroma_llama_token_analysis.ipynb)

## Instalação

Na raiz do repositório (com venv ativado):

```bash
cd llm && pip install -e .
```

O chunking semântico é opcional. Como ele usa o mesmo embedding local do Ollama (`nomic-embed-text`), o extra `semantic` não instala PyTorch ou SentenceTransformers:

```bash
pip install --upgrade pip
pip install -e "llm[semantic]"
ollama pull nomic-embed-text
```

Para reconhecimento biomédico no chat médico, o medSpaCy com modelo em português (`pt_core_news_sm`) é obrigatório. O `--setup` do orquestrador baixa o modelo automaticamente se ainda não estiver instalado:

```bash
python run-local.py --setup
```

Para instalar manualmente:

```bash
python -m spacy download pt_core_news_sm
```

O backend usa o resolvedor clínico próprio com medSpaCy NER em português para resolver entidades clínicas na query antes da busca; se o modelo não estiver disponível, registra erro e continua com fallback pelo catálogo Conitec local.

Para usar o download Einstein com navegador (Playwright), instale também o Chromium:

```bash
playwright install chromium
```

Você também precisará de [Ollama](https://ollama.com/) executando localmente com `nomic-embed-text` para conseguir os embeddings:

```bash
ollama pull nomic-embed-text
```

## Uso

Veja as subseções seguintes para explicação de cada comando - incluindo formas de visualizar artefatos intermediários - ou execute estes comando em sequência para completar a pipeline localmente:

```bash
download-pcdt
build-conitec-catalog
download-clinical-exams # Opcional: caso queira o dataset Albert Einstein
extract-pcdt-markdown --workers 6
clean-pcdt-extracted --workers 6
chunk-pcdt --workers 6
build-vectorstore
```

### Download de arquivos

```bash
download-pcdt --max-files 200
download-pcdt --quiet
```

Manifestos PCDT: `llm/data/manifests/pcdt_index.jsonl`, `llm/data/manifests/pcdt_run.json`.

### Catálogo Conitec PCDT/CID/medicamentos

O campo `disease` dos chunks pode ser enriquecido a partir da planilha oficial da Conitec com diretrizes, CID-10 e medicamentos. O comando abaixo baixa a planilha apenas quando executado explicitamente e gera um cache local em `llm/data/processed/conitec/pcdt_catalog.jsonl`:

```bash
build-conitec-catalog
python -m pcdt_ingest.cli_conitec_catalog --input /caminho/medicamentos_cid_pcdt_atual-1.xlsx
python -m pcdt_ingest.cli_conitec_catalog --output llm/data/processed/conitec/pcdt_catalog.jsonl
```

Se o catálogo local existir, `chunk-pcdt` o carrega automaticamente. Também é possível apontar outro JSONL ou desativar o enriquecimento:

```bash
chunk-pcdt --force --conitec-catalog llm/data/processed/conitec/pcdt_catalog.jsonl
chunk-pcdt --no-conitec-catalog
```

Para reprocessar a base RAG após atualizar o catálogo, rode:

```bash
build-conitec-catalog
chunk-pcdt --force --workers 6
build-vectorstore --force
```

O matching compara o nome do PDF com a `Diretriz` normalizada da planilha, removendo datas e termos genéricos como `pcdt`, `protocolo`, `diretriz` e `relatorio`. Quando não há match confiável, a heurística antiga de doença continua sendo usada.

### Extração Markdown (PCDT)

Converte cada PDF em `llm/data/raw/pcdt/` para um **sidecar JSONL** por documento: `llm/data/processed/pcdt/<nome>.pages.jsonl` (uma linha JSON por página, campos `page` e `markdown`).

```bash
extract-pcdt-markdown
extract-pcdt-markdown --max-files 5
extract-pcdt-markdown --only-manifest
extract-pcdt-markdown --force
extract-pcdt-markdown --workers 4   # vários PDFs em paralelo (uma thread por ficheiro)
```

O arquivo **Markdown combinado** (`processed/pcdt/<nome>.md`, todas as páginas em sequência) **só** é gerado se usar a flag:

```bash
extract-pcdt-markdown --with-combined-md
```

Manifesto desta extração: `llm/data/manifests/pcdt_md_extract.jsonl` (uma linha por PDF processado, com caminhos relativos a `llm/data/`, `wrote_combined_md`, `status`, etc.).

### Limpeza dos sidecars extraídos (PCDT)

Após a extração, a etapa de limpeza lê `processed/pcdt/<nome>.pages.jsonl` e grava `processed/pcdt_cleaned/<nome>.pages.cleaned.jsonl`. O conteúdo gravado preserva o mesmo formato de entrada (`page`, `markdown` e demais campos originais), alterando apenas o `markdown` para a versão limpa. Assim, os sidecars brutos continuam segregados em `processed/pcdt/` e os limpos ficam em `processed/pcdt_cleaned/`.

A limpeza remove ruídos comuns da extração de PDFs diagramados:

- placeholders de imagem (`picture`, `intentionally omitted`, `pixmap`, `<IMAGE`, `image omitted`);
- assinaturas administrativas conhecidas;
- números de página isolados;
- headers/footers repetidos detectados pelas primeiras/últimas linhas das páginas;
- tabelas de índice/sumário e linhas com dot leaders;
- quebras de palavra por hífen no fim de linha;
- `<br>` e quebras internas em tabelas Markdown;
- sumários/índices com pontilhado, legendas de figuras e tabelas de estratégia de busca bibliográfica;
- seções finais não clínicas, como `REFERÊNCIAS`, `ANEXO(S)` e `APÊNDICE(S)`, incluindo páginas seguintes;
- formulários de assinatura, checkboxes de medicamentos e notas administrativas isoladas;
- tabelas OCR malformadas com cabeçalhos quebrados/repetidos;
- excesso de espaços, caracteres invisíveis e linhas vazias;
- páginas administrativas iniciais antes do início clínico quando detectável.

Uso padrão:

```bash
clean-pcdt-extracted
clean-pcdt-extracted --max-files 10
clean-pcdt-extracted --force
clean-pcdt-extracted --workers 4
clean-pcdt-extracted --dry-run --verbose
```

Opções úteis:

```bash
clean-pcdt-extracted --header-footer-threshold 0.6
clean-pcdt-extracted --min-words 8
clean-pcdt-extracted --input llm/data/processed/pcdt/arquivo.pages.jsonl --output /tmp/arquivo.pages.cleaned.jsonl
```

No modo `--dry-run`, nenhum arquivo é gravado; a CLI apenas mostra o resumo de páginas analisadas, páginas ignoradas e linhas removidas. Em execução normal, o manifesto fica em `llm/data/manifests/pcdt_clean_index.jsonl`.

### Fragmentação de chunks (PCDT)

Após ler `processed/pcdt_cleaned/<nome>.pages.cleaned.jsonl` quando existir, ou `processed/pcdt/<nome>.pages.jsonl` como fallback, gera `chunks/pcdt/<nome>.chunks.jsonl` (uma linha por chunk: `text` + `metadata`). O processo costura as páginas em texto contínuo antes da fragmentação, usa os spans globais apenas para calcular `page_start`, `page_end` e `page_range`, e normaliza títulos típicos dos PCDTs para melhorar `section`, `header_1` e `header_2`.

O modo padrão continua sendo `recursive`, com `MarkdownHeaderTextSplitter` + `RecursiveCharacterTextSplitter`:

```bash
chunk-pcdt
chunk-pcdt --max-files 10
chunk-pcdt --only-manifest
chunk-pcdt --force
chunk-pcdt --workers 4
chunk-pcdt --chunk-strategy recursive
```

Também há o modo `semantic`, que usa `SemanticChunker` com o mesmo embedding local da indexação (`nomic-embed-text` via Ollama) dentro de cada seção lógica. Se um chunk semântico ficar grande demais, ele é quebrado com o fallback recursivo.

```bash
python -m pcdt_ingest.cli_chunk --force --chunk-strategy semantic
python -m pcdt_ingest.cli_chunk --force --max-files 2 --chunk-strategy semantic
python -m pcdt_ingest.cli_chunk --force --chunk-strategy semantic --chunk-tokens 500 --overlap-tokens 80
```

O modo `semantic` requer as dependências opcionais descritas na seção de instalação. Se elas não estiverem instaladas, a CLI retorna uma mensagem com os comandos necessários.

Os defaults da pipeline RAG ficam centralizados em `llm/config.py`, incluindo estratégia de chunking, tamanho de chunk, overlap, percentil semântico, URL do Ollama, modelo de embedding e batch size de indexação.

Metadata principal dos chunks:

- `source_stem`, `source_pdf`;
- `section`, `header_1`, `header_2`;
- `page_start`, `page_end`, `page_range`;
- `chunk_index`, `chunk_strategy`;
- `disease`, `disease_normalized`, `metadata_source`;
- quando houver match no catálogo Conitec: `diretriz`, `formato`, `cid10_codes`, `cid10_descriptions`, `medicamentos`, `portarias`, `datas_portaria`, `descricao_siglas`;

Esses metadados permitem ao chat resolver candidatos de catálogo, expandir a query de forma restritiva e filtrar/reranquear documentos por diretriz, doença e seção. Por exemplo, um PDF `20210428_pcdt_artrite_reativa.pdf` passa a receber `disease = "Artrite Reativa"` e `metadata_source = "conitec_xlsx"` quando a diretriz está no catálogo.

Manifesto: `llm/data/manifests/pcdt_chunk_index.jsonl`.

#### Visualizador de chunks PCDT (browser)

Interface HTML estática em `[tools/pcdt-chunks-viewer/index.html](tools/pcdt-chunks-viewer/index.html)` (lista documentos a partir de `pcdt_chunk_index.jsonl`, navegação por chunk, PDF, modo raw/preview Markdown). O detalhe de cada chunk destaca os campos do catálogo Conitec quando presentes: `metadata_source`, `disease_normalized`, `diretriz`, `formato`, `cid10_codes`, `cid10_descriptions`, `medicamentos`, `portarias`, `datas_portaria` e `descricao_siglas`.

Após `pip install -e .`, o comando a seguir sobe um servidor HTTP na raiz do pacote `llm/` e exibe a URL para o acessar o visualizador:

```bash
view-pcdt-chunks
# opcional: --port 8765 --bind 127.0.0.1
```

Alternativa manual: `cd llm && python -m http.server 8765` e no browser abra `http://127.0.0.1:8765/tools/pcdt-chunks-viewer/index.html` (é necessário servir `llm/`, não só `llm/data/`, para o `fetch` ao manifest e aos JSONL funcionar).

### Vector store (Chroma + Ollama)

Com os arquivos `chunks/pcdt/<nome>.chunks.jsonl` e o manifesto `pcdt_chunk_index.jsonl`, indexa os chunks em uma base Chroma em `vectorstore/chroma/` **na raiz do repositório** (fora de `llm/data/`, para não perder embeddings ao limpar dados de ingestão). Requer [Ollama](https://ollama.com/) em execução com o modelo de embeddings:

```bash
ollama pull nomic-embed-text
build-vectorstore
build-vectorstore --max-files 5
build-vectorstore --force
build-vectorstore --verbose # Converte para tokens antes de armazenar (não durante) e exibe número de tokens por chunk
```

Opcional: variável de ambiente `OLLAMA_BASE_URL` (por padrão `http://127.0.0.1:11434`). O manifesto `llm/data/manifests/pcdt_embed_index.jsonl` regista o último estado por documento e permite execuções incrementais; use `--skip-embed-manifest` para desativar. O diretório `vectorstore/` está no `.gitignore`.

#### Visualizar a coleção Chroma (CLI)

Com venv ativo e `pip install -e .`, use o binário `chroma` do pacote `chromadb`. Na **raiz do repositório**:

```bash
chroma run --path vectorstore/chroma   # terminal 1 — servidor local
chroma browse pcdt --local             # terminal 2 — TUI da coleção
```

Se o `browse` não funcionar, tente `chroma browse pcdt --local --path vectorstore/chroma`.

### RAG Inspector

O app Streamlit `scripts/rag_inspector_app.py` permite depurar retrieve, prompt, geração e tempos sem iniciar backend/frontend:

```bash
cd llm
ollama pull llama3.2:3b
streamlit run scripts/rag_inspector_app.py
```

O modo principal do Inspector chama `run_full_graph_debug`, o mesmo serviço central usado pelo fluxo real do chat para memória, router, rewrite, retrieve, rerank e decisão de suficiência. Assim, a mesma query deve produzir o mesmo `expanded_query`, `structured_terms`, documentos selecionados e `context_quality` que o endpoint `POST /api/assistant/chat`.

Campos exibidos:

- `memory_result`: histórico/transcript e últimos `structured_terms` usados para follow-up.
- `router_result`: decisão `search_needed` e tipo da pergunta.
- `rewrite_result`: `resolved_query`, `expanded_query`, `structured_terms`, entidades e candidatos do catálogo.
- `rewrite_result.llm_rewrite_used`: indica se o rewrite conversacional por LLM foi usado.
- `rewrite_result.spacy_used`: indica se medSpaCy (`pt_core_news_sm`) participou da resolução clínica.
- `retrieve_result`: query enviada ao Chroma, filtro de metadata, tentativa, collection, persist dir e modelo de embedding.
- `rerank_result`: `context_quality`, `failure_type`, documentos removidos/selecionados, seções esperadas/encontradas e saída do LLM rerank quando habilitado.
- `audit_trace`: trilha append-only por etapa, exportável na aba **Exportar JSON**.

Diferença importante: `expanded_query` é texto limpo para busca vetorial; `structured_terms` carrega doença, CID, intenção, seção preferencial e candidatos em formato estruturado para filtros, rerank, prompt e auditoria. Não coloque JSON na query vetorial.

O Inspector usa `llama3.2:3b` como modelo de chat padrão para geração. O campo continua editável na sidebar, mas não há fallback automático para outro modelo; se a geração falhar, o erro do modelo selecionado é exibido diretamente.

Export de auditoria:

```bash
streamlit run scripts/rag_inspector_app.py -- --export-audit /tmp/rag-audit.json
```

Quando esse argumento é informado, a última execução grava o `audit_trace` completo no caminho indicado. A aba **Exportar JSON** também oferece download do payload completo e do `audit_trace`.

### RAG Eval (avaliação comparativa de retrieval)

`scripts/rag_eval_multiquery.py` mede hit-rate@k sobre um conjunto curado de perguntas clínicas (`llm/data/eval/rag_questions.jsonl`) e compara quatro caminhos de busca:

| Caminho | Descrição |
|---------|-----------|
| **1q** | `similarity_search_with_score(pergunta, k)` — baseline direto |
| **Nq** | Union dos resultados individuais das N queries geradas por CoT |
| **RRF** | Fusão das N queries por Reciprocal Rank Fusion |
| **1q+Nq** | RRF de [pergunta original + N queries CoT] — **caminho padrão do agente** |

Após `pip install -e .` no pacote `llm/` (ou `uv sync`), o comando `eval-rag` fica disponível:

```bash
eval-rag                                      # avaliação completa, saída resumida
eval-rag --docs                               # + tabela de chunks do caminho padrão (1q+Nq via RRF)
eval-rag --docs-single --docs --docs-combined # todos os caminhos visíveis
eval-rag --k 10 --docs 10                     # top-10
```

Alternativa sem instalar (backend como ambiente de execução):

```bash
uv run --project backend python llm/scripts/rag_eval_multiquery.py --docs
```

Opções principais:

| Flag | Padrão | Descrição |
|------|--------|-----------|
| `--k N` | `rag_retrieve_final_k` do `.env` | Top-k avaliado |
| `--docs [N]` | — | Tabela de chunks do caminho RRF (N=6 sem valor) |
| `--docs-single [N]` | — | Tabela de chunks do caminho 1q |
| `--docs-nq [N]` | — | Tabela de chunks do caminho Nq (union) |
| `--docs-combined [N]` | — | Tabela de chunks do caminho 1q+Nq |
| `--eval-file PATH` | `llm/data/eval/rag_questions.jsonl` | JSONL de perguntas curadas |
| `--env-file PATH` | `backend/.env` | `.env` com credenciais/modelo |
| `--runs-dir PATH` | `llm/data/eval/runs/` | Diretório de persistência dos runs |

A saída no terminal usa Rich com hierarquia visual: CoT do planner em painel dim, queries em magenta, badge verde/vermelho por caminho e tabelas com stem/seção/score/campeão (query que levou ao doc no topo da sua busca individual).

Cada execução persiste um JSONL em `llm/data/eval/runs/run_<timestamp>.jsonl` com stems, hits, queries geradas, raciocínio CoT, saída raw do LLM e detalhes de cada chunk retornado por caminho — útil para comparar configurações de modelo entre runs.

Pré-requisitos: Chroma populado (`build-vectorstore`), Ollama com `nomic-embed-text` para embeddings, LLM de chat acessível conforme `backend/.env`.

### Dataset COVID Albert Einstein

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

1. Acesse [https://repositoriodatasharingfapesp.uspdigital.usp.br/handle/item/98](https://repositoriodatasharingfapesp.uspdigital.usp.br/handle/item/98) no navegador.
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
