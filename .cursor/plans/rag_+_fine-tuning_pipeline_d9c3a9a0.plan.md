---
name: RAG + Fine-Tuning Pipeline
overview: "Master roadmap: PCDT extraction is implemented (JSONL sidecars + CLI). Remaining work — chunking from sidecars, optional [rag] deps for LangChain/Chroma/embeddings, RAG chain, SFT + QLoRA fine-tuning — is described below."
todos:
  - id: deps
    content: "Add LangChain/Chroma/finetune deps when implementing embed+RAG+SFT (optional [rag]/[finetune] groups or extend main deps — see Part Dependencies)"
    status: pending
  - id: extract
    content: "DONE — extract.py + extract-pcdt-markdown (sidecar *.pages.jsonl, optional combined .md)"
    status: completed
  - id: chunk
    content: "Implement pcdt_ingest/chunk.py — see .cursor/plans/pcdt_chunking_implementation.plan.md"
    status: pending
  - id: embed
    content: "Implement llm/src/pcdt_ingest/embed.py: bulk Chroma ingestion with nomic-embed-text via OllamaEmbeddings"
    status: pending
  - id: rag
    content: "Implement llm/src/pcdt_ingest/rag.py: LangChain LCEL RAG chain with ChatOllama + Chroma retriever"
    status: pending
  - id: sft
    content: "Implement llm/src/pcdt_ingest/sft.py: synthetic Q&A pair generation from chunks for SFT dataset"
    status: pending
  - id: finetune
    content: Document and implement QLoRA fine-tuning script using Unsloth on HuggingFace Gemma weights → GGUF export → Ollama import
    status: pending
isProject: false
---

# RAG + Fine-Tuning Strategy for Assistente Médico

## Context (updated)

- 132 PCDT PDFs live at `llm/data/raw/pcdt/` (via `download-pcdt`).
- **`gemma4:e4b-it-q4_K_M`** runs locally in Ollama.
- **Extraction is implemented** (see § Part 1 below): per-PDF **sidecar** `processed/pcdt/<stem>.pages.jsonl` (one JSON line per page: `page`, `markdown`), optional combined `*.md` via `--with-combined-md`, CLI **`extract-pcdt-markdown`**, run manifest `manifests/pcdt_md_extract.jsonl`, parallelism via **`--workers`**, incremental/skip logic.
- **`llm/pyproject.toml`** uses a **single** `[project.dependencies]` list (no optional groups today): core ingest stack includes `pymupdf4llm`, Playwright, pandas, pytest, **ruff** (dev linter folded into main install per “flatten deps” decision). **`pip install -e .`** from `llm/` installs everything listed there.
- **Still open**: chunking → embeddings → Chroma → RAG → SFT → QLoRA as in the sections below.

---

## Part 1 — PDF Extraction (done) & Chunking (next)

### Extraction — implemented

- **Library**: `pymupdf4llm` with **`page_chunks=True`** → list of per-page dicts (`text` + `metadata.page_number`).
- **Artifacts** (under `llm/data/processed/pcdt/`):
  - **Always**: `{stem}.pages.jsonl` — canonical **page-level** markdown for downstream **`page_range`** metadata.
  - **Optional**: `{stem}.md` — full concatenation for human review, only if CLI **`--with-combined-md`**.
- **CLI**: `extract-pcdt-markdown` — flags include `--with-combined-md`, `--force`, `--max-files`, `--only-manifest`, `--workers`, `--quiet` (see [`llm/README.md`](../../llm/README.md)).
- **Cleaning**: `clean_markdown()` per page (conservative footer/page-noise stripping).

### Chunking strategy (unchanged intent, input clarified)

PCDTs are long (~30–80 pages). Use a **two-pass** approach in `llm/src/pcdt_ingest/chunk.py`:

1. **First pass** — `MarkdownHeaderTextSplitter` on the **stitched document** built from `*.pages.jsonl` (preserve page order), splitting on `##` / `###` → metadata such as `section`, `source`.
2. **Second pass** — `RecursiveCharacterTextSplitter` (e.g. chunk_size≈800 tokens, overlap≈150) within each section so chunks fit the retriever/LLM.

**Page provenance**: while splitting, map character spans back to **page numbers** using the known per-page boundaries from the sidecar so each chunk gets **`page_range`** (or `page_start` / `page_end`), not only section title.

**Detailed implementation plan**: [`.cursor/plans/pcdt_chunking_implementation.plan.md`](pcdt_chunking_implementation.plan.md).

### Modules

