# Padrão: Criar Novas Tabelas no Backend

## 1. Visão Geral Arquitetura

O backend segue uma arquitetura em **4 camadas** com responsabilidades bem definidas:

```
API Layer (routes)
    ↓
Service Layer (business logic)
    ↓
Repository Layer (data access)
    ↓
Model Layer (database schema)
    ↓
Database (SQLite)
```

### Fluxo de Dados Completo
1. **API Route** recebe request HTTP + `AsyncSession` (dependency injection)
2. **Service** contém lógica de negócio e transforma dados
3. **Repository** executa operações SQL puras (async)
4. **Model** define estrutura da tabela (SQLModel)
5. **Route** faz commit da sessão e retorna resposta

---

## 2. Convenções de Nomes

| Elemento | Convenção | Exemplo |
|----------|-----------|---------|
| **Tabela** | Snake_case, plural | `medications`, `clinical_assessments` |
| **Colunas** | Snake_case | `admitted_at`, `medication_name` |
| **ID Primária** | String com prefixo ou auto-int | `"md-<uuid>"` ou `id: int` |
| **Foreign Key** | `{table_singular}_id` | `patient_id`, `admission_id` |
| **Arquivo Model** | Snake_case.py | `medication.py` |
| **Arquivo Repository** | `{model_name}_repo.py` | `medication_repo.py` |
| **Arquivo Schema** | `{models_plural}.py` | `medications.py` |
| **Arquivo Service** | `{model_name}_service.py` | `medication_service.py` |
| **API File** | `{models_plural}.py` | `medications.py` |
| **Função Repository** | Verbo + Nome | `create_medication`, `list_by_patient_id`, `get_latest` |

### Convenção de ID
- **UUID com prefixo:** `"md-<uuid>"` para dados de domínio (mais legível)
- **Auto-increment int:** para dados transacionais/logs sem necessidade de distribuição
- **Escolha:** Use prefixo se a entidade for referenciada por usuários/frontend

### Aliases API (camelCase)
Use `populate_by_name=True` em schemas Pydantic para aceitar ambos:
```python
class MedicationResponse(BaseModel):
    medication_name: str = Field(alias="medicationName")
    administered_at: datetime = Field(alias="administeredAt")
```

---

## 3. Estrutura de Pastas

```
backend/
├── src/assistente_medico_api/
│   ├── models/
│   │   └── medication.py          ← Define tabela
│   ├── repositories/
│   │   └── medication_repo.py      ← Acesso a dados
│   ├── schemas/
│   │   └── medications.py          ← Serialização
│   ├── services/
│   │   └── medication_service.py   ← Lógica negócio
│   └── api/
│       └── medications.py          ← Rotas HTTP
├── alembic/versions/
│   └── YYYYMMDD_HHMM_add_medications_table.py  ← Migração
└── tests/
    └── test_medications_endpoint_contract.py   ← Testes
```

---

## 4. Implementação Passo a Passo

### 4.1 Passo 1: Criar Model (Models Layer)

**Arquivo:** `backend/src/assistente_medico_api/models/medication.py`

```python
from datetime import UTC, datetime
from uuid import uuid4
from sqlalchemy import Column, DateTime
from sqlmodel import Field, SQLModel

class Medication(SQLModel, table=True):
    __tablename__ = "medications"

    id: str = Field(default_factory=lambda: f"md-{uuid4()}", primary_key=True)
    patient_id: str = Field(foreign_key="patients.id", index=True)
    medication_name: str = Field(index=True)
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(UTC),
        sa_column=Column(DateTime(timezone=True), index=True),
    )
```

**Padrões Aplicados:**
- Herda de `SQLModel` com `table=True`
- ID com prefixo "md-" + UUID
- Foreign key com `index=True` (para JOINs)
- Timestamps com `UTC` timezone
- Exemplo mínimo (adicione demais campos e índices conforme o domínio)

---

### 4.2 Passo 2: Criar Schema (Schemas Layer)

**Arquivo:** `backend/src/assistente_medico_api/schemas/medications.py`

```python
from datetime import datetime
from pydantic import BaseModel, Field

class MedicationCreateRequest(BaseModel):
    patient_id: str
    medication_name: str


class MedicationResponse(BaseModel):
    model_config = {"populate_by_name": True}

    id: str
    patient_id: str = Field(alias="patientId")
    medication_name: str = Field(alias="medicationName")
    created_at: datetime = Field(alias="createdAt")
```

