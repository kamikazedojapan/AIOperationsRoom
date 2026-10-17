from __future__ import annotations

import io
import subprocess
import threading
from types import SimpleNamespace

import pytest

from backend import task_runner
from backend.providers import codex_local, ollama_local


class _FakeStdin:
    def write(self, value: str) -> int:
        return len(value)

    def close(self) -> None:
        pass


class _BlockingStdout:
    def __init__(self, released: threading.Event) -> None:
        self.released = released

    def __iter__(self):
        return self

    def __next__(self) -> str:
        self.released.wait(timeout=2)
        raise StopIteration


class _FakeCodexProcess:
    def __init__(self) -> None:
        self.pid = 1234
        self.stdin = _FakeStdin()
        self.released = threading.Event()
        self.stdout = _BlockingStdout(self.released)
        self.stderr = io.StringIO("")
        self.returncode: int | None = None
        self.stopped = False

    def poll(self):
        return self.returncode

    def terminate(self) -> None:
        self.stopped = True
        self.returncode = -15
        self.released.set()

    def kill(self) -> None:
        self.stopped = True
        self.returncode = -9
        self.released.set()

    def wait(self, timeout=None):
        if self.returncode is None:
            raise subprocess.TimeoutExpired("codex", timeout or 0)
        return self.returncode


class _BlockingOllamaResponse:
    def __init__(self) -> None:
        self.released = threading.Event()
        self.closed = False

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        self.close()
        return False

    def __iter__(self):
        return self

    def __next__(self) -> bytes:
        self.released.wait(timeout=2)
        raise StopIteration

    def close(self) -> None:
        self.closed = True
        self.released.set()


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


def test_codex_provider_cancels_without_waiting_for_stdout(monkeypatch):
    provider = codex_local.CodexTaskProvider()
    process = _FakeCodexProcess()
    monkeypatch.setattr(provider, "_executable", lambda: "codex")
    monkeypatch.setattr(provider, "_automation_args", lambda executable: [])
    monkeypatch.setattr(provider, "_cwd", lambda task: None)
    monkeypatch.setattr(codex_local.subprocess, "Popen", lambda *args, **kwargs: process)
    monkeypatch.setattr(
        provider,
        "_stop_process",
        lambda proc, windows=None: proc.terminate(),
    )

    with pytest.raises(task_runner.TaskCancelled):
        provider.run(
            {"id": "cancel-me", "prompt": "long task", "project_id": None},
            lambda *args, **kwargs: None,
            lambda: True,
        )

    assert process.stopped is True


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


def test_ollama_provider_cancels_without_waiting_for_stream(monkeypatch):
    provider = ollama_local.OllamaTaskProvider()
    response = _BlockingOllamaResponse()
    monkeypatch.setattr(provider, "models", lambda: ["qwen3:4b"])
    monkeypatch.setattr(
        ollama_local.request,
        "urlopen",
        lambda *args, **kwargs: response,
    )

    with pytest.raises(task_runner.TaskCancelled):
        provider.run(
            {
                "id": "cancel-ollama",
                "prompt": "long task",
                "agent": "general",
                "model": "qwen3:4b",
            },
            lambda *args, **kwargs: None,
            lambda: True,
        )

    assert response.closed is True


def test_default_registry_contains_local_providers():
    assert task_runner.get_provider("codex") is not None
    assert task_runner.get_provider("ollama") is not None
    assert task_runner.get_provider("openai_api") is not None
