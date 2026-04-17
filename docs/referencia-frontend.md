# Assistente Médico com IA — Documento de Referência de Interface

> **Finalidade:** Este documento serve como referência para agentes de desenvolvimento (Cursor, Copilot, etc.) construírem o protótipo da interface React do assistente médico com IA. Todos os dados são mock. O backend pode ser substituído por integrações reais sem alterar a interface.

---

## Índice

1. [Estado Global (Mock Store)](#1-estado-global-mock-store)
2. [Componentes Compartilhados](#2-componentes-compartilhados)
3. [Página 0 — Check-in / Admissão](#3-página-0--check-in--admissão)
4. [Página 1 — Dashboard do Paciente](#4-página-1--dashboard-do-paciente)
5. [Página 2 — Chat com o Assistente](#5-página-2--chat-com-o-assistente)
6. [Página 3 — Fluxo de Decisão](#6-página-3--fluxo-de-decisão)
7. [Página 4 — Exames e Pendências](#7-página-4--exames-e-pendências)
8. [Página 5 — Ações Sugeridas](#8-página-5--ações-sugeridas)
9. [Página 6 — Painel de Alertas](#9-página-6--painel-de-alertas)
10. [Mapa de Transições](#10-mapa-de-transições)
11. [Fluxos de Teste](#11-fluxos-de-teste)

---

## 1. Estado Global (Mock Store)

O estado da aplicação deve ser gerenciado com **React Context + useReducer** (ou Zustand). Todas as páginas leem e escrevem nesse estado.

### Estrutura do store

```ts
interface AppState {
  patients: Patient[];           // todos os pacientes cadastrados
  activePatientId: string | null; // paciente selecionado na sidebar
  alerts: Alert[];               // alertas globais do sistema
}

interface Patient {
  id: string;
  name: string;
  age: number;
  sex: "M" | "F";
  bed: string;
  status: "admitted" | "discharged"; // sidebar exibe apenas "admitted"
  admittedAt: string;                // ISO timestamp
  cid: {
    code: string;   // ex: "L40.5"
    label: string;  // ex: "Artrite Psoriásica"
  };
  chiefComplaint: string;
  comorbidities: string[];   // ex: ["HAS", "DM2"]
  currentMedications: string[];
  vitalSigns: VitalSigns;
  exams: Exam[];
  conduct: SuggestedActionItem[];
  agentLog: AgentLogEntry[];
}

interface VitalSigns {
  bloodPressure: string;  // ex: "130/85"
  temperature: number;    // °C
  oxygenSaturation: number; // %
  heartRate: number;      // bpm
  updatedAt: string;
}

interface Exam {
  id: string;
  name: string;
  requestedAt: string;
  status: "pending" | "completed" | "critical";
  result?: string;
  interpretation?: string; // gerada pelo assistente (mock)
  source: "protocol" | "manual"; // se veio do protocolo ou foi solicitado manualmente
}

interface SuggestedActionItem {
  id: string;
  type: "exam" | "prescription" | "observation" | "review";
  description: string;
  status: "suggested" | "accepted" | "modified" | "rejected";
  protocolRef?: string; // ex: "PCDT Artrite Psoriásica — CONITEC 2023"
}

interface Alert {
  id: string;
  patientId: string;
  severity: "critical" | "moderate" | "info";
  category: "exam" | "medication" | "clinical" | "system";
  message: string;
  team: "doctors" | "nursing" | "pharmacy" | "all";
  createdAt: string;
  resolved: boolean;
}

interface AgentLogEntry {
  step: string;
  status: "done" | "running" | "alert" | "error";
  detail: string;
  timestamp: string;
}
```

### Pacientes mock iniciais (status: "discharged" — não aparecem na sidebar)

```ts
const MOCK_PATIENTS_DISCHARGED = [
  {
    id: "p-hist-01",
    name: "Roberto Farias",
    age: 72,
    status: "discharged",
    cid: { code: "I50.0", label: "Insuficiência Cardíaca Congestiva" },
    // ... demais campos
  }
];
```

> Os pacientes do fluxo de teste (seção 11) devem ser **admitidos via Página 0** durante a demo, não pré-carregados como "admitted".

---

## 2. Componentes Compartilhados

### Sidebar

- Logo do projeto no topo
- **Seletor de paciente:** dropdown exibindo **apenas pacientes com `status: "admitted"`**. Se nenhum paciente estiver admitido, exibe mensagem: *"Nenhum paciente ativo. Realize um check-in."* com link para Página 0
- Indicador de status do agente: ponto colorido + texto ("🟢 Agente ativo")
- Menu de navegação:
  - ➕ Check-in / Admissão
  - 🏠 Dashboard
  - 💬 Chat com Assistente
  - 🔀 Fluxo de Decisão
  - 🧪 Exames
  - 📋 Ações Sugeridas
  - 🔔 Alertas `<badge com contagem de alertas não resolvidos>`

### Header

- Nome e CID do paciente ativo (clicável — abre modal de edição de CID)
- Leito e hora de admissão
- Botão **"Editar CID"** → abre `<CIDEditModal>`
- Botão **"Alta"** → abre confirmação, muda `status` para `"discharged"`, remove da sidebar

### CIDEditModal

- Campo de busca com filtro sobre lista de CIDs mock (mínimo 20 entradas cobrindo os casos de teste)
- Ao confirmar: atualiza `patient.cid`, dispara re-execução do fluxo de decisão, exibe toast: *"CID atualizado. Fluxo de decisão re-executado."*
- Exibe aviso: *"Novos exames podem ter sido identificados com base no protocolo atualizado."* e navega para Página 3

---

## 3. Página 0 — Check-in / Admissão

**Rota:** `/checkin`  
**Propósito:** Ponto de entrada da demo. Admite um novo paciente e dispara o fluxo inicial.

### Layout

Formulário centralizado, largura máxima 640px, fundo em card.

### Campos

| Campo | Tipo | Obrigatório | Notas |
|---|---|---|---|
| Nome completo | text | ✅ | |
| Idade | number | ✅ | min 0, max 120 |
| Sexo | select | ✅ | Masculino / Feminino |
| Leito | text | ✅ | ex: "UTI-03" |
| CID Principal | searchable select | ✅ | Busca por código ou descrição |
| Queixa principal | textarea | ✅ | máx 300 chars |
| Comorbidades | checkbox group | — | Carregadas do backend via `GET /api/assistant/comorbidities` |
| Medicamentos em uso | textarea | — | Campo livre, uma linha por medicamento |

### CID Mock List (mínimo necessário para os fluxos de teste)

```ts
const CID_LIST = [
  { code: "L40.5", label: "Artrite Psoriásica" },
  { code: "A41.9", label: "Sepse não especificada" },
  { code: "T81.4", label: "Infecção pós-procedimento cirúrgico" },
  { code: "E11.9", label: "Diabetes Mellitus tipo 2 sem complicações" },
  { code: "I10",   label: "Hipertensão Essencial" },
  { code: "J18.9", label: "Pneumonia não especificada" },
  { code: "N17.9", label: "Insuficiência Renal Aguda" },
  { code: "K92.1", label: "Melena" },
  { code: "I63.9", label: "AVC Isquêmico" },
  { code: "M05.3", label: "Artrite Reumatoide" },
  // ... completar com mais 10+ para realismo
];
```

### Protocolo Mock por CID

Estrutura central da demo. Mapeia CID → exames e ações sugeridas recomendadas.

```ts
const PROTOCOL_MAP: Record<string, ProtocolResult> = {
  "L40.5": {
    protocolRef: "PCDT Artrite Psoriásica — CONITEC 2023",
    exams: [
      "Hemograma completo",
      "Contagem de plaquetas",
      "Creatinina sérica",
      "AST/TGO",
      "ALT/TGP",
    ],
    suggestedActions: [
      { type: "exam", description: "Solicitar Hemograma completo" },
      { type: "exam", description: "Solicitar Contagem de plaquetas" },
      { type: "exam", description: "Solicitar Creatinina sérica" },
      { type: "exam", description: "Solicitar AST/TGO" },
      { type: "exam", description: "Solicitar ALT/TGP" },
      { type: "observation", description: "Avaliar acometimento cutâneo (PASI)" },
      { type: "review", description: "Reavaliação em 24h" },
    ],
  },
  "A41.9": {
    protocolRef: "Protocolo de Sepse — MS 2019",
    exams: [
      "Hemoculturas (2 amostras)",
      "Lactato sérico",
      "Hemograma completo",
      "PCR e Procalcitonina",
      "Gasometria arterial",
      "Creatinina e Ureia",
    ],
    suggestedActions: [
      { type: "prescription", description: "Antibioticoterapia empírica em até 1h (ver protocolo)" },
      { type: "exam", description: "Coletar hemoculturas antes dos antibióticos" },
      { type: "observation", description: "Monitorar sinais de disfunção orgânica" },
      { type: "review", description: "Reavaliação em 6h — bundle de sepse" },
    ],
  },
  "T81.4": {
    protocolRef: "Protocolo Pós-Cirúrgico — Controle de Infecção",
    exams: [
      "Hemograma completo",
      "PCR",
      "Cultura de sítio cirúrgico",
      "Glicemia",
    ],
    suggestedActions: [
      { type: "prescription", description: "Verificar interação: antibiótico + anticoagulante em uso" },
      { type: "exam", description: "Solicitar cultura de sítio cirúrgico" },
      { type: "observation", description: "Inspecionar ferida operatória" },
    ],
    drugInteractionAlert: true, // dispara alerta de farmácia no Paciente C
  },
};
```

### Comportamento ao submeter

1. Cria novo `Patient` com `status: "admitted"` e `id` gerado (uuid mock)
2. Exibe `<AgentSpinner>` por 1,5s com mensagens sequenciais:
   - *"Registrando paciente..."*
   - *"Consultando protocolo clínico..."*
   - *"Identificando exames recomendados..."*
   - *"Gerando plano inicial..."*
3. Popula `patient.exams` e `patient.suggestedActions` a partir do `PROTOCOL_MAP[cid.code]`
4. Cria `AgentLogEntry[]` correspondente
5. Seleciona o paciente na sidebar (`activePatientId = newPatient.id`)
6. Navega automaticamente para **Página 3 — Fluxo de Decisão**

---

## 4. Página 1 — Dashboard do Paciente

**Rota:** `/dashboard`  
**Propósito:** Visão consolidada do caso. Ponto de retorno após outras páginas.

### Layout — 3 colunas + linha do tempo

**Coluna esquerda — Identificação**
- Card com nome, idade, sexo, leito, CID (clicável para editar), data de admissão
- Botão "Alta" (vermelho, outline) com confirmação modal
- Comorbidades como badges

**Coluna central — Sinais Vitais**
- 4 métricas em grid 2x2: PA, Temperatura, SpO2, FC
- Cada métrica com valor e status (normal/atenção/crítico por threshold)
- Botão "Simular novo valor" → abre mini-form para alterar um sinal vital e disparar alerta se crítico
- Timestamp da última atualização

**Coluna direita — Resumo Ativo**
- Lista de medicamentos em uso
- Alertas ativos (máx 3, com link "ver todos")
- Exames pendentes (contagem + link para Página 4)

**Linha do tempo (full-width, abaixo das colunas)**
- Eventos horizontais em ordem cronológica: Admissão → Check-in → Exames solicitados → Alertas → (futuros)
- Cada evento é um ponto clicável que exibe um tooltip com detalhes

### Interações dinâmicas

- **Editar CID:** clique no badge do CID → abre `<CIDEditModal>` → re-executa protocolo
- **Alta:** confirmação → `status: "discharged"` → redireciona para `/checkin` com toast *"Paciente [Nome] recebeu alta."*
- **Simular sinal vital crítico:** altera o valor, se fora do threshold dispara novo `Alert` com `severity: "critical"`

---

## 5. Página 2 — Chat com o Assistente

**Rota:** `/chat`  
**Propósito:** Demonstrar interação conversacional com RAG e raciocínio transparente.

### Layout — 2 painéis

**Painel principal (2/3 da largura) — Chat**
- Balões de conversa: usuário (direita, azul) e assistente (esquerda, cinza)
- Input no rodapé com botão enviar
- Botões de atalho acima do input (4 perguntas pré-definidas por CID):

```ts
const QUICK_QUESTIONS: Record<string, string[]> = {
  "L40.5": [
    "Quais exames estão pendentes?",
    "Há contraindicação ao metotrexato neste paciente?",
    "Qual o protocolo recomendado para artrite psoriásica?",
    "Resumir o caso clínico atual",
  ],
  "A41.9": [
    "Quais exames estão pendentes?",
    "Bundle de sepse está completo?",
    "Qual antibiótico empírico recomendar?",
    "Paciente apresenta critérios de UTI?",
  ],
  // ... default para outros CIDs
  default: [
    "Quais exames estão pendentes?",
    "Resumir o caso clínico atual",
    "Há alertas ativos?",
    "Qual a ação sugerida?",
  ],
};
```

**Painel lateral (1/3 da largura) — Contexto do Agente**
- Seção **"Fontes consultadas"**: lista de documentos mock com ícone de arquivo
  - ex: *📄 PCDT Artrite Psoriásica — CONITEC 2023*
  - ex: *📄 Bula Metotrexato — ANVISA*
- Seção expansível **"Raciocínio do agente"**: passos intermediários
  - *🔍 Buscou: "artrite psoriásica exames baseline"*
  - *📋 Encontrou: PCDT seção 4.2 — Avaliação laboratorial inicial*
  - *✅ Concluiu: 5 exames identificados*

### Respostas mock por pergunta

```ts
const MOCK_RESPONSES: Record<string, MockResponse> = {
  "Quais exames estão pendentes?": {
    text: "Com base no protocolo para L40.5 (Artrite Psoriásica), os seguintes exames estão pendentes:\n\n• Hemograma completo\n• Contagem de plaquetas\n• Creatinina sérica\n• AST/TGO\n• ALT/TGP\n\nEsses exames são necessários para avaliação basal antes do início da terapia modificadora.",
    sources: ["PCDT Artrite Psoriásica — CONITEC 2023"],
    reasoning: [
      "Buscou: 'artrite psoriásica avaliação laboratorial'",
      "Encontrou: PCDT seção 4.2 — Critérios de Inclusão e Avaliação Basal",
      "Extraiu: lista de exames obrigatórios pré-tratamento",
    ],
  },
  // ... demais perguntas
};
```

### Comportamento para perguntas não mapeadas

Exibe: *"Esta pergunta requer consulta ao backend. Em modo demo, apenas perguntas pré-definidas têm resposta simulada."* — em itálico, sem balão de resposta do assistente.

---

## 6. Página 3 — Fluxo de Decisão

**Rota:** `/flow`  
**Propósito:** Tornar o LangGraph visível. Página mais importante para comunicar a inovação.

### Layout

**Diagrama de nós (topo)**

Representado como SVG ou biblioteca de grafos (ex: `reactflow`). Nós fixos:

```
[Triagem] → [Consulta Protocolo] → [Checar Exames] → [Sugerir Ações Sugeridas] → [Emitir Alertas]
                                          ↓ (se crítico)
                                    [Alerta Imediato]
```

Cada nó tem um estado visual:
- ⬜ `idle` — cinza, aguardando
- 🟡 `running` — amarelo, pulsando (CSS animation)
- 🟢 `done` — verde
- 🔴 `alert` — vermelho, com ícone de sino

**Botão "Executar Fluxo"** — centralizado abaixo do diagrama

**Log de execução (abaixo do botão)**

Entradas aparecem sequencialmente com delay (200ms entre cada):

```
✅ [10:32:01] Triagem: dados do paciente carregados — L40.5, João Silva, 67 anos
🔍 [10:32:02] Consultando protocolo: PCDT Artrite Psoriásica — CONITEC 2023
📋 [10:32:03] Exames identificados: Hemograma, Plaquetas, Creatinina, AST/TGO, ALT/TGP
⚙️ [10:32:04] Ações Sugeridas gerada: 7 itens — aguarda aprovação do médico
🔔 [10:32:05] Alerta enviado: equipe de enfermagem notificada
✅ [10:32:05] Fluxo concluído
```

### Comportamento de execução

1. Botão clicado → inicia animação sequencial nos nós (200ms por nó)
2. Log aparece linha a linha em paralelo
3. Se `patient.cid.code === "A41.9"` (Sepse): nó "Checar Exames" ativa a branch `[Alerta Imediato]` com nó vermelho piscando + nova entrada no log: *"🚨 Caso crítico detectado — alerta imediato para equipe médica"*
4. Ao concluir: botão muda para "Re-executar Fluxo" (outline)
5. Link no rodapé: *"Ver ações sugeridas →"* navega para Página 5

### Re-execução após edição de CID

Se o CID foi alterado via `<CIDEditModal>`, ao entrar nessa página exibe banner amarelo: *"CID atualizado para [novo CID]. Clique em 'Executar Fluxo' para re-analisar."*

---

## 7. Página 4 — Exames e Pendências

**Rota:** `/exams`  
**Propósito:** Simular consulta ao sistema de laboratório e ação sobre resultados.

### Layout

**Filtros (topo):** tabs ou chips — Todos | Pendentes | Concluídos | Críticos

**Tabela de exames**

| Exame | Solicitado em | Origem | Status | Ação |
|---|---|---|---|---|
| Hemograma completo | 10:32 hoje | Protocolo | 🟡 Pendente | Simular resultado |
| Creatinina sérica | 10:32 hoje | Protocolo | 🟡 Pendente | Simular resultado |
| ... | | | | |

- Coluna **Origem:** badge "Protocolo" (azul) ou "Manual" (cinza)
- Coluna **Ação:** botão "Simular resultado" para exames pendentes

### Painel lateral de detalhe

Ao clicar em uma linha:
- Nome do exame, método, valores de referência (mock)
- Resultado (se `completed` ou `critical`)
- **Interpretação do assistente** (texto mock) ex: *"Creatinina em 4.2 mg/dL — valor significativamente elevado. Sugere lesão renal aguda. Recomenda-se avaliação nefrológica urgente."*
- Botão "Notificar responsável" → cria Alert mock com `severity: "moderate"` + toast

### Modal "Simular resultado"

- Campo numérico (valor) + unidade (pré-preenchida)
- Checkbox "Marcar como crítico"
- Ao confirmar:
  - `exam.status` → `"completed"` ou `"critical"`
  - Se crítico: cria Alert com `severity: "critical"`, equipe `"doctors"`, navega e destaca no Painel de Alertas
  - Toast: *"Resultado registrado. [Se crítico: Alerta crítico emitido para equipe médica.]"*

---

## 8. Página 5 — Sugestão de Ações Sugeridas

**Rota:** `/suggested-actions`  
**Propósito:** Saída estruturada do agente. Demonstra que a IA sugere e o médico decide.

### Layout — 2 colunas

**Coluna esquerda — Resumo do Caso**
- Hipótese diagnóstica (mock baseada no CID)
- Contexto clínico (3–4 linhas de texto clínico gerado)
- CID + protocolo de referência com link (fake) para o documento

**Coluna direita — Checklist de Ações Sugeridas**

Itens agrupados por tipo:

```
📋 EXAMES A SOLICITAR
  ☐ Hemograma completo        [Aceitar] [Modificar]
  ☐ Contagem de plaquetas     [Aceitar] [Modificar]
  ...

💊 PRESCRIÇÕES
  ☐ Avaliar início de DMARD   [Aceitar] [Modificar]
  ...

📝 OBSERVAÇÕES DE ENFERMAGEM
  ☐ Monitorar PA a cada 4h    [Aceitar] [Modificar]
  ...

🔄 REVISÃO
  ☐ Reavaliação em 24h        [Aceitar] [Modificar]
```

### Interações

- **Aceitar:** item fica verde com ✅, `status: "accepted"`
- **Modificar:** abre campo de texto inline para editar a descrição, ao salvar `status: "modified"` com badge "Modificado"
- **Rejeitar (hover):** ícone de X aparece, clique → `status: "rejected"`, item riscado
- **"Aceitar tudo":** botão no topo direito que aceita todos os sugeridos de uma vez

**Rodapé da página:**
- *"Protocolo: PCDT Artrite Psoriásica — CONITEC 2023"* (texto estático com ícone de documento)
- *"Esta é uma sugestão. A decisão final é do médico responsável."* — em cinza, itálico

---

## 9. Página 6 — Painel de Alertas

**Rota:** `/alerts`  
**Propósito:** Visão proativa. O sistema age, não apenas responde.

### Layout

**Filtros (topo):** por severidade (Crítico | Moderado | Informativo) e por equipe (Médicos | Enfermagem | Farmácia | Todos)

**Lista de alertas**

Cada card de alerta:
- Ícone de severidade (🔴🟡🔵) + título
- Paciente vinculado (clicável — navega para Dashboard daquele paciente)
- Timestamp
- Mensagem completa
- Botão "Marcar como resolvido" → `resolved: true`, item vai para seção colapsada "Resolvidos"

**Gráfico (sidebar direita)**
- Barras simples: volume de alertas por categoria na "última semana" (dados completamente mock, estáticos)
- Ex: Exames críticos: 8 | Medicamentos: 3 | Clínicos: 5

### Alertas mock pré-populados (demonstração)

```ts
const INITIAL_ALERTS = [
  {
    id: "a-01",
    patientId: "p-demo", // vinculado ao primeiro paciente admitido na demo
    severity: "info",
    category: "system",
    message: "Sistema iniciado. Aguardando admissão de pacientes.",
    team: "all",
    createdAt: new Date().toISOString(),
    resolved: false,
  }
];
```

---

## 10. Mapa de Transições

```
                        ┌─────────────────────────────────────────────────┐
                        │                    SIDEBAR                       │
                        │  [Seletor de paciente — apenas "admitted"]       │
                        │  Menu: Check-in | Dashboard | Chat | Fluxo |    │
                        │         Exames | Ações Sugeridas | Alertas               │
                        └─────────────────────────────────────────────────┘
                                            │
                        ┌───────────────────▼──────────────────────────────┐
                        │           Página 0 — Check-in                    │
                        │  Formulário → submit → AgentSpinner (1.5s)       │
                        └───────────────────┬──────────────────────────────┘
                                            │ auto-navega
                        ┌───────────────────▼──────────────────────────────┐
                        │        Página 3 — Fluxo de Decisão               │
                        │  Diagrama anima → Log aparece                    │
                        │  Botão "Ver ações sugeridas →"                   │
                        └──────┬──────────────────────────┬────────────────┘
                               │                          │
               ┌───────────────▼──────┐      ┌───────────▼────────────────┐
               │  Página 5 — Ações Sugeridas  │      │  Página 6 — Alertas        │
               │  Checklist de itens  │      │  (se fluxo crítico)        │
               └──────────────────────┘      └────────────────────────────┘

Página 1 — Dashboard
  ├── [Editar CID] → CIDEditModal → re-executa fluxo → Página 3
  ├── [Alta] → confirma → status "discharged" → remove da sidebar → /checkin
  └── [Simular sinal vital crítico] → novo Alert → badge em Alertas

Página 2 — Chat
  └── Pergunta rápida → resposta mock + fontes + raciocínio

Página 4 — Exames
  └── [Simular resultado crítico] → novo Alert crítico → badge em Alertas

Página 6 — Alertas
  └── [Paciente vinculado] → navega para Dashboard daquele paciente
```

---

## 11. Fluxos de Teste

Os três perfis abaixo cobrem os caminhos principais do grafo. **Todos devem ser admitidos via Página 0 durante a demo.**

---

### Fluxo A — João Silva (Artrite Psoriásica)
**Caminho:** Normal, protocolo bem definido, zero urgência

| Etapa | Ação | Resultado esperado |
|---|---|---|
| 1 | Admitir João, 67 anos, M, Leito "ENF-12", CID L40.5 | Agente carrega PCDT Artrite Psoriásica |
| 2 | Página 3 abre automaticamente | 5 nós ficam verdes, log exibe 5 exames identificados |
| 3 | Acessar Página 5 — Ações Sugeridas | 7 itens sugeridos (5 exames + 1 observação + 1 revisão) |
| 4 | Aceitar todos os itens de exame | Badges verdes, botão "Aceitar tudo" funcional |
| 5 | Acessar Página 4 — Exames | 5 exames com status "Pendente", origem "Protocolo" |
| 6 | Simular resultado: Creatinina = 1.1 (normal) | Status → "Concluído", sem alerta |
| 7 | Acessar Página 2 — Chat | Perguntas rápidas para L40.5 disponíveis |
| 8 | Perguntar "Quais exames estão pendentes?" | Resposta lista os 4 exames restantes + fontes no painel |

---

### Fluxo B — Maria Santos (Sepse)
**Caminho:** Crítico, alerta imediato, branch alternativa do grafo

| Etapa | Ação | Resultado esperado |
|---|---|---|
| 1 | Admitir Maria, 54 anos, F, Leito "UTI-02", CID A41.9 | Agente carrega Protocolo de Sepse |
| 2 | Página 3 abre automaticamente | Nó "Alerta Imediato" fica vermelho piscando |
| 3 | Log exibe | *"🚨 Caso crítico — alerta imediato para equipe médica"* |
| 4 | Página 6 — Alertas | Novo alerta crítico para equipe de médicos aparece no topo |
| 5 | Página 5 — Ações Sugeridas | Inclui "Antibioticoterapia empírica em até 1h" |
| 6 | Página 4 — Exames | Hemocultura e Lactato como prioridade (primeiros da lista) |
| 7 | Simular resultado: Lactato = 4.8 mmol/L (crítico, checkbox marcado) | Alert crítico criado, toast, badge de alertas atualiza |
| 8 | Página 1 — Dashboard | Sinal vital: SpO2 = 88% via "Simular sinal vital" → novo alerta |

---

### Fluxo C — Carlos Mendes (Pós-cirúrgico + Interação Medicamentosa)
**Caminho:** Alerta de farmácia, interação medicamentosa

| Etapa | Ação | Resultado esperado |
|---|---|---|
| 1 | Admitir Carlos, 41 anos, M, Leito "CIR-05", CID T81.4, medicamentos: "Warfarina 5mg, Ciprofloxacino 500mg" | Agente carrega Protocolo Pós-Cirúrgico |
| 2 | Página 3 | Log inclui *"⚠️ Possível interação medicamentosa detectada — encaminhado para farmácia"* |
| 3 | Página 6 — Alertas | Alerta com `category: "medication"`, `team: "pharmacy"` aparece |
| 4 | Filtrar alertas por "Farmácia" | Apenas o alerta de Carlos visível |
| 5 | Página 5 — Ações Sugeridas | Item "Verificar interação: antibiótico + anticoagulante" destacado |
| 6 | Modificar o item de ação sugerida | Campo inline editável, badge "Modificado" após salvar |
| 7 | Página 1 — Dashboard | Editar CID para M05.3 (Artrite Reumatoide) via modal |
| 8 | Banner amarelo em Página 3 | *"CID atualizado. Clique em 'Executar Fluxo' para re-analisar."* |
| 9 | Re-executar fluxo | Novos exames carregados (Artrite Reumatoide tem protocolo diferente) |

---

### Fluxo D — Alta de Paciente
**Caminho:** Ciclo de vida completo

| Etapa | Ação | Resultado esperado |
|---|---|---|
| 1 | Com João admitido, acessar Página 1 | Botão "Alta" visível no header |
| 2 | Clicar "Alta" | Modal de confirmação: *"Confirmar alta de João Silva?"* |
| 3 | Confirmar | `status → "discharged"`, removido do seletor da sidebar |
| 4 | Sidebar | Dropdown volta a mostrar apenas pacientes restantes (ou mensagem de nenhum ativo) |
| 5 | Toast | *"Paciente João Silva recebeu alta com sucesso."* |

---

## Notas para o Agente de Desenvolvimento

- **Não criar dados estáticos fora do store.** Toda informação de paciente deve passar pelo estado global para garantir consistência entre páginas.
- **O seletor de paciente na sidebar deve ser reativo** — ao admitir ou dar alta, atualiza imediatamente sem refresh.
- **Delays são intencionais.** O `AgentSpinner` e as animações sequenciais do log existem para comunicar que um processamento está ocorrendo. Use `setTimeout` ou similar; não eliminar por "otimização".
- **Manter o `protocolRef`** em todos os itens de ações sugeridas e exames gerados. Essa string aparece em múltiplas páginas (Ações Sugeridas, Chat, Fluxo) e deve ser consistente.
- **Alertas críticos** devem atualizar o badge da sidebar imediatamente após criação.
- **A página de Ações Sugeridas** deve ser inacessível (redirecionar para Check-in) se nenhum paciente estiver admitido.