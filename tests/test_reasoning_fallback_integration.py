import asyncio
from types import SimpleNamespace

import pytest
from llama_index.core.base.llms.types import ChatMessage

from mobilerun.agent.manager.events import ManagerContextEvent
from mobilerun.agent.manager.manager_agent import ManagerAgent
from mobilerun.agent.manager.prompts import ManagerResponseValidationError


def _response(content: str) -> SimpleNamespace:
    return SimpleNamespace(message=SimpleNamespace(content=content))


def _run(coro):
    return asyncio.run(coro)


class FakeContext:
    def __init__(self) -> None:
        self.events = []

    def write_event_to_stream(self, event) -> None:
        self.events.append(event)


def _manager() -> ManagerAgent:
    agent = object.__new__(ManagerAgent)
    agent.llm = SimpleNamespace(class_name=lambda: "FakeLLM")
    agent.agent_config = SimpleNamespace(streaming=False)
    agent.shared_state = SimpleNamespace(
        screenshot=None,
        message_history=[],
        previous_plan="",
        plan="",
        current_subgoal="",
        last_thought="",
        answer="",
        progress_summary="",
        append_memory=lambda text: None,
    )

    async def build_system_prompt() -> str:
        return "system"

    agent._build_system_prompt = build_system_prompt
    agent._build_messages_with_context = lambda **kwargs: [
        ChatMessage(role="user", content="prompt")
    ]
    return agent


@pytest.mark.parametrize(
    "invalid_response",
    [
        "<answer>Done</answer>",
        "<answer success='maybe'>Done</answer>",
        "<answer success='true'></answer>",
        "<plan>1. Continue checking the screen.</plan><answer success='true'>Done</answer>",
    ],
)
def test_manager_boundary_fails_closed_after_persistent_invalid_repair_output(
    monkeypatch, invalid_response
):
    calls = []

    async def fake_acall(llm, messages, stream=False):
        calls.append((llm, messages, stream))
        return _response(invalid_response)

    monkeypatch.setattr(
        "mobilerun.agent.manager.manager_agent.acall_with_retries", fake_acall
    )

    ctx = FakeContext()
    with pytest.raises(ManagerResponseValidationError):
        _run(_manager().get_response(ctx, ManagerContextEvent()))

    # One initial manager call and three corrective attempts; no response event
    # exists that could reach the executor after the validation failure.
    assert len(calls) == 4
    assert ctx.events == []


def test_manager_boundary_accepts_a_valid_corrective_response(monkeypatch):
    calls = []

    async def fake_acall(llm, messages, stream=False):
        calls.append((llm, messages, stream))
        if len(calls) == 1:
            return _response("<answer>Done</answer>")
        return _response("<answer success='false'>Blocked</answer>")

    monkeypatch.setattr(
        "mobilerun.agent.manager.manager_agent.acall_with_retries", fake_acall
    )

    manager = _manager()
    ctx = FakeContext()
    response_event = _run(manager.get_response(ctx, ManagerContextEvent()))
    details_event = _run(manager.process_response(ctx, response_event))

    assert len(calls) == 2
    assert details_event.answer == "Blocked"
    assert details_event.success is False


def test_manager_boundary_fails_closed_when_corrective_provider_call_fails(monkeypatch):
    calls = []

    async def fake_acall(llm, messages, stream=False):
        calls.append((llm, messages, stream))
        if len(calls) == 1:
            return _response("<answer>Done</answer>")
        raise RuntimeError("provider unavailable")

    monkeypatch.setattr(
        "mobilerun.agent.manager.manager_agent.acall_with_retries", fake_acall
    )

    ctx = FakeContext()
    with pytest.raises(ManagerResponseValidationError, match="success"):
        _run(_manager().get_response(ctx, ManagerContextEvent()))

    assert len(calls) == 2
    assert ctx.events == []
