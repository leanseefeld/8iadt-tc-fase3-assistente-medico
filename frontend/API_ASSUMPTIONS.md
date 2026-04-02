# Premissas de API REST (protótipo)

Este documento descreve o contrato **provisório** que o frontend espera quando o backend existir. Hoje as respostas são **simuladas** em `src/api/mockApi.ts` e `src/api/mockData.ts`.

## Paciente (`Patient`)

Campos usados na barra superior e na busca:

| Campo            | Tipo           | Observação |
| ---------------- | -------------- | ---------- |
| `id`             | string         | Identificador único (ex.: `P001`). |
| `name`           | string         | Nome completo. |
| `gender`         | string         | Texto para exibição (ex.: `Feminino` / `Masculino`). |
| `age`            | number         | Idade em anos. |
| `mainCondition`  | string         | Condição principal / motivo resumido. |
| `checkedInAt`    | string \| null | ISO 8601 do check-in; `null` = sem internação / sem check-in. |

### Regra do indicador de internação (12 horas)

O frontend calcula o estado visual (verde / amarelo / cinza) com **janela móvel de 12 horas** a partir de `checkedInAt`:

- **Verde:** há `checkedInAt` e o tempo decorrido é **≤ 12 horas**.
- **Amarelo:** há `checkedInAt` e o tempo decorrido é **> 12 horas**.
- **Cinza:** `checkedInAt` é `null` ou inválido.

Se o backend passar a enviar o estado já calculado, este contrato pode ser estendido com um campo derivado; até lá, a fonte da verdade é `checkedInAt`.

## Alertas (`ClinicalAlert`)

| Campo        | Tipo                         | Observação |
| ------------ | ---------------------------- | ---------- |
| `id`         | string                       | Identificador do alerta. |
| `patientId`  | string                       | Deve coincidir com `Patient.id`. |
| `title`      | string                       | Título curto. |
| `severity`   | `info` \| `warning` \| `critical` | Severidade para estilo e rótulo. |
| `createdAt`  | string                       | ISO 8601. |
| `message`    | string                       | Detalhe exibido no painel. |

---

## Endpoints sugeridos

### `GET /api/patients?q=`

- **Query:** `q` opcional — filtra por substring em `id` ou `name` (case-insensitive).
- **Resposta 200:** `{ "patients": Patient[] }`

### `GET /api/patients/:id`

- **Resposta 200:** corpo = `Patient`
- **Resposta 404:** paciente inexistente

### `GET /api/patients/:id/alerts`

- **Resposta 200:** `{ "alerts": ClinicalAlert[] }` (apenas alertas daquele `patientId`)

### `PATCH /api/patients/:id` ou `POST /api/session/patient` (opcional)

- Uso futuro se a **seleção do paciente ativo** for persistida no servidor (sessão / contexto clínico). No protótipo a seleção é só no estado do cliente (`PatientContext`).

---

## Base URL

Variável opcional: `VITE_API_BASE_URL` (ver `src/api/client.ts`). Padrão fictício: `http://localhost:3000/api`.
