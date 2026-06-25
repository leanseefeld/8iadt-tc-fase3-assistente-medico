# Assistente Médico IA

Monorepo de um assistente médico para apoio à decisão clínica (RAG + LangGraph + guardrails).

## Estrutura

- `backend/` — API FastAPI: chat clínico via LangGraph + RAG (Chroma), SSE, alertas clínicos, persistência SQLite (Alembic). Código em `backend/src/assistente_medico_api/`.
- `frontend/` — SPA "Assistente Médico" (Vite + TypeScript), fachada `clinicalApi`.
- `llm/` — pipeline RAG (download de PCDTs da Conitec, dataset COVID, chunking, ingestão Chroma) e fine-tuning (SFT em Llama 3.2 via Unsloth/MLX).
- `docs/` — relatório de implementação, referências e dev log (`docs/dev-log/INDEX.md`).
- `vectorstore/` — índice Chroma na raiz do repo.

Cada subprojeto Python (`backend/`, `llm/`) gerencia dependências via `pyproject.toml` (`pip install -e .`).

## Configuração compartilhada Cursor + Claude Code

Este repositório é editável tanto pelo **Cursor** quanto pelo **Claude Code**. As regras são mantidas em **`.cursor/rules/*.mdc`** como fonte única de verdade; este `CLAUDE.md` as importa abaixo para que os dois ambientes sigam exatamente as mesmas convenções. Ao ajustar uma regra, edite o `.mdc` correspondente — a mudança vale para ambos.

Mapeamento entre as ferramentas:

| Cursor | Claude Code |
|--------|-------------|
| `.cursor/rules/*.mdc` (alwaysApply) | importadas neste `CLAUDE.md` |
| `.cursor/rules/langgraph-node-conventions.mdc` (glob `backend/src/**/graph/**`) | importada em `backend/CLAUDE.md` |
| `.cursor/rules/report-and-wait-before-implement.mdc` (manual) | comando `/report-and-wait` (`.claude/commands/`) |
| `.cursor/agents/brazilian-tone-fixer.md` | subagente `.claude/agents/brazilian-tone-fixer.md` |
| `.agents/skills/` (caveman, caveman-help) | `.claude/skills/` (symlinks para a mesma fonte) |

## Regras sempre ativas

@.cursor/rules/language-conventions-en-code-pt-br-ui.mdc

@.cursor/rules/activate-venv-before-python.mdc

@.cursor/rules/inline-comments-for-long-methods.mdc

@.cursor/rules/dev-log.mdc
