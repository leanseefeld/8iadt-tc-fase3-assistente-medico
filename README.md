Assistente Médico combinando LLM fine-tuned + RAG em uma interface web para auxílio em consultas e acompanhamento de pacientes.

Veja [llm/README.md](./llm/README.md) para executar a pipeline de ingestão de protocolos e criar a vector store Chroma inicial (ou cole uma existente no diretório `vectorstore/chroma`)

## Rodar tudo localmente (Windows/Linux/macOS)

Foi adicionado o script `run-local.py` na raiz do projeto para subir backend + frontend com um comando, sem depender de terminal específico.

1. Crie e ative seu ambiente virtual (`.venv` ou `ambiente_virtual`) e garanta que o Ollama esteja ativo (se usar RAG completo).
2. Na raiz do repositório, execute:

```bash
python run-local.py --setup
```

O script faz:
- instala dependências Python (`llm` e `backend`) e Node (`frontend`);
- aplica migrations e seed do banco;
- quando usado com `--build-vectorstore`, executa a pipeline RAG incluindo catálogo Conitec, limpeza dos PCDTs, chunking e Chroma;
- sobe backend em `http://localhost:8000/docs`;
- sobe frontend em `http://localhost:5173`;
- imprime os logs dos serviços diretamente no console.

Comandos úteis:

```bash
# sem instalar dependências novamente
python run-local.py

# inclui build das dependências do projeto
python run-local.py --setup

# inclui build do vectorstore (requer ollama)
python run-local.py --build-vectorstore

# no build do vectorstore, o catálogo Conitec é gerado antes dos chunks
# para enriquecer metadados de doença, diretriz, CID-10 e medicamentos

# instala dependências opcionais para chunking semântico
python run-local.py --setup --setup-semantic

# executa a pipeline RAG usando chunking semântico
python run-local.py --build-vectorstore --chunk-strategy semantic

# ajusta tamanho/overlap dos chunks sem editar código
python run-local.py --build-vectorstore --chunk-tokens 500 --overlap-tokens 80

# portas customizadas
python run-local.py --backend-port 8001 --frontend-port 5174

# não executar migrations
python run-local.py --skip-migrations
```

## Fluxo RAG do chat

O chat médico usa um grafo LangGraph com nós separados e auditáveis:

```text
load_memory
-> router_search_needed
   -> generate_direct_answer -> guardrail -> save_memory
   -> rewrite_query -> retrieve_attempt_1 -> rerank_and_validate_context
      -> generate_grounded_answer -> guardrail -> save_memory
      -> fallback_retrieve_attempt_2 -> rerank_and_validate_context
         -> generate_grounded_answer | generate_insufficient_context
         -> guardrail -> save_memory
```

O limite é `MEDICO_RAG_MAX_RETRIEVE_ATTEMPTS=2`: uma busca normal e uma busca de fallback no máximo. O `retrieve` só busca candidatos no Chroma; o `rerank_and_validate_context` filtra doença/diretriz, ordena e classifica o contexto como `sufficient`, `partial` ou `insufficient`; a geração clínica grounded só roda quando o contexto é suficiente.

Para depurar divergência entre frontend/backend e inspector, use:

```bash
cd llm
streamlit run scripts/rag_inspector_app.py
```

O inspector chama o mesmo serviço central de debug do backend (`run_full_graph_debug`) e mostra `memory_result`, `router_result`, `rewrite_result`, `retrieve_result`, `rerank_result`, fontes e `audit_trace` exportável.
