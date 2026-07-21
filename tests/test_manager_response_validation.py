import asyncio
from pathlib import Path
from types import SimpleNamespace

import pytest
from llama_index.core.base.llms.types import ChatMessage

from mobilerun.agent.droid.droid_agent import MobileAgent
from mobilerun.agent.droid.events import (
    FinalizeEvent,
    ManagerInputEvent,
    ManagerPlanEvent,
)
from mobilerun.agent.manager.manager_agent import ManagerAgent
from mobilerun.agent.manager.prompts import (
    ManagerResponseValidationError,
    parse_manager_response,
    validate_manager_response,
)
from mobilerun.agent.manager.stateless_manager_agent import StatelessManagerAgent
from mobilerun.agent.utils.prompt_resolver import PromptResolver
from mobilerun.config_manager.config_manager import AgentConfig, ManagerConfig

REPO_ROOT = Path(__file__).resolve().parents[1]


def _response(content: str) -> SimpleNamespace:
    return SimpleNamespace(message=SimpleNamespace(content=content))


def _stateful_manager() -> ManagerAgent:
    agent = object.__new__(ManagerAgent)
    agent.llm = SimpleNamespace()
    agent.agent_config = SimpleNamespace(streaming=False)
    return agent


def _stateless_manager() -> StatelessManagerAgent:
    agent = object.__new__(StatelessManagerAgent)
    agent.llm = SimpleNamespace()
    return agent


def _run(coro):
    return asyncio.run(coro)


def test_parse_final_success_attribute_is_bound_to_matching_final_tag():
    parsed = parse_manager_response(
        """
        <thought>done</thought>
        <request_accomplished reason='checked' success='TRUE'>
        Android 16 is installed.
        </request_accomplished>
        """
    )

    assert parsed["answer"] == "Android 16 is installed."
    assert parsed["success"] is True
    assert parsed["final_tag"] == "request_accomplished"


def test_parse_answer_alias_and_missing_success_stays_none():
    parsed = parse_manager_response("<answer>Done</answer>")

    assert parsed["answer"] == "Done"
    assert parsed["success"] is None
    assert parsed["final_tag"] == "answer"


@pytest.mark.parametrize(
    "response",
    [
        "<plan>1. Open Settings</plan>",
        "<request_accomplished success='true'>Done</request_accomplished>",
        "<request_accomplished success='false'>Blocked</request_accomplished>",
        '<answer success="true">Done</answer>',
        '<answer success="false">Blocked</answer>',
    ],
)
def test_validate_accepts_exactly_one_nonempty_manager_result(response):
    validation = validate_manager_response(parse_manager_response(response))

    assert validation.is_valid
    assert validation.error_message is None


@pytest.mark.parametrize(
    "response, expected_valid",
    [
        ("<answer>Done</answer>", False),
        ("<answer success='maybe'>Done</answer>", False),
        ("<answer success=true>Done</answer>", False),
        ("<answer status='complete' success=\"true\">Done</answer>", True),
        ("<answer success='false' reason=\"blocked\">Blocked</answer>", True),
    ],
)
def test_validate_requires_one_explicit_quoted_success_attribute(
    response, expected_valid
):
    validation = validate_manager_response(parse_manager_response(response))

    assert validation.is_valid is expected_valid
    if not expected_valid:
        assert "success" in validation.error_message


@pytest.mark.parametrize(
    "response",
    [
        '<answer data-success="true">Not complete</answer>',
        "<answer note=\"example: success='true'\">Not complete</answer>",
        '<answer success="true" success="false">Contradictory</answer>',
        "<answer success='true' success='true'>Duplicate</answer>",
    ],
)
def test_validate_rejects_ambiguous_or_lookalike_success_attributes(response):
    validation = validate_manager_response(parse_manager_response(response))

    assert not validation.is_valid
    assert "success" in validation.error_message


@pytest.mark.parametrize(
    "response, expected_error",
    [
        ("", "provide exactly one"),
        (
            "<plan>1. Read version</plan>"
            "<request_accomplished success='true'>Android 16</request_accomplished>",
            "exactly one",
        ),
        ("<plan></plan><answer success='true'>Done</answer>", "exactly one"),
        ("<plan>1. Read version</plan><answer success='true'></answer>", "exactly one"),
        ("<plan></plan>", "must not be empty"),
        ("<answer success='true'></answer>", "must not be empty"),
        (
            "<plan>1. Open Settings</plan><plan>2. Read version</plan>",
            "multiple <plan>",
        ),
        (
            "<answer success='true'>Done</answer>"
            "<request_accomplished success='false'>Blocked</request_accomplished>",
            "multiple final",
        ),
        (
            "<answer success='true'></answer>"
            "<request_accomplished success='false'>Blocked</request_accomplished>",
            "multiple final",
        ),
        (
            "<answer success='true'>Done</answer><answer success='false'>Blocked</answer>",
            "multiple final",
        ),
        (
            "<answer success='true'></answer><answer success='false'></answer>",
            "multiple final",
        ),
    ],
)
def test_validate_rejects_mixed_empty_and_duplicate_results(response, expected_error):
    validation = validate_manager_response(parse_manager_response(response))

    assert not validation.is_valid
    assert expected_error in validation.error_message


