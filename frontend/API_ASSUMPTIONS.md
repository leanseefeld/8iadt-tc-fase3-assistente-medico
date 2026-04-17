# Premissas de API REST (protótipo)

Contrato alinhado à [referencia-frontend.md](../docs/referencia-frontend.md). **Hoje** as rotas abaixo são implementadas via `src/api/clinicalApi.ts`: por padrão tudo delega a `src/api/clinicalApi.memory.ts` + `src/api/mockServerState.ts`.

Com `VITE_CLINICAL_API_HTTP=true`, apenas **`POST /assistant/chat`** passa a usar `src/api/clinicalApi.http.ts` (fetch + SSE). As demais operações continuam em **memória** até existirem endpoints reais — evita quebrar check-in, dashboard, etc.

## Sessão (`activePatientId`)

Não faz parte do contrato HTTP no protótipo: o cliente mantém o paciente ativo no **contexto React**. O backend futuro pode expor `GET/PATCH /session`.

**Nota (chat):** o `patientId` é enviado no corpo do chat para alinhamento futuro; o backend atual **não** injeta contexto clínico do paciente no RAG (planeado após CRUD).

---

## DTOs (JSON — identificadores em inglês)

### `Cid`

| Campo  | Tipo   |
| ------ | ------ |
| `code` | string |
| `label`| string |

### `VitalSigns`

| Campo                 | Tipo   |
| --------------------- | ------ |
| `bloodPressure`       | string |
| `temperature`         | number |
| `oxygenSaturation`    | number |
| `heartRate`           | number |
| `updatedAt`           | string (ISO 8601) |

### `Exam`

| Campo             | Tipo                                      |
| ----------------- | ----------------------------------------- |
| `id`              | string                                    |
| `name`            | string                                    |
| `requestedAt`     | string (ISO 8601)                         |
| `status`          | `pending` \| `completed` \| `critical`    |
| `result`          | string (opcional)                         |
| `interpretation`  | string (opcional)                         |
| `source`          | `protocol` \| `manual`                    |
| `protocolRef`     | string (opcional)                         |

### `SuggestedActionItem`

| Campo         | Tipo                                                                 |
| ------------- | -------------------------------------------------------------------- |
| `id`          | string                                                               |
| `type`        | `exam` \| `prescription` \| `observation` \| `review`                 |
| `description` | string                                                             |
| `status`     | `suggested` \| `accepted` \| `modified` \| `rejected`                |
| `protocolRef` | string (opcional)                                                  |

### `AgentLogEntry`

| Campo       | Tipo                                       |
| ----------- | ------------------------------------------ |
| `step`      | string                                     |
| `status`    | `done` \| `running` \| `alert` \| `error`   |
| `detail`    | string                                     |
| `timestamp` | string (ISO 8601)                          |

### `Patient`

| Campo                | Tipo                                                                 |
| -------------------- | -------------------------------------------------------------------- |
| `id`                 | string                                                               |
| `name`               | string                                                               |
| `age`                | number                                                               |
| `sex`                | `M` \| `F`                                                           |
| `bed`                | string                                                               |
| `status`             | `admitted` \| `discharged`                                           |
| `admittedAt`         | string (ISO 8601)                                                    |
| `cid`                | `Cid`                                                                |
| `observations`     | string                                                               |
| `comorbidities`      | string[]                                                             |
| `currentMedications` | string[] (itens normalizados a partir do texto do check-in)        |
| `vitalSigns`         | `VitalSigns`                                                         |
| `exams`              | `Exam[]`                                                             |
| `suggestedItems`     | `SuggestedActionItem[]` (substitui o termo legado `conduct`)         |
| `agentLog`           | `AgentLogEntry[]`                                                    |

### `Alert`

| Campo       | Tipo                                                                 |
| ----------- | -------------------------------------------------------------------- |
| `id`        | string                                                               |
| `patientId` | string (`"system"` para alertas globais de demonstração)             |
| `severity`  | `critical` \| `moderate` \| `info`                                  |
| `category`  | `exam` \| `medication` \| `clinical` \| `system`                   |
| `message`   | string                                                               |
| `team`      | `doctors` \| `nursing` \| `pharmacy` \| `all`                        |
| `createdAt` | string (ISO 8601)                                                    |
| `resolved`  | boolean                                                              |

### `ChatResponse`

| Campo        | Tipo       |
| ------------ | ---------- |
| `text`       | string     |
| `sources`    | string[]   |
| `reasoning`  | string[]   |

### `DecisionFlowResponse`

| Campo   | Tipo     | Descrição                                      |
| ------- | -------- | ---------------------------------------------- |
| `lines` | string[] | Linhas de log textuais para a Página 3         |
| `meta`  | object   | `sepsisCritical`, `pharmacyInteraction` (bool) |

---

## Endpoints

### 1. `GET /patients`

**Query (opcional):**

- `status`: ex. `admitted` — filtra por `Patient.status`
- `q`: substring case-insensitive em `id` ou `name`

**Resposta 200:** `{ "patients": Patient[] }`

---

### 2. `POST /patients`

Admissão (Página 0). Corpo JSON alinhado ao formulário:

| Campo                 | Tipo        | Obrigatório |
| --------------------- | ----------- | ----------- |
| `name`                | string      | sim         |
| `age`                 | number      | sim         |
| `sex`                 | `M` \| `F` | sim         |
| `bed`                 | string      | sim         |
| `cid`                 | `Cid`       | sim         |
| `observations`      | string      | sim         |
| `comorbidities`       | string[]    | não         |
| `currentMedications`  | string      | não (multilinha → split em array no servidor) |