| Module | Status | Role |
|--------|--------|------|
| [`llm/src/pcdt_ingest/extract.py`](../../llm/src/pcdt_ingest/extract.py) | **Done** | PDF → `*.pages.jsonl` (+ optional `*.md`) |
| `llm/src/pcdt_ingest/chunk.py` | **Todo** | Sidecar JSONL → `List[Document]` / exported chunks + metadata |

---

## Part 2 — Local Embeddings

### Recommended: `nomic-embed-text` via Ollama

The `OllamaEmbeddings` class from `langchain-ollama` keeps everything local and consistent with the same Ollama daemon already serving Gemma 4.

```python
from langchain_ollama import OllamaEmbeddings

embeddings = OllamaEmbeddings(model="nomic-embed-text", base_url="http://localhost:11434")
```

Pull the model once: `ollama pull nomic-embed-text`

**Alternative for better Portuguese quality**: `sentence-transformers` with `BAAI/bge-m3` (multilingual, 1024-dim, strong on PT-BR). Worth testing if retrieval quality is poor; it requires ~2 GB VRAM but runs on CPU.

---

## Part 3 — Vector Store

### Recommendation: Chroma (local, persistent, best DX for this project)

| | Chroma | Qdrant local | FAISS |
|---|---|---|---|
| Setup | `pip install chromadb` | `pip install qdrant-client[local]` | `pip install faiss-cpu` |
| Persistence | File-backed | File-backed | Manual save/load |
| Metadata filtering | Yes | Yes (richer) | No |
| LangChain integration | `langchain-chroma` (official) | `langchain-qdrant` (official) | `langchain-community` |
| Docs quality (2026) | Excellent | Excellent | Minimal |

**Choose Chroma** for this project: simpler, in-process (no background process), and `langchain-chroma` is a first-party integration. With 132 PDFs (~5k–15k chunks), Chroma handles it trivially.

**Switch to Qdrant** if you want production-grade filtering (e.g. filter by CID-10, disease, year) or plan to scale to larger corpora.

Persistent Chroma setup:

```python
from langchain_chroma import Chroma

vectorstore = Chroma(
    collection_name="pcdt",
    embedding_function=embeddings,
    persist_directory="llm/data/vectorstore/chroma",
)
```

### New module: `llm/src/pcdt_ingest/embed.py`

Responsible for: bulk ingestion of chunks into Chroma with deduplication by `source` filename.

---

## Part 4 — RAG Pipeline with LangChain + Ollama

### New module: `llm/src/pcdt_ingest/rag.py`

Standard retrieval-augmented generation chain:

```
User query
   │
   ▼
OllamaEmbeddings(nomic-embed-text)
   │
   ▼ similarity search (top-k=5)
Chroma vectorstore
   │ retrieved docs + sources
   ▼
PromptTemplate (RAG prompt, PT-BR, with citation instruction)
   │
   ▼
ChatOllama(model="gemma4:e4b-it-q4_K_M")
   │
   ▼
StrOutputParser → answer + sources
```

LangChain LCEL chain:

```python
from langchain_ollama import ChatOllama, OllamaEmbeddings
from langchain_chroma import Chroma
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.runnables import RunnablePassthrough
from langchain_core.output_parsers import StrOutputParser

llm = ChatOllama(model="gemma4:e4b-it-q4_K_M", temperature=0)
retriever = vectorstore.as_retriever(search_kwargs={"k": 5})

prompt = ChatPromptTemplate.from_template("""
Você é um assistente médico que responde com base em protocolos clínicos oficiais do CONITEC.
Responda apenas com base no contexto abaixo. Se não souber, diga "não encontrado no protocolo".
Sempre cite a fonte (nome do PCDT).

Contexto:
{context}

Pergunta: {question}
""")

chain = (
    {"context": retriever | format_docs, "question": RunnablePassthrough()}
    | prompt
    | llm
    | StrOutputParser()
)
```

---

## Part 5 — Fine-Tuning Gemma 4 with QLoRA

### Important caveat

The `gemma4:e4b-it-q4_K_M` in Ollama is a **4-bit GGUF** file — you cannot fine-tune it directly. Fine-tuning requires the original HuggingFace BF16/FP16 weights, which you then quantize and reimport into Ollama after training.

### Step-by-step workflow

**1. Get HuggingFace weights**

```bash
pip install huggingface-hub
huggingface-cli download google/gemma-3-4b-it --local-dir llm/models/gemma-3-4b-it
```

Requires accepting Google's license at [huggingface.co/google/gemma-3-4b-it](https://huggingface.co/google/gemma-3-4b-it).

**2. Build SFT dataset from PDFs**

New module `llm/src/pcdt_ingest/sft.py`:

