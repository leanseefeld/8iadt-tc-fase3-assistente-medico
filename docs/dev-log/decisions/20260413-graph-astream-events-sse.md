# SSE via graph.astream_events

**Data:** 2026-04-13  
**Autor:** agent:cursor + Leander Seefeld  
**Revisão anterior:** `1e7fd7b` chore(cursor): subagent to fix portuguese to brazilian

## Problema

O caminho SSE anterior bypassava o grafo LangGraph: chamava `retrieve_node` e `astream_answer` diretamente. O grafo só era usado no caminho JSON. Duas rotas de execução paralelas, lógica duplicada.

## Decisão

Usar `graph.astream_events(initial, version="v2")` para o caminho SSE. Grafo único serve ambos os caminhos:


| Caminho | Método                                        |
| ------- | --------------------------------------------- |
| JSON    | `asyncio.to_thread(graph.invoke, initial)`    |
| SSE     | `graph.astream_events(initial, version="v2")` |


## Mapeamento de eventos em chat.py

`chat.py` ouve eventos específicos e decide o que emitir para o cliente. Nós não conhecem SSE.


| Evento LangGraph                   | Ação                                               |
| ---------------------------------- | -------------------------------------------------- |
| `on_chain_end` + `name="retrieve"` | Emite `sources` e `reasoning` SSE antes dos tokens |
| `on_chat_model_stream`             | Emite `token` SSE com `chunk.content`              |


Metadados são enviados **imediatamente** quando o nó `retrieve` termina — não no fim do grafo. Isso permite que a UI mostre fontes enquanto tokens ainda chegam.

## Contrato de nós (ver também `.cursor/rules/langgraph-node-conventions.mdc`)

- **Nó de resposta final**: `async def` + `llm.astream` → emite `on_chat_model_stream` → tokens SSE para o cliente.
- **Nó intermediário com LLM** (refinamento, roteamento, grading): `async def` + `llm.ainvoke` → async sem vazar tokens para o cliente. Resultado vai para `reasoning_steps`.
- **Nó com I/O bloqueante** (Chroma, DB): `def` síncrono — LangGraph roda em thread.
- Nós escrevem em campos de estado (`sources`, `reasoning_steps`). `chat.py` decide quando emitir.

## Mudanças nos módulos

- `**generate.py`**: `generate_node_sync` e `astream_answer` removidos. Único export: `generate_node(state, settings)` async com `llm.astream`. Helpers `_build_llm` / `_build_messages` privados.
- `**chat_rag.py**`: closure `_generate` é `async def`, delega para `generate_node`.
- `**chat.py**`: `_merge_retrieve` e imports diretos de `retrieve_node`/`astream_answer` removidos. SSE = loop único sobre `astream_events`.

## Risco

`on_chain_end` com `name="retrieve"` depende do nome exato do nó no LangGraph. Se versão do langgraph mudar schema de eventos, ajustar para o nome correto. Debugar com `print(event["event"], event.get("name"))` se metadados chegarem vazios.