@pytest.mark.parametrize(
    "response",
    [
        "<thought><answer success='true'>not a result</answer></thought>"
        "<plan>1. Read version</plan>",
        "<add_memory><plan>not a result</plan></add_memory><answer success='true'>Done</answer>",
        "<plan>1. Read <answer success='true'>not a result</answer></plan>",
        "<plan>1. Read version</plan><answer success='true'/>",
        "<plan>1. Read version</plan><answer success='true'>Dangling",
        '<answer success="true">Done</answer success="false">',
        "< plan>1. Read version</ plan>",
        "< plan>ignored</ plan><answer success='true'>Done</answer>",
    ],
)
def test_validate_rejects_nested_dangling_and_self_closing_control_tags(response):
    parsed = parse_manager_response(response)
    validation = validate_manager_response(parsed)

    assert not validation.is_valid
    assert "malformed or nested" in validation.error_message


def test_nested_final_tag_does_not_become_a_terminal_result():
    parsed = parse_manager_response(
        "<thought><answer success='true'>not a result</answer></thought>"
        "<plan>1. Read version</plan>"
    )

    assert parsed["answer"] == ""
    assert parsed["success"] is None


def test_stateful_manager_retries_invalid_response_then_returns_valid(monkeypatch):
    calls = []

    async def fake_acall(llm, messages, stream=False):
        calls.append((llm, messages, stream))
        return _response(
            "<request_accomplished success='true'>Android 16.</request_accomplished>"
        )

    monkeypatch.setattr(
        "mobilerun.agent.manager.manager_agent.acall_with_retries", fake_acall
    )

    output = _run(
        _stateful_manager()._validate_and_retry(
            [ChatMessage(role="user", content="prompt")],
            "<plan>1. Read version</plan>"
            "<request_accomplished success='true'>Android 16.</request_accomplished>",
        )
    )

    assert output == (
        "<request_accomplished success='true'>Android 16.</request_accomplished>"
    )
    assert len(calls) == 1
    assert calls[0][2] is False


@pytest.mark.parametrize(
    "invalid_response",
    [
        "<plan>1. Read version</plan>"
        "<request_accomplished success='true'>Android 16.</request_accomplished>",
        "<answer>Done</answer>",
    ],
)
def test_stateful_manager_fails_closed_after_three_invalid_repairs(
    monkeypatch, invalid_response
):
    calls = []

    async def fake_acall(llm, messages, stream=False):
        calls.append((llm, messages, stream))
        return _response(invalid_response)

    monkeypatch.setattr(
        "mobilerun.agent.manager.manager_agent.acall_with_retries", fake_acall
    )

    with pytest.raises(ManagerResponseValidationError):
        _run(
            _stateful_manager()._validate_and_retry(
                [ChatMessage(role="user", content="prompt")], invalid_response
            )
        )

    assert len(calls) == 3


def test_stateful_manager_fails_closed_when_corrective_provider_call_fails(monkeypatch):
    calls = []

    async def fake_acall(llm, messages, stream=False):
        calls.append((llm, messages, stream))
        raise RuntimeError("provider unavailable")

    monkeypatch.setattr(
        "mobilerun.agent.manager.manager_agent.acall_with_retries", fake_acall
    )

    with pytest.raises(ManagerResponseValidationError, match="success"):
        _run(
            _stateful_manager()._validate_and_retry(
                [ChatMessage(role="user", content="prompt")], "<answer>Done</answer>"
            )
        )

    assert len(calls) == 1


def test_stateless_manager_retries_invalid_response_then_returns_valid(monkeypatch):
    calls = []

    async def fake_acall(llm, messages):
        calls.append((llm, messages))
        return _response("<answer success='false'>Blocked</answer>")

    monkeypatch.setattr(
        "mobilerun.agent.manager.stateless_manager_agent.acall_with_retries", fake_acall
    )

    output = _run(
        _stateless_manager()._validate_and_retry(
            [{"role": "user", "content": [{"text": "prompt"}]}],
            "<answer>Done</answer>",
        )
    )

    assert output == "<answer success='false'>Blocked</answer>"
    assert len(calls) == 1


def test_stateless_manager_fails_closed_after_three_invalid_repairs(monkeypatch):
    calls = []
    invalid_response = (
        "<plan>1. Read version</plan><answer success='true'>Android 16.</answer>"
    )

    async def fake_acall(llm, messages):
        calls.append((llm, messages))
        return _response(invalid_response)

    monkeypatch.setattr(
        "mobilerun.agent.manager.stateless_manager_agent.acall_with_retries", fake_acall
    )

    with pytest.raises(ManagerResponseValidationError):
        _run(
            _stateless_manager()._validate_and_retry(
                [{"role": "user", "content": [{"text": "prompt"}]}],
                invalid_response,
            )
        )

    assert len(calls) == 3


