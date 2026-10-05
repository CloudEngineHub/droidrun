import asyncio
import json
from types import SimpleNamespace

import pytest

from mobilerun.app_cards.providers.composite_provider import CompositeAppCardProvider
from mobilerun.app_cards.providers.local_provider import LocalAppCardProvider
from mobilerun.app_cards.providers.server_provider import ServerAppCardProvider


def _write_cards(folder, mapping, cards):
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "app_cards.json").write_text(json.dumps(mapping))
    for name, text in cards.items():
        (folder / name).write_text(text)


@pytest.fixture
def cards_dir(tmp_path):
    _write_cards(
        tmp_path / "android",
        {"com.zhiliaoapp.musically": "tiktok.md", "com.example.broken": ["x.md"]},
        {"tiktok.md": "ANDROID TIKTOK"},
    )
    _write_cards(
        tmp_path / "ios",
        {"com.zhiliaoapp.musically": "tiktok.md"},
        {"tiktok.md": "IOS TIKTOK"},
    )
    return tmp_path


def _load(provider, package, platform):
    return asyncio.run(provider.load_app_card(package, "goal", platform))


def test_local_provider_reads_the_folder_for_each_platform(cards_dir) -> None:
    provider = LocalAppCardProvider(str(cards_dir))

    assert _load(provider, "com.zhiliaoapp.musically", "android") == "ANDROID TIKTOK"
    assert _load(provider, "com.zhiliaoapp.musically", "ios") == "IOS TIKTOK"
    assert _load(provider, "com.zhiliaoapp.musically", None) == ""


def test_single_app_cards_json_is_used_for_a_platform_without_a_folder(
    tmp_path,
) -> None:
    _write_cards(tmp_path, {"com.example.notes": "notes.md"}, {"notes.md": "SHARED"})
    _write_cards(
        tmp_path / "ios", {"com.example.notes": "notes.md"}, {"notes.md": "IOS"}
    )
    provider = LocalAppCardProvider(str(tmp_path))

    assert _load(provider, "com.example.notes", "android") == "SHARED"
    assert _load(provider, "com.example.notes", "ios") == "IOS"
    assert _load(provider, "com.example.notes", None) == "SHARED"


def test_local_provider_ignores_an_invalid_mapping_value(cards_dir) -> None:
    provider = LocalAppCardProvider(str(cards_dir))

    assert _load(provider, "com.example.broken", "android") == ""


def test_relative_folder_comes_entirely_from_the_working_dir(
    tmp_path, monkeypatch
) -> None:
    from mobilerun.config_manager.path_resolver import PathResolver

    work, package = tmp_path / "work", tmp_path / "package"
    _write_cards(
        work / "cards" / "android", {"com.app": "a.md"}, {"a.md": "USER ANDROID"}
    )
    _write_cards(package / "cards" / "ios", {"com.app": "a.md"}, {"a.md": "BUNDLED"})
    monkeypatch.chdir(work)
    monkeypatch.setattr(PathResolver, "get_project_root", staticmethod(lambda: package))
    provider = LocalAppCardProvider("cards")

    assert _load(provider, "com.app", "android") == "USER ANDROID"
    assert _load(provider, "com.app", "ios") == ""


def test_server_provider_sends_the_platform(monkeypatch) -> None:
    sent = []

    class FakeClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

        async def post(self, url, json):
            sent.append(json)
            return SimpleNamespace(status_code=200, json=lambda: {"app_card": "CARD"})

    monkeypatch.setattr(
        "mobilerun.app_cards.providers.server_provider.httpx.AsyncClient", FakeClient
    )
    provider = ServerAppCardProvider(server_url="https://cards.example")

    assert _load(provider, "com.zhiliaoapp.musically", "ios") == "CARD"
    assert _load(provider, "com.zhiliaoapp.musically", "android") == "CARD"
    assert [payload["platform"] for payload in sent] == ["ios", "android"]


def test_composite_provider_passes_the_platform_to_the_local_fallback(
    cards_dir, monkeypatch
) -> None:
    provider = CompositeAppCardProvider(
        server_url="https://cards.example", app_cards_dir=str(cards_dir)
    )

    async def no_server_card(*args, **kwargs):
        return ""

    monkeypatch.setattr(provider.server_provider, "load_app_card", no_server_card)

    assert _load(provider, "com.zhiliaoapp.musically", "ios") == "IOS TIKTOK"


def test_manager_loads_the_card_for_the_device_platform(cards_dir) -> None:
    from mobilerun.agent.manager.manager_agent import ManagerAgent

    calls = []

    class RecordingProvider:
        async def load_app_card(self, package_name, instruction="", platform=None):
            calls.append((package_name, platform))
            return "CARD"

    manager = ManagerAgent.__new__(ManagerAgent)
    manager.app_card_config = SimpleNamespace(enabled=True)
    manager.app_card_provider = RecordingProvider()
    manager.shared_state = SimpleNamespace(
        current_package_name="com.zhiliaoapp.musically",
        instruction="goal",
        platform="iOS",
        app_card="",
    )

    asyncio.run(manager._load_app_card())

    assert calls == [("com.zhiliaoapp.musically", "ios")]
    assert manager.shared_state.app_card == "CARD"


@pytest.mark.parametrize(
    ("platform", "expected"),
    [("Android", "android"), ("iOS", "ios"), ("VisualRemote", None), (None, None)],
)
def test_manager_sends_only_android_or_ios(platform, expected) -> None:
    from mobilerun.agent.manager.manager_agent import _card_platform

    assert _card_platform(platform) == expected
