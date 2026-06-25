# Agente de busca especializado + ingestão estruturada

**Data:** 2026-06-24  
**Autor:** agent:cursor + Leander Seefeld  
**Revisão anterior:** `bf3812f` chore: configurar Claude Code com regras espelhadas do Cursor

> Decisão de **direção** (ideação), não de implementação. Detalhamento em [`docs/handoff/agente-busca-especializado.md`](../../handoff/agente-busca-especializado.md).

## Problema

O RAG atual reescreve a pergunta em **uma única** query densa e perde estrutura na ingestão: a extração (`pymupdf4llm`) tem fidelidade limitada para tabelas/figuras e a limpeza (`clean/heuristics.py`) **descarta** imagens, figuras, diagramas e tabelas malformadas. Em PCDTs, muito do conteúdo clínico crítico (doses, critérios, fluxogramas) está justamente em tabelas e figuras. Além disso, operar o pipeline (adicionar PCDT, reexecutar a partir de uma etapa, avaliar saídas) é só via CLI.

Durante a revisão, a doc descritiva (`pipeline-rag.md`) também afirmava **busca híbrida (BM25 + denso)**, que **não existe** no código — afirmação removida e reposicionada como inspiração.

## Decisão (direção a explorar)

1. **Geração de queries por LLM com chain-of-thought**: o agente raciocina sobre a intenção clínica e emite **até N queries** Chroma estruturadas; resultados são fundidos/deduplicados antes do rerank atual. Encaixa entre `rewrite` e `retrieve` no grafo `chat_rag`.
2. **Chunking/ingestão estruturados**: preservar cabeçalhos, seções, **tabelas**, imagens e diagramas, marcando tipo de bloco e hierarquia, e expô-los ao LLM como grounding.
3. **Reavaliação da conversão de PDF** (`extract.py`): avaliar extração layout-aware que preserve tabelas como estrutura e detecte figuras/diagramas.
4. **UI/fluxo web de operação**: adicionar PCDTs, reexecutar a partir de uma etapa (sobre os manifestos JSONL por etapa) e avaliar saídas, reaproveitando o RAG Inspector.

## Inspirações futuras (registradas, fora de escopo imediato)

- Busca **híbrida denso + lexical/BM25** com fusão (ex.: RRF), alimentada pelas N queries.
- **Gestão de protocolos** além dos PCDTs da Conitec, com **scrapers por fonte** (ex.: POPs de prefeituras).
- **Perfis profissionais** (enfermagem, farmácia, etc.) com POPs e prompts dedicados.

## Riscos

- **Latência/custo**: N queries por turno multiplicam chamadas de busca (e possivelmente de LLM). Definir teto de N e fallback para query única.
- **Fusão de resultados**: combinar rankings de queries distintas antes do rerank precisa de critério (ex.: RRF) para não degradar precisão.
- **Conflito com a limpeza atual**: preservar tabelas/figuras exige separar ruído (cabeçalho/rodapé/índice) de conteúdo estrutural — risco de reintroduzir lixo se mal calibrado.
- **Reextração**: trocar/estender a conversão de PDF invalida sidecars/chunks/embeddings existentes; planejar reprocessamento idempotente via manifestos.
