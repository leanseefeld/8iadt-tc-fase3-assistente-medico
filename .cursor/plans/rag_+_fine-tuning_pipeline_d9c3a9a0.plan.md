---
name: RAG + Fine-Tuning Pipeline
overview: Build a complete RAG pipeline + SFT fine-tuning workflow for the medical assistant, covering PDF extraction, chunking, local embeddings, vector store ingestion, LangChain RAG agent, and QLoRA fine-tuning of Gemma 4 4B from the 132 PCDT PDFs already in `llm/data/raw/pcdt/`.
todos:
  - id: deps
    content: Add [rag] and [finetune] optional dependency groups to llm/pyproject.toml
    status: pending
  - id: extract
    content: "Implement llm/src/pcdt_ingest/extract.py: PDF → clean markdown with pymupdf4llm"
    status: pending
  - id: chunk
    content: "Implement llm/src/pcdt_ingest/chunk.py: two-pass MarkdownHeader + RecursiveCharacter splitter"
    status: pending
  - id: embed
    content: "Implement llm/src/pcdt_ingest/embed.py: bulk Chroma ingestion with nomic-embed-text via OllamaEmbeddings"
    status: pending
  - id: rag
    content: "Implement llm/src/pcdt_ingest/rag.py: LangChain LCEL RAG chain with ChatOllama + Chroma retriever"
    status: pending
  - id: sft
    content: "Implement llm/src/pcdt_ingest/sft.py: synthetic Q&A pair generation from PDF chunks for SFT dataset"
    status: pending
  - id: finetune
    content: Document and implement QLoRA fine-tuning script using Unsloth on HuggingFace Gemma weights → GGUF export → Ollama import
    status: pending
isProject: false
---

# RAG + Fine-Tuning Strategy for Assistente Médico

## Context

- 132 PCDT PDFs are already at `llm/data/raw/pcdt/`
- `gemma4:e4b-it-q4_K_M` is running locally in Ollama
- The `llm/` package has directory stubs (`chunks/pcdt`, `processed/pcdt`, `sft/samples`) but no code filling them yet
- `llm/pyproject.toml` has no RAG or ML training dependencies yet

---

## Part 1 — PDF Extraction & Chunking

### Library choice: `pymupdf4llm`

PyMuPDF renders PDFs to markdown (preserving headings, tables, lists), which is far better for PCDTs than raw text extraction from `pypdf` or `pdfplumber`. PCDTs have structured sections (Diagnóstico, Tratamento, Posologia) that map well to markdown headers.

```python
import pymupdf4llm
md_text = pymupdf4llm.to_markdown("path/to/pcdt.pdf")
```

### Chunking strategy: two-pass splitter

PCDTs are long (~30-80 pages) with dense clinical sections. Use a two-pass approach in `llm/src/pcdt_ingest/chunk.py`:

1. **First pass** — `MarkdownHeaderTextSplitter` splits on `##` and `###` headers → preserves clinical section context in each chunk's metadata (e.g. `{"section": "Tratamento", "source": "pcdt-artrite.pdf"}`)
2. **Second pass** — `RecursiveCharacterTextSplitter(chunk_size=800, chunk_overlap=150)` on each section to limit token length

800 tokens is a practical sweet spot: fits within Gemma 4's context, contains enough clinical detail, and avoids retrieval noise from over-large chunks.

### New module: `llm/src/pcdt_ingest/extract.py`

Responsible for: `pdf → clean markdown` (strip footers/headers, page numbers via regex).

### New module: `llm/src/pcdt_ingest/chunk.py`

Responsible for: `markdown → List[Document]` with metadata (`source`, `section`, `page_range`).

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

**Choose Chroma** for this project: simpler, in-process (no background process), and `langchain-chroma` is a first-party integration. With 132 PDFs (~5k-15k chunks), Chroma handles it trivially.

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
- Extract chunk text → generate Q&A pairs using the Ollama model itself as a "teacher"
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

## Dependency additions to `llm/pyproject.toml`

Two new optional groups:

```toml
[project.optional-dependencies]
rag = [
    "pymupdf4llm>=0.0.17",
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

Install: `pip install -e ".[rag]"` or `pip install -e ".[finetune]"`

---

## Suggested module layout

```
llm/src/pcdt_ingest/
├── extract.py      # PDF → markdown (new)
├── chunk.py        # markdown → List[Document] (new)
├── embed.py        # bulk Chroma ingestion (new)
├── rag.py          # LangChain RAG chain (new)
└── sft.py          # synthetic Q&A generation (new)
```

New console scripts in `pyproject.toml`:
- `build-vectorstore` → `pcdt_ingest.embed:main`
- `generate-sft-data` → `pcdt_ingest.sft:main`

---

## Potential inefficiencies to be aware of

- **Re-embedding on restart**: Chroma persists to disk, but `OllamaEmbeddings` has no batching by default. For 10k+ chunks, use `add_documents` in batches of 100 to avoid OOM in Ollama's embedding server.
- **GGUF fine-tune misconception**: Many tutorials claim you can fine-tune GGUF models via Ollama — you cannot. Always use HuggingFace weights for training.
- **SFT dataset size**: 132 PDFs may yield ~1k-3k Q&A pairs after dedup. That's enough for style/format adaptation but not for deep knowledge acquisition — which is exactly why RAG is the right complementary approach.
- **nomic-embed-text vs bge-m3**: `nomic-embed-text` was primarily trained on English. For PCDTs in Portuguese, `BAAI/bge-m3` may give meaningfully better recall. Worth running a quick retrieval evaluation on 20-30 hand-written queries before committing to the embedding model.
