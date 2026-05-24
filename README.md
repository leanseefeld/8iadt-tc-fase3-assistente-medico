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

# opcional: scispaCy (EntityLinker); em Python 3.14 use 3.11–3.13 ou omita (há fallback no chat)
python run-local.py --setup --setup-scispacy

# executa a pipeline RAG usando chunking semântico
python run-local.py --build-vectorstore --chunk-strategy semantic

# ajusta tamanho/overlap dos chunks sem editar código
python run-local.py --build-vectorstore --chunk-tokens 500 --overlap-tokens 80

# portas customizadas
python run-local.py --backend-port 8001 --frontend-port 5174

# não executar migrations
python run-local.py --skip-migrations
```
