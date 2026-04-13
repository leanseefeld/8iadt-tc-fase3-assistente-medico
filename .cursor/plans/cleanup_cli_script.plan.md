---
name: Cleanup CLI script
overview: "CLI `clean-pcdt-data`: cada etapa expõe `cleanup_targets` no módulo que gera artefactos; `cli_clean` só agrega, confirma e executa I/O; `--reset-after`, flags granulares, `--chroma` explícito; `--dry-run` / TTY / `--yes`."
todos:
  - id: cleanup-targets-modules
    content: "Adicionar `cleanup_targets(data_root)` (ou nome alinhado) em `pcdt_download`, `extract`, `chunk`, `embed`, `exams_fetch`; SFT ver nota no plano"
    status: pending
  - id: cli-clean-module
    content: "Implementar `cli_clean.py`: importar e agregar targets, dedupe, flags, `--reset-after`, exclusões mútuas, execução rmtree/unlink"
    status: pending
  - id: pyproject-script
    content: "Registar `clean-pcdt-data` em `llm/pyproject.toml`"
    status: pending
  - id: tests-cli-clean
    content: "Testes: funções `cleanup_targets` por módulo (paths estáveis); agregação `--reset-after` no CLI ou helper puro; non-TTY"
    status: pending
  - id: readme-devlog
    content: "`llm/README.md` (pt-BR) + `docs/dev-log/INDEX.md`"
    status: pending
isProject: true
---

# Plano: CLI de limpeza (`clean-pcdt-data`)

## Origem

Requisitos base no follow-up de [embeddings_+_chroma_78fa139f.plan.md](./embeddings_+_chroma_78fa139f.plan.md) (secção “script de limpeza”).

## Comando principal pedido: “apagar tudo depois da etapa X” (sem Chroma implícito)

**Sugestão (legível e alinhada ao README):**

```bash
clean-pcdt-data --reset-after extract --dry-run   # pré-visualizar
clean-pcdt-data --reset-after extract --yes       # executar (não-TTY ou saltar prompt)
```

- **`--reset-after <stage>`** — Remove **tudo o que o pipeline PCDT produz *depois*** dessa etapa ficar concluída, **mantendo** PDFs + manifestos + pastas **até e incluindo** essa etapa.
- **`vectorstore/chroma/` nunca** entra neste mapeamento; só some com **`--chroma`** (explícito).
- Combinação típica para “recomeçar embeddings mas manter chunks”:  
  `clean-pcdt-data --reset-after chunk`  
  (remove só `pcdt_embed_index.jsonl`; em seguida `build-vectorstore`. Para apagar a coleção Chroma inteira, usar `--chroma` no mesmo comando ou à parte.)

### Nomes de etapa (`<stage>`)

| `stage` | Mantém (não apaga) | Apaga (além do que está à direita nas linhas abaixo) |
|---------|----------------------|------------------------------------------------------|
| `download` | `raw/pcdt/`, `manifests/pcdt_index.jsonl`, `manifests/pcdt_run.json` | `processed/pcdt/`, `chunks/pcdt/`, `pcdt_md_extract.jsonl`, `pcdt_chunk_index.jsonl`, `pcdt_embed_index.jsonl` |
| `extract` | tudo acima + `processed/pcdt/` + `pcdt_md_extract.jsonl` | `chunks/pcdt/`, `pcdt_chunk_index.jsonl`, `pcdt_embed_index.jsonl` |
| `chunk` | tudo acima + `chunks/pcdt/` + `pcdt_chunk_index.jsonl` | `pcdt_embed_index.jsonl` apenas |

Não há `embed` como `stage`: depois do chunk o único artefacto em `llm/data` é o manifesto de embed; isso já é coberto por `chunk`. Para só apagar o índice incremental use `--embed-manifest`. Vetores: sempre `--chroma`.

Constantes de ficheiros: `MANIFEST_*` em [`llm/src/pcdt_ingest/paths.py`](../llm/src/pcdt_ingest/paths.py).

**Alias opcional:** `raw` como sinónimo de `download` (bom mnemónico).

### Fora do `--reset-after` (PCDT)

- **`raw/clinical_exams/`**, **`sft/samples/`**, manifestos Einstein — **não** fazem parte da cadeia PCDT acima; continuam só com flags explícitas (`--clinical-exams`, `--sft-samples`, …) ou com `--i-understand-delete-all-llm-data`.

### Exclusões mútuas

- **`--reset-after`** incompatível com **`--i-understand-delete-all-llm-data`** e com flags granulares que sobreponham o mesmo alvo (validar no `argparse` / após parse e sair com mensagem em pt-BR).
- **`--chroma`** pode combinar com **`--reset-after`** (ex.: reprocessar pipeline e limpar vetores na mesma corrida).

## Confirmação (decisão do utilizador)

- **TTY:** prompt; aceitar `yes` / `sim`.
- **Não-TTY:** obrigatório **`--yes`** ou erro claro em pt-BR.
- **`--dry-run`:** só listar caminhos; sem apagar; sem confirmação.

## Flags granulares (mantidas)

Úteis para casos pontuais ou scripts: `--raw-pcdt`, `--processed-pcdt`, `--chunks`, `--manifests`, `--embed-manifest`, `--clinical-exams`, `--sft-samples`, `--i-understand-delete-all-llm-data`, `--chroma`, `--dry-run`, `--yes`, `--quiet`.

