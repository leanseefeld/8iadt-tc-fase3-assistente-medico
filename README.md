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
- sobe backend em `http://localhost:8000/docs`;
- sobe frontend em `http://localhost:5173`;
- grava logs em `.run-local-logs/`.

Comandos úteis:

```bash
# sem instalar dependências novamente
python run-local.py

# inclui build do vectorstore (requer ollama)
python run-local.py --setup --build-vectorstore

# portas customizadas
python run-local.py --backend-port 8001 --frontend-port 5174
```

Launcher para cada sistema:

```bat
run-local.bat
```

```bash
./run-local.sh
```

Os launchers usam `setup` por padrão e repassam parâmetros extras para o script Python:

```text
run-local.bat --build-vectorstore --backend-port 8001 --frontend-port 5174
./run-local.sh --build-vectorstore --backend-port 8001 --frontend-port 5174
```