def test_stateless_manager_fails_closed_when_corrective_provider_call_fails(
    monkeypatch,
):
    calls = []

    async def fake_acall(llm, messages):
        calls.append((llm, messages))
        raise RuntimeError("provider unavailable")

    monkeypatch.setattr(
        "mobilerun.agent.manager.stateless_manager_agent.acall_with_retries", fake_acall
    )

    with pytest.raises(ManagerResponseValidationError, match="exactly one"):
        _run(
            _stateless_manager()._validate_and_retry(
                [{"role": "user", "content": [{"text": "prompt"}]}],
                "<plan>1. Read version</plan><answer success='true'>Android 16.</answer>",
            )
        )

    assert len(calls) == 1


def test_droid_agent_validation_failure_finalizes_without_executor_invocation():
    class FakeHandler:
        async def stream_events(self):
            if False:
                yield None

        def __await__(self):
            async def fail():
                raise ManagerResponseValidationError("bad manager response")

            return fail().__await__()

    events = []
    agent = object.__new__(MobileAgent)
    agent.shared_state = SimpleNamespace(
        step_number=0,
        drain_user_messages=lambda: [],
    )
    agent.config = SimpleNamespace(agent=SimpleNamespace(max_steps=5))
    agent.manager_agent = SimpleNamespace(run=lambda: FakeHandler())
    agent.handle_stream_event = lambda *_: pytest.fail("executor path must not run")
    ctx = SimpleNamespace(write_event_to_stream=events.append)

    result = _run(agent.run_manager(ctx, ManagerInputEvent()))

    assert isinstance(result, FinalizeEvent)
    assert result.success is False
    assert result.reason == "bad manager response"
    assert events == []


@pytest.mark.parametrize(
    "success, answer",
    [
        (None, "Done, but success is missing."),
        (False, "Could not complete the task."),
    ],
)
def test_droid_agent_never_treats_unknown_or_false_success_as_success(success, answer):
    agent = object.__new__(MobileAgent)
    agent.shared_state = SimpleNamespace(
        pending_user_messages=[],
        progress_summary="",
    )

    event = ManagerPlanEvent(
        plan="",
        current_subgoal="",
        thought="done",
        answer=answer,
        success=success,
    )

    result = _run(agent.handle_manager_plan(SimpleNamespace(), event))

    assert isinstance(result, FinalizeEvent)
    assert result.success is False
    assert result.reason == answer


def test_stateless_manager_uses_the_configured_manager_prompt_path(monkeypatch):
    configured_prompt = REPO_ROOT / "mobilerun/config/prompts/manager/trained.jinja2"
    agent = object.__new__(StatelessManagerAgent)
    agent.agent_config = AgentConfig(
        manager=ManagerConfig(stateless=True, system_prompt=str(configured_prompt))
    )
    agent.prompt_resolver = PromptResolver()
    agent.shared_state = SimpleNamespace(
        instruction="Read Android version",
        device_date="2026-07-21",
        previous_plan="",
        previous_formatted_device_state="",
        agent_memory="",
        last_thought="",
        progress_summary="",
        formatted_device_state="",
    )
    agent._build_action_history = lambda: []
    loaded_paths = []

    async def fake_load_prompt(path, variables):
        loaded_paths.append(path)
        return "configured prompt"

    monkeypatch.setattr(
        "mobilerun.agent.manager.stateless_manager_agent.PromptLoader.load_prompt",
        fake_load_prompt,
    )

    assert _run(agent._build_prompt()) == "configured prompt"
    assert loaded_paths == [str(configured_prompt)]


def test_manager_prompt_contracts_and_custom_prompt_docs_require_exactly_one_result():
    prompt_dir = REPO_ROOT / "mobilerun/config/prompts/manager"
    for prompt_name in (
        "system.jinja2",
        "rev1.jinja2",
        "stateless.jinja2",
        "trained.jinja2",
    ):
        prompt = (prompt_dir / prompt_name).read_text()
        assert "exactly one" in prompt.lower()
        assert "both <plan>" in prompt.lower()

    docs = (REPO_ROOT / "docs/concepts/prompts.mdx").read_text()
    assert "exactly one non-empty result tag" in docs.lower()
    assert '<request_accomplished success="true">' in docs
    assert docs.count("exactly one") >= 3
    assert '<request_accomplished success="true|false">' in docs

    custom_variables_docs = (
        REPO_ROOT / "docs/features/custom-variables.mdx"
    ).read_text()
    sdk_docs = (REPO_ROOT / "docs/sdk/droid-agent.mdx").read_text()
    for documented_prompt in (custom_variables_docs, sdk_docs):
        assert "exactly one non-empty result tag" in documented_prompt.lower()
        assert '<request_accomplished success="true|false">' in documented_prompt