## Responsabilidade dos módulos (não redesclarar caminhos no CLI)

Cada passo do pipeline **expõe uma função pura** que devolve os artefactos **que esse módulo cria** (para o CLI juntar, mostrar em `--dry-run` e apagar). O CLI **não** duplica constantes de `paths.py` nem listas de manifestos por etapa.

**Contrato sugerido (ajustar nomes na implementação, manter semântica):**

- Assinatura comum: `cleanup_targets(data_root: Path) -> tuple[frozenset[Path], frozenset[Path]]` **(dirs, files)** — caminhos absolutos ou relativos a `data_root` resolvidos de forma consistente (recomendado: sempre `data_root / …` resolvido com `.resolve()` na agregação final).
- **Sem efeitos secundários** nestas funções: só descrevem o conjunto; `cli_clean` faz `rmtree` / `unlink` após confirmação.
- **Documentar** em docstring (pt-BR) que são os artefactos gerados por aquele módulo, para manutenção quando o pipeline evoluir.

| Etapa / domínio | Módulo | O que a função deve incluir |
|-----------------|--------|---------------------------|
| Download PCDT | [`pcdt_download.py`](../llm/src/pcdt_ingest/pcdt_download.py) | Diretório `DIR_RAW_PCDT`; ficheiros `MANIFEST_PCDT_INDEX`, `MANIFEST_PCDT_RUN` sob `DIR_MANIFESTS` |
| Extração MD | [`extract.py`](../llm/src/pcdt_ingest/extract.py) | Diretório `DIR_PROCESSED_PCDT`; ficheiro `MANIFEST_PCDT_MD_EXTRACT` |
| Chunks PCDT | [`chunk.py`](../llm/src/pcdt_ingest/chunk.py) | Diretório `DIR_CHUNKS_PCDT`; ficheiro `MANIFEST_PCDT_CHUNK` |
| Embeddings / índice embed | [`embed.py`](../llm/src/pcdt_ingest/embed.py) | Ficheiro `MANIFEST_PCDT_EMBED`; **função separada** para o Chroma, p.ex. `chroma_cleanup_targets() -> frozenset[Path]` devolvendo só `vectorstore_chroma_dir()` (usa [`paths.vectorstore_chroma_dir`](../llm/src/pcdt_ingest/paths.py) por baixo — o “dono” semântico continua a ser o fluxo de embed) |
| Exames clínicos | [`exams_fetch.py`](../llm/src/pcdt_ingest/exams_fetch.py) | Diretório `DIR_RAW_CLINICAL_EXAMS`; `MANIFEST_CLINICAL_EXAMS_INDEX`, `MANIFEST_CLINICAL_EXAMS_RUN` |
| Amostras SFT | — | Ainda **sem** módulo de geração dedicado no repo; até lá, **uma** função mínima (p.ex. em [`paths.py`](../llm/src/pcdt_ingest/paths.py) com docstring `TODO: mover quando existir ingestão SFT`) ou ficheiro `sft_samples.py` só com `cleanup_targets`, para não espalhar listas no CLI |

**`--reset-after <stage>`** implementa-se **compondo** estas funções (união de conjuntos), **sem** incluir `chroma_cleanup_targets` salvo flag `--chroma`:

- `download` — união de targets de extract + chunk + embed (só parte `llm/data` de embed, i.e. manifesto embed).
- `extract` — união de chunk + embed (manifesto embed).
- `chunk` — só targets de embed (manifesto embed).

**Flags granulares** mapeiam 1:1 para a função do módulo correspondente (e `--chroma` chama só a função Chroma de `embed`).

**`--manifests`** (apagar pasta inteira `DIR_MANIFESTS`) é transversal: pode ficar como **única** exceção no `cli_clean` com justificativa em comentário (múltiplos autores) **ou** helper em [`paths.py`](../llm/src/pcdt_ingest/paths.py) tipo `all_manifests_dir_target(data_root)` para não hardcodar segmentos no CLI.

**`--i-understand-delete-all-llm-data`** — continua a ser `data_root` completo; não precisa de composição (mensagem de aviso forte no CLI).

## Implementação do CLI

- Novo módulo [`llm/src/pcdt_ingest/cli_clean.py`](../llm/src/pcdt_ingest/cli_clean.py): `argparse`, validação de exclusões mútuas, agregação de `frozenset`s, dedupe, impressão, confirmação TTY / `--yes`, `--dry-run`.
- Execução: `shutil.rmtree` em diretórios; `unlink` em ficheiros; idempotente se ausente.
- Logging: [`logutil.py`](../llm/src/pcdt_ingest/logutil.py).

## Testes

- Mapeamento por `stage` (paths esperados).
- `--reset-after chunk` não inclui `vectorstore`.
- Conflito de flags; non-TTY sem `--yes`.

## Documentação

- Parágrafo em [`llm/README.md`](../llm/README.md) com exemplos `--reset-after` e `--chroma` separado.
- Linha em [`docs/dev-log/INDEX.md`](../docs/dev-log/INDEX.md) após implementação.

## Ineficiências / follow-up

- Se no futuro existir mais de um motor em `vectorstore/`, avaliar flag `--vectorstore` além de `--chroma`.