O servidor aplica o protocolo mock do CID: preenche `exams`, `suggestedItems`, `protocolRef` nos itens, `agentLog` inicial quando aplicável, e alertas específicos (ex.: sepse T81.4 farmácia, A41.9 crítico).

**Resposta 201:** `{ "patient": Patient }`

---

### 3. `GET /patients/:id`

**Resposta 200:** `{ "patient": Patient }` (agregado completo)

**Resposta 404:** paciente inexistente

---

### 4. `PATCH /patients/:id`

Corpo JSON **parcial**. Campos de primeiro nível suportados (lista mínima do protótipo):

- `cid`, `status`, `observations`, `comorbidities`, `currentMedications`, `vitalSigns`, `bed`, etc.
- **`exams`**: array de objetos `{ id, ...campos }` — **merge por `id`**: cada elemento atualiza o exame existente com os campos enviados.
- **`suggestedItems`**: idem — merge por `id` para aceitar / modificar / rejeitar / alterar `description`.

Quando `cid` muda, o servidor **substitui** `exams` e `suggestedItems` pelos derivados do novo protocolo (como na referência após editar CID).

**Resposta 200:** `{ "patient": Patient }`

**Resposta 404:** paciente inexistente

---

### 5. `GET /alerts`

**Query (opcional):** `patientId`, `severity`, `team`, `resolved` (`true` / `false`)

**Resposta 200:** `{ "alerts": Alert[] }`

---

### 6. `PATCH /alerts/:id`

Corpo: `{ "resolved": boolean }`

**Resposta 200:** `{ "alert": Alert }`

---

### 7. `POST /assistant/chat`

**Corpo (JSON no fio — camelCase):**

```json
{ "patientId": "uuid", "message": "string" }
```

O servidor FastAPI aceita `patientId` (alias); internamente pode mapear para `patient_id`.

**Modo principal — SSE (streaming):**

- Cabeçalho: `Accept: text/event-stream`
- Corpo: `Content-Type: application/json` com o JSON acima
- Resposta: `200` com `Content-Type: text/event-stream`; fluxo de eventos Server-Sent Events:

| Nome do evento (`event:`) | Corpo JSON (`data:`) | Descrição |
| ------------------------- | -------------------- | --------- |
| `sources` | `{ "sources": string[] }` | Rótulos das fontes PCDT recuperadas |
| `reasoning` | `{ "steps": string[] }` | Traço curto da etapa de recuperação (no cliente mapeado para o painel «raciocínio») |
| `token` | `{ "content": string }` | Fragmento incremental da resposta do modelo |
| `done` | `{}` | Fim do fluxo com sucesso |
| `error` | `{ "detail": string }` | Erro durante recuperação ou geração |

O cliente (`src/api/sseChat.ts`) agrega os `token` em `ChatResponse.text` e usa `sources` + `steps` como `sources` e `reasoning`.

**Modo alternativo — JSON (bloqueante):**

- Sem `Accept: text/event-stream` (ex.: `Accept: application/json` ou omisso, conforme implementação do cliente)
- **Resposta 200:** corpo JSON igual a `ChatResponse` (`text`, `sources`, `reasoning`)

**Erros HTTP:** ex. **503** se Chroma/Ollama indisponíveis na inicialização ou falha grave na invocação do grafo (detalhe em `detail` quando aplicável).

**Premissas alteradas em relação ao protótipo só-mock:**

- Perguntas «não mapeadas» deixam de ser só fallback na UI: com backend ativo, o modelo responde com RAG sobre PCDTs indexados em `vectorstore/chroma`.
- `conversationId`: reservado para versões futuras; não é obrigatório na v1.

---

### 8. `POST /assistant/decision-flow`

Corpo:

```json
{ "patientId": "uuid" }
```

Simula execução do grafo para o paciente atual (log + metadados de branch sepse / farmácia conforme CID e estado).

**Resposta 200:** `DecisionFlowResponse`

---

### 9. `GET /assistant/comorbidities`

Retorna opções disponíveis de comorbidades para seleção no check-in (dados de referência em memória, sem persistência em banco de dados).

**Query:** nenhuma

**Resposta 200:** `ComorbidititiesResponse`

| Campo | Tipo | Descrição |
| --- | --- | --- |
| `comorbidities` | `ComorbidityOption[]` | Lista de opções de comorbidades para seleção no check-in |

**`ComorbidityOption`:**

| Campo | Tipo | Descrição |
| --- | --- | --- |
| `code` | string | Identificador único (ex.: `HAS`, `DM2`, `Gravidez`) |
| `label` | string | Descrição legível em português (ex.: `Hipertensão Arterial Sistêmica`) |
| `category` | string | Categoria para agrupamento (ex.: `cardiovascular`, `endocrine`, `respiratory`) |

Exemplo:
```json
{
  "comorbidities": [
    {
      "code": "HAS",
      "label": "Hipertensão Arterial Sistêmica",
      "category": "cardiovascular"
    },
    {
      "code": "Gravidez",
      "label": "Gravidez",
      "category": "reproductive"
    }
  ]
}
```

---

## Base URL

Variável: `VITE_API_BASE_URL` (ver `src/api/client.ts`). Padrão documental e no código: **`http://localhost:8001/api`** (servidor FastAPI local, prefixo `/api`).

Ativar chat real: `VITE_CLINICAL_API_HTTP=true` e backend a correr (ver `backend/README.md`).

## Mapeamento futuro backend

Os DTOs acima servem como alvo estável para o frontend. O backend pode adicionar campos ou usar nomes de tabela diferentes internamente, desde que a camada de API traduza para estes contratos ou seja atualizado em conjunto com este arquivo.