- Consume **chunk** text (from Part 1 chunking) → generate Q&A pairs using the Ollama model as a "teacher"
- Prompt: *"Dado este trecho de protocolo clínico, gere 3 pares pergunta/resposta médica em português"*
- Output format: JSONL with `{"prompt": "...", "completion": "..."}` at `llm/data/sft/samples/`
- This is the "self-play" / synthetic data approach — no manual labeling needed

**3. QLoRA fine-tuning with Unsloth**

Unsloth is the most efficient local fine-tuning library for consumer GPUs (2x faster than HuggingFace PEFT, 60% less VRAM):

```python
from unsloth import FastLanguageModel
from trl import SFTTrainer
from transformers import TrainingArguments

model, tokenizer = FastLanguageModel.from_pretrained(
    model_name="llm/models/gemma-3-4b-it",
    max_seq_length=2048,
    load_in_4bit=True,
)

model = FastLanguageModel.get_peft_model(
    model,
    r=16,                     # LoRA rank
    target_modules=["q_proj", "k_proj", "v_proj", "o_proj",
                    "gate_proj", "up_proj", "down_proj"],
    lora_alpha=16,
    lora_dropout=0,
    bias="none",
)
```

Minimum VRAM: ~8 GB for 4B model with QLoRA. With 16 GB+ it runs comfortably.

**4. Export and reimport into Ollama**

```bash
# Convert merged model to GGUF
python llm_to_gguf.py --outfile llm/models/gemma3-pcdt-q4.gguf --outtype q4_k_m llm/models/gemma3-pcdt-merged/

# Create Modelfile
echo 'FROM ./llm/models/gemma3-pcdt-q4.gguf' > Modelfile

# Import into Ollama
ollama create gemma3-pcdt:latest -f Modelfile
```

---

## Dependency strategy for RAG / fine-tune stages

**Today**: `llm/pyproject.toml` lists **runtime + ingest + dev tools** in a single `[project.dependencies]` (including `pymupdf4llm`, Playwright, pandas, pytest, ruff).

**When implementing Parts 2–5**, add something like:

```toml
[project.optional-dependencies]
rag = [
    "langchain>=0.3",
    "langchain-core>=0.3",
    "langchain-ollama>=0.2",
    "langchain-chroma>=0.1",
    "langchain-text-splitters>=0.3",
    "chromadb>=0.6",
]
finetune = [
    "unsloth",
    "trl>=0.12",
    "datasets>=3.0",
    "transformers>=4.47",
    "peft>=0.14",
    "huggingface-hub>=0.25",
]
```

Install examples: `pip install -e ".[rag]"` and/or `pip install -e ".[finetune]"` **or** merge these into main `dependencies` if the project prefers a single flat install for CI (same tradeoff as the current base stack).

---

## Suggested module layout

```
llm/src/pcdt_ingest/
├── extract.py      # PDF → *.pages.jsonl (+ optional *.md) [DONE]
├── cli_extract.py  # extract-pcdt-markdown [DONE]
├── chunk.py        # *.pages.jsonl → chunks + metadata [TODO]
├── embed.py        # bulk Chroma ingestion [TODO]
├── rag.py          # LangChain RAG chain [TODO]
└── sft.py          # synthetic Q&A generation [TODO]
```

**Console scripts** (existing / planned):

- `extract-pcdt-markdown` → `pcdt_ingest.cli_extract:main` (**done**)
- `build-vectorstore` → `pcdt_ingest.embed:main` (planned)
- `generate-sft-data` → `pcdt_ingest.sft:main` (planned)
- Optional: `chunk-pcdt` → `pcdt_ingest.chunk:main` (see chunking plan)

---

## Potential inefficiencies to be aware of

- **Re-embedding on restart**: Chroma persists to disk, but `OllamaEmbeddings` has no batching by default. For 10k+ chunks, use `add_documents` in batches of 100 to avoid OOM in Ollama's embedding server.
- **GGUF fine-tune misconception**: Many tutorials claim you can fine-tune GGUF models via Ollama — you cannot. Always use HuggingFace weights for training.
- **SFT dataset size**: 132 PDFs may yield ~1k–3k Q&A pairs after dedup. That's enough for style/format adaptation but not for deep knowledge acquisition — which is exactly why RAG is the right complementary approach.
- **nomic-embed-text vs bge-m3**: `nomic-embed-text` was primarily trained on English. For PCDTs in Portuguese, `BAAI/bge-m3` may give meaningfully better recall. Worth running a quick retrieval evaluation on 20–30 hand-written queries before committing to the embedding model.
- **Parallel extraction**: `extract-pcdt-markdown --workers N` uses threads; very high `N` can memory-pressure PyMuPDF — tune per machine.