**Padrões Aplicados:**
- Classes separadas por operação (ex.: Create e Response)
- `populate_by_name=True` para aceitar snake_case e camelCase
- Aliases em camelCase para frontend
- Exemplo mínimo (adicione Patch/List conforme necessidade)

---

### 4.3 Passo 3: Criar Repository (Repository Layer)

**Arquivo:** `backend/src/assistente_medico_api/repositories/medication_repo.py`

```python
from sqlmodel import select
from sqlalchemy.ext.asyncio import AsyncSession
from assistente_medico_api.models import Medication


async def create_medication(session: AsyncSession, medication: Medication) -> Medication:
    session.add(medication)
    await session.flush()
    return medication


async def list_by_patient_id(session: AsyncSession, patient_id: str) -> list[Medication]:
    statement = select(Medication).where(Medication.patient_id == patient_id)
    result = await session.execute(statement)
    return result.scalars().all()
```

**Padrões Aplicados:**
- Todas funções são `async`
- `AsyncSession` é primeiro parâmetro
- Usam `select()` e operações SQLModel
- `flush()` no fim (não commit)
- Sem classe (funções puras)
- Exemplo mínimo (completar CRUD no arquivo real)

---

### 4.4 Passo 4: Criar Service (Service Layer)

**Arquivo:** `backend/src/assistente_medico_api/services/medication_service.py`

```python
from datetime import datetime, UTC
from sqlalchemy.ext.asyncio import AsyncSession
from assistente_medico_api.models import Medication
from assistente_medico_api.schemas.medications import (
    MedicationCreateRequest,
    MedicationResponse,
)
from assistente_medico_api.repositories import medication_repo
from assistente_medico_api.services.patient_service import get_patient_or_raise


async def create_medication(session: AsyncSession, request: MedicationCreateRequest) -> MedicationResponse:
    await get_patient_or_raise(session, request.patient_id)

    medication = Medication(
        patient_id=request.patient_id,
        medication_name=request.medication_name.strip(),
        created_at=datetime.now(UTC),
    )

    created = await medication_repo.create_medication(session, medication)
    return MedicationResponse(**created.model_dump())
```

**Padrões Aplicados:**
- Orquestra repositories
- Valida regras de negócio (patient exists)
- Transforma DTOs (request → model → response)
- Trata erros com HTTPException (quando aplicável)
- Exemplo mínimo (expanda para get/list/patch/delete)

---

### 4.5 Passo 5: Criar API Routes (API Layer)

**Arquivo:** `backend/src/assistente_medico_api/api/medications.py`

```python
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from assistente_medico_api.deps import get_session
from assistente_medico_api.schemas.medications import (
    MedicationCreateRequest,
    MedicationResponse,
)
from assistente_medico_api.services import medication_service


router = APIRouter(prefix="/medications", tags=["medications"])


@router.post("/", response_model=MedicationResponse, status_code=201)
async def create_medication(request: MedicationCreateRequest, session: AsyncSession = Depends(get_session)):
    try:
        result = await medication_service.create_medication(session, request)
        await session.commit()
        return result
    except HTTPException:
        await session.rollback()
        raise
```

**Padrões Aplicados:**
- Router com prefixo e tags
- Dependency injection para `AsyncSession`
- Commit após sucesso, rollback em erro
- Status codes apropriados (ex.: 201 para create)
- Exemplo mínimo (repita o padrão para os demais endpoints CRUD)
- Response models do tipo schema

---

### 4.6 Passo 6: Criar Migração (Alembic)

**Arquivo:** `backend/alembic/versions/20260417_1430_add_medications_table.py`

```python
"""Add medications table."""

from alembic import op
import sqlalchemy as sa

revision = '001_add_medications'
down_revision = '20260417_1200_initial_schema'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'medications',
        sa.Column('id', sa.String(), nullable=False),
        sa.Column('patient_id', sa.String(), nullable=False),
        sa.Column('medication_name', sa.String(), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.ForeignKeyConstraint(
            ['patient_id'],
            ['patients.id'],
            ondelete='CASCADE'
        ),
    )
    op.create_index('ix_medications_patient_id', 'medications', ['patient_id'])


def downgrade() -> None:
    op.drop_table('medications')
```

