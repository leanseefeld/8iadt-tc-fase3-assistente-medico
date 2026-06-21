"""Persistência de chamadas auxiliares LLM por mensagem do assistente."""

from __future__ import annotations

from datetime import UTC, datetime
import pytest
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlmodel import select

from assistente_medico_api.config import Settings
from assistente_medico_api.graph.llm_client import append_aux_trace_entry, tracked_ainvoke
from assistente_medico_api.graph.nodes.generate import GENERATE_SYSTEM_PROMPT
from assistente_medico_api.graph.nodes.router import router_search_needed_node
from assistente_medico_api.models.conversation import Conversation, ConversationMessage
from assistente_medico_api.models.conversation_message_llm_call import ConversationMessageLlmCall
from assistente_medico_api.repositories import llm_interaction_log_repo
from assistente_medico_api.services import chat_persistence
from assistente_medico_api.services.llm_interaction_log import persist_aux_trace


class _FakeLLM:
    async def ainvoke(self, messages):
        return AIMessage(content='{"route":"direct","reason":"test","confidence":0.9}')


@pytest.mark.asyncio
async def test_tracked_ainvoke_appends_trace_when_enabled():
    settings = Settings(llm_interaction_log_enabled=True)
    trace: list[dict] = []
    llm = _FakeLLM()
    messages = [SystemMessage(content="sys"), HumanMessage(content="oi")]
    await tracked_ainvoke(
        llm,
        messages,
        call_type="router",
        trace=trace,
        settings=settings,
    )
    assert len(trace) == 1
    assert trace[0]["call_type"] == "router"
    assert trace[0]["llm_input"][0]["role"] == "system"
    assert "route" in trace[0]["llm_output"]


@pytest.mark.asyncio
async def test_tracked_ainvoke_noop_when_disabled():
    settings = Settings(llm_interaction_log_enabled=False)
    trace: list[dict] = []
    llm = _FakeLLM()
    await tracked_ainvoke(
        llm,
        [HumanMessage(content="x")],
        call_type="router",
        trace=trace,
        settings=settings,
    )
    assert trace == []


@pytest.mark.asyncio
async def test_router_node_returns_aux_trace(monkeypatch):
    settings = Settings(llm_interaction_log_enabled=True)

    async def _fake_tracked(llm, messages, *, call_type, trace, settings):
        append_aux_trace_entry(
            trace,
            call_type=call_type,
            messages=messages,
            result_content='{"route":"rag"}',
            settings=settings,
        )
        return AIMessage(content='{"route":"rag"}')

    monkeypatch.setattr(
        "assistente_medico_api.graph.nodes.router.tracked_ainvoke",
        _fake_tracked,
    )
    monkeypatch.setattr(
        "assistente_medico_api.graph.nodes.router.build_llm",
        lambda _settings: _FakeLLM(),
    )

    out = await router_search_needed_node(
        {"query": "tratamento diabetes", "reasoning_steps": []},
        settings=settings,
    )
    assert len(out["aux_llm_trace"]) == 1
    assert out["aux_llm_trace"][0]["call_type"] == "router"


@pytest.mark.asyncio
async def test_persist_aux_trace_writes_rows(
    test_session_factory: async_sessionmaker[AsyncSession],
):
    settings = Settings(llm_interaction_log_enabled=True)
    async with test_session_factory() as session:
        conv = Conversation(
            id="thread-llm-log",
            doctor_id="dr-1",
            patient_id="p1",
            system_prompt=GENERATE_SYSTEM_PROMPT,
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
        )
        session.add(conv)
        await session.flush()
        assistant = ConversationMessage(
            conversation_id=conv.id,
            author="assistant",
            content="resposta",
            created_at=datetime.now(UTC),
        )
        session.add(assistant)
        await session.flush()

        await persist_aux_trace(
            session,
            assistant_message_id=assistant.id,
            trace=[
                {
                    "call_type": "router",
                    "sequence": 0,
                    "model": "llama3.2:3b",
                    "llm_input": [{"role": "user", "content": "q"}],
                    "llm_output": "out",
                }
            ],
            settings=settings,
        )
        await session.commit()

        rows = await llm_interaction_log_repo.list_by_assistant_message_id(
            session,
            assistant.id,
        )
    assert len(rows) == 1
    assert rows[0].call_type == "router"
    assert rows[0].llm_output == "out"


