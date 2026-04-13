# Dev log (índice compacto)

Formato: uma linha por decisão relevante; mais detalhe só em `decisions/` quando necessário.

**Autor (opcional):** humano → `git config user.name` (curto); agente → `agent:cursor` (ou prefixo fixo `agent:`) para filtros/`rg` fáceis.

| Data (ISO) | ID | Autor | Resumo |
|------------|-----|-------|--------|
| 2026-04-12 | dev-log-bootstrap | agent:cursor | Log em `docs/dev-log/`; regra `dev-log.mdc`; follow-up script limpeza + flag `llm/data` + `vectorstore/` (plano embeddings). |
| 2026-04-12 | cursor-rule-report-and-wait | Preferência de fluxo: `.cursor/rules/report-and-wait-before-implement.mdc` — @ ou `/report-and-wait` no fim da mensagem para o agente reportar e aguardar antes de implementar. |

## `decisions/` (opcional)

Ficheiros `YYYYMMDD-id-curto.md` só quando uma linha no índice não chega (API, ADR mini).