**Padrões Aplicados:**
- Naming: `YYYYMMDD_HHMM_description.py`
- Revision chain (down_revision)
- Índices em colunas frequentemente consultadas
- Foreign key com `ondelete='CASCADE'`
- Ambos `upgrade()` e `downgrade()`
- Exemplo mínimo (inclua todas as colunas do model na migração real)

---

### 4.7 Passo 7: Registrar no Main (Se necessário)

**Arquivo:** `backend/src/assistente_medico_api/main.py` (verify existing)

```python
# Verificar se medicamentos router está registrado
from assistente_medico_api.api import medications

app.include_router(medications.router)
```

---

## 5. Checklist de Implementação

Use este checklist ao criar uma nova tabela:

- [ ] **Model criado** (`models/nome_modelo.py`)
  - [ ] Herda `SQLModel` com `table=True`
  - [ ] Tem `__tablename__` e docstring
  - [ ] ID definido (prefixo + UUID ou auto-int)
  - [ ] Foreign keys com índices
  - [ ] Timestamps com UTC
  - [ ] Índices compostos se necessário
  
- [ ] **Schema criado** (`schemas/nomes_plurais.py`)
  - [ ] Request class (Create, Patch)
  - [ ] Response class com aliases camelCase
  - [ ] `populate_by_name=True`
  
- [ ] **Repository criado** (`repositories/nome_repo.py`)
  - [ ] Funções async puras (sem classe)
  - [ ] `AsyncSession` como primeiro parâmetro
  - [ ] CRUD básico (create, get, list, update, delete)
  - [ ] Queries reutilizáveis e nomeadas
  
- [ ] **Service criado** (`services/nome_service.py`)
  - [ ] Orquestra repositories
  - [ ] Validações de negócio
  - [ ] Transforma schemas
  - [ ] Trata erros com HTTPException
  
- [ ] **API criado** (`api/nomes_plurais.py`)
  - [ ] Router com prefixo e tags
  - [ ] CRUD endpoints
  - [ ] Dependency injection de session
  - [ ] Commit/rollback patterns
  - [ ] Docstrings nos endpoints
  
- [ ] **Migração criado** (`alembic/versions/`)
  - [ ] Arquivo nomeado com timestamp
  - [ ] `upgrade()` cria tabela
  - [ ] `downgrade()` remove tabela
  - [ ] Índices e foreign keys
  
- [ ] **Registrado no Main**
  - [ ] Router importado em `main.py`
  - [ ] `app.include_router()` chamado
  
- [ ] **Testes criados** (`tests/test_*.py`)
  - [ ] Testes de contrato do endpoint
  - [ ] Dados de entrada/saída validados

---

## 6. Exemplo Enxuto: Tabela "Medications"

Os trechos acima mostram um exemplo **enxuto** da tabela `medications`.

No código real, implemente os arquivos completos com CRUD, validações e todos os campos do domínio.

**Estrutura criada:**
```
✅ models/medication.py          (SQLModel com campos)
✅ schemas/medications.py        (Pydantic Request/Response)
✅ repositories/medication_repo.py (CRUD functions)
✅ services/medication_service.py (Business logic)
✅ api/medications.py            (FastAPI routes)
✅ alembic/versions/20260417_1430_add_medications_table.py (Migration)
✅ main.py updated              (Router registered)
```

---

## 7. Boas Práticas para IA Entender

1. **Separação Rigorosa de Camadas**: IA can follow predefined patterns
2. **Funções Puras no Repository**: Sem efeitos colaterais (flush/commit no caller)
3. **Docstrings Estruturadas**: Args, Returns, Raises em português/inglês
4. **Nomes Descritivos**: Verbos + Nomes (ex: `create_medication`, `list_by_patient_id`)
5. **Type Hints Completos**: `Optional[X]`, `list[Model]`, `AsyncSession`
6. **Índices Pensados**: Índices simples em FKs e colunas de query; compostos para joins
7. **Error Handling**: HTTPException com status_code e detail
8. **Transactional Semantics**: Commit em API, flush em repository
9. **Versioning**: Migrations versionadas com timestamp
10. **Reutilização**: Funções genéricas no repository (não repetir queries)

---

## 8. Próximos Passos Após Implementação

1. Rodar migração: `alembic upgrade head`
2. Criar testes de contrato (`test_medications_endpoint_contract.py`)
3. Testar manualmente com cURL/Postman
4. Documentar no API_ASSUMPTIONS.md (frontend)
5. Registrar decisão em `docs/dev-log/decisions/YYYYMMDD-*.md`
