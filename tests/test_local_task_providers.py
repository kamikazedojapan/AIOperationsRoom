from __future__ import annotations

from types import SimpleNamespace

from backend import task_runner
from backend.providers import codex_local, ollama_local


def test_codex_provider_detects_cli(monkeypatch):
    provider = codex_local.CodexTaskProvider()
    monkeypatch.setattr(codex_local.shutil, "which", lambda name: "C:/tools/codex.cmd")

    assert provider.available() is True
    assert provider.unavailable_reason() is None


def test_codex_provider_reports_missing_cli(monkeypatch):
    provider = codex_local.CodexTaskProvider()
    monkeypatch.setattr(codex_local.shutil, "which", lambda name: None)

    assert provider.available() is False
    assert "PATH" in (provider.unavailable_reason() or "")


def test_codex_provider_prefers_approve_for_me(monkeypatch):
    provider = codex_local.CodexTaskProvider()
    monkeypatch.setattr(
        codex_local.subprocess,
        "run",
        lambda *args, **kwargs: SimpleNamespace(
            stdout="--approve-for-me\n--sandbox <MODE>",
            stderr="",
        ),
    )

    assert provider._automation_args("codex") == ["--approve-for-me"]


def test_codex_provider_falls_back_to_legacy_full_auto(monkeypatch):
    provider = codex_local.CodexTaskProvider()
    monkeypatch.setattr(
        codex_local.subprocess,
        "run",
        lambda *args, **kwargs: SimpleNamespace(
            stdout="--full-auto\n--sandbox <MODE>",
            stderr="",
        ),
    )

    assert provider._automation_args("codex") == ["--full-auto"]


def test_codex_provider_falls_back_to_workspace_write(monkeypatch):
    provider = codex_local.CodexTaskProvider()
    monkeypatch.setattr(
        codex_local.subprocess,
        "run",
        lambda *args, **kwargs: SimpleNamespace(
            stdout="--sandbox <MODE>",
            stderr="",
        ),
    )

    assert provider._automation_args("codex") == ["--sandbox", "workspace-write"]


def test_ollama_provider_exposes_installed_models(monkeypatch):
    provider = ollama_local.OllamaTaskProvider()
    monkeypatch.setattr(
        provider,
        "_probe",
        lambda force=False: (True, ["qwen3:4b", "llama3.2:3b"], None),
    )

    assert provider.available() is True
    assert provider.models() == ["qwen3:4b", "llama3.2:3b"]
    assert provider.unavailable_reason() is None


def test_ollama_provider_requires_a_local_model(monkeypatch):
    provider = ollama_local.OllamaTaskProvider()
    monkeypatch.setattr(provider, "_probe", lambda force=False: (True, [], None))

    assert provider.available() is False
    assert "nenhum modelo" in (provider.unavailable_reason() or "").lower()


def test_default_registry_contains_local_providers():
    assert task_runner.get_provider("codex") is not None
    assert task_runner.get_provider("ollama") is not None
    assert task_runner.get_provider("openai_api") is not None
