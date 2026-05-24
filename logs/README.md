# Pasta de logs (`logs/`)

Este diretório pode conter ficheiros **`audit_clinical_YYYY-MM-DD.jsonl`**: uma linha JSON por evento (prontuário/admissões/exames/etc. **e**, em forma resumida, marcos do assistente: RAG, guardrail e turnos do chat — ver `backend/README.md`).

- O **dia** da ocorrência está no **nome do ficheiro** (`YYYY-MM-DD` com base na data local do servidor quando ocorre a escrita).
- Cada linha segue o schema documentado em `backend/README.md` (campo `acao`, `medico_id`, `patient_id`, `descricao`, …).
- Para marcar simulações da UI de demonstração, o cliente envia o cabeçalho `X-Audit-Context: demo` nas rotas indicadas no README do backend.
- Os testes de backend (`pytest`) **não** acrescentam linhas nestes ficheiros (persistência da auditoria clínica fica desligada na configuração de testes).