@pytest.mark.asyncio
async def test_persist_aux_trace_skips_when_disabled(
    test_session_factory: async_sessionmaker[AsyncSession],
):
    settings = Settings(llm_interaction_log_enabled=False)
    async with test_session_factory() as session:
        conv = Conversation(
            id="thread-off",
            doctor_id="dr-1",
            patient_id="p1",
            system_prompt=GENERATE_SYSTEM_PROMPT,
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
        )
        session.add(conv)
        await session.flush()
        assistant = ConversationMessage(
            conversation_id=conv.id,
            author="assistant",
            content="resposta",
            created_at=datetime.now(UTC),
        )
        session.add(assistant)
        await session.flush()

        await persist_aux_trace(
            session,
            assistant_message_id=assistant.id,
            trace=[{"call_type": "router", "llm_input": [], "llm_output": "x"}],
            settings=settings,
        )
        await session.commit()

        count = len(
            list(
                (
                    await session.execute(select(ConversationMessageLlmCall))
                ).scalars()
            )
        )
    assert count == 0


@pytest.mark.asyncio
async def test_list_all_llm_interactions_unions_generate_and_aux(
    test_session_factory: async_sessionmaker[AsyncSession],
):
    async with test_session_factory() as session:
        conv = Conversation(
            id="thread-union",
            doctor_id="dr-1",
            patient_id="p1",
            system_prompt=GENERATE_SYSTEM_PROMPT,
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
        )
        session.add(conv)
        await session.flush()
        assistant = ConversationMessage(
            conversation_id=conv.id,
            author="assistant",
            content="final",
            llm_input=[{"role": "system", "content": "sys"}],
            llm_output="gerado",
            created_at=datetime.now(UTC),
        )
        session.add(assistant)
        await session.flush()
        session.add(
            ConversationMessageLlmCall(
                assistant_message_id=assistant.id,
                call_type="router",
                sequence=0,
                model="llama3.2:3b",
                llm_input=[{"role": "user", "content": "q"}],
                llm_output="rag",
            )
        )
        await session.commit()

        items = await llm_interaction_log_repo.list_all_llm_interactions_for_message(
            session,
            assistant.id,
        )
    call_types = [item["call_type"] for item in items]
    assert "generate" in call_types
    assert "router" in call_types


@pytest.mark.asyncio
async def test_append_turn_persists_aux_trace(
    test_session_factory: async_sessionmaker[AsyncSession],
):
    settings = Settings(llm_interaction_log_enabled=True)
    async with test_session_factory() as session:
        conv = Conversation(
            id="thread-append",
            doctor_id="dr-1",
            patient_id="p1",
            system_prompt=GENERATE_SYSTEM_PROMPT,
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
        )
        session.add(conv)
        await session.commit()

        msg_id = await chat_persistence.append_turn(
            session,
            conversation=conv,
            doctor_message="pergunta",
            final_state={
                "answer": "ok",
                "generate_llm_input": [{"role": "user", "content": "pergunta"}],
                "generate_llm_output": "bruto",
                "aux_llm_trace": [
                    {
                        "call_type": "guardrail_classify",
                        "sequence": 0,
                        "model": settings.llm_chat_model,
                        "llm_input": [{"role": "user", "content": "ok"}],
                        "llm_output": '{"verdict":"SEGURO","reason":""}',
                    }
                ],
            },
            settings=settings,
        )
        await session.commit()

        rows = await llm_interaction_log_repo.list_by_assistant_message_id(session, msg_id)
    assert len(rows) == 1
    assert rows[0].call_type == "guardrail_classify"
