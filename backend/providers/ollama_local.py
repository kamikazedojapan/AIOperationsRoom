"""Local Ollama TaskProvider for Agent Console."""

from __future__ import annotations

import json
import os
import queue
import threading
import time
from urllib import error, request

from backend.task_runner import ProviderResult, TaskCancelled


AGENT_INSTRUCTIONS = {
    "general": (
        "Complete the user's task carefully. Be explicit about limitations. "
        "You are running locally and do not have implicit access to project files or tools."
    ),
    "coder": (
        "Act as a local software engineering assistant. Reason carefully about code, "
        "but do not claim to have read, changed, or executed files unless their contents "
        "were explicitly provided in the task."
    ),
    "reviewer": (
        "Act as a rigorous reviewer. Identify correctness, security, maintainability, "
        "and testing issues from the material actually provided."
    ),
}


class _QwenThinkGuard:
    """Prevent Qwen3 reasoning text from leaking into task output/timeline.

    Some Ollama/Qwen3 combinations can still place reasoning text in `message.content`
    even when `think=false`, commonly ending it with `</think>`. For Qwen3 we buffer
    content until that boundary is known. If no boundary appears, the buffered text is
    treated as the normal answer at the end of the stream.
    """

    close_tag = "</think>"
    open_tag = "<think>"

    def __init__(self) -> None:
        self._buffer: list[str] = []
        self._released = False

    def feed(self, content: str) -> str:
        if self._released:
            return content

        self._buffer.append(content)
        combined = "".join(self._buffer)
        close_at = combined.find(self.close_tag)
        if close_at < 0:
            return ""

        self._released = True
        self._buffer.clear()
        return combined[close_at + len(self.close_tag):].lstrip()

    def finish(self) -> str:
        if self._released:
            return ""

        combined = "".join(self._buffer)
        self._buffer.clear()
        open_at = combined.find(self.open_tag)
        if open_at >= 0:
            return combined[:open_at].rstrip()
        return combined


def _base_url() -> str:
    value = (
        os.environ.get("AI_OPERATIONS_ROOM_OLLAMA_URL")
        or os.environ.get("OLLAMA_HOST")
        or "http://127.0.0.1:11434"
    ).strip()
    if not value.startswith(("http://", "https://")):
        value = "http://" + value
    return value.rstrip("/")


class OllamaTaskProvider:
    source = "ollama"

    def __init__(self) -> None:
        self._probe_at = 0.0
        self._probe_result: tuple[bool, list[str], str | None] = (False, [], None)

    def _probe(self, *, force: bool = False) -> tuple[bool, list[str], str | None]:
        now = time.monotonic()
        if not force and now - self._probe_at < 2:
            return self._probe_result

        try:
            with request.urlopen(f"{_base_url()}/api/tags", timeout=0.6) as response:
                payload = json.loads(response.read().decode("utf-8"))
            names = []
            for item in payload.get("models", []):
                if not isinstance(item, dict):
                    continue
                name = item.get("name") or item.get("model")
                if isinstance(name, str) and name:
                    names.append(name)
            result = (True, sorted(dict.fromkeys(names)), None)
        except (OSError, ValueError, json.JSONDecodeError, error.URLError) as exc:
            result = (False, [], str(exc))

        self._probe_at = now
        self._probe_result = result
        return result

    def models(self) -> list[str]:
        reachable, models, _ = self._probe()
        return models if reachable else []

    def available(self) -> bool:
        reachable, models, _ = self._probe()
        return reachable and bool(models)

    def unavailable_reason(self) -> str | None:
        reachable, models, detail = self._probe()
        if not reachable:
            return (
                "Ollama não respondeu em "
                f"{_base_url()}. Inicie o serviço local antes de executar uma task."
                + (f" ({detail})" if detail else "")
            )
        if not models:
            return "Ollama está ativo, mas nenhum modelo local está instalado."
        return None

    @staticmethod
    def _pump_response(response, items: queue.Queue[tuple[str, object | None]]) -> None:
        """Read Ollama's stream off the runner thread so cancellation stays responsive."""
        try:
            for raw_line in response:
                items.put(("line", raw_line))
        except Exception as exc:  # network/read errors are surfaced on the runner thread
            items.put(("error", exc))
        finally:
            items.put(("done", None))

    def run(self, task: dict, emit, is_cancelled) -> ProviderResult:
        installed = self.models()
        if not installed:
            raise RuntimeError(self.unavailable_reason() or "Nenhum modelo Ollama disponível.")

        requested = str(task.get("model") or "").strip()
        configured = os.environ.get("AI_OPERATIONS_ROOM_OLLAMA_MODEL", "").strip()
        model = requested or configured or installed[0]
        if model not in installed:
            raise RuntimeError(
                f"Modelo Ollama não está instalado: {model}. "
                f"Disponíveis: {', '.join(installed)}"
            )

        local_run_id = f"ollama:{task['id']}"
        emit(
            "provider.session",
            source_event="ollama.local_run.started",
            data={"provider_session_id": local_run_id, "model": model},
        )
        emit(
            "provider.lifecycle",
            source_event="ollama.chat.started",
            data={"model": model},
        )

        payload = {
            "model": model,
            "messages": [
                {
                    "role": "system",
                    "content": AGENT_INSTRUCTIONS.get(
                        task.get("agent"),
                        AGENT_INSTRUCTIONS["general"],
                    ),
                },
                {"role": "user", "content": task["prompt"]},
            ],
            "stream": True,
            "think": False,
        }
        encoded = json.dumps(payload).encode("utf-8")
        req = request.Request(
            f"{_base_url()}/api/chat",
            data=encoded,
            headers={"Content-Type": "application/json"},
            method="POST",
        )

        output_parts: list[str] = []
        think_guard = _QwenThinkGuard() if model.lower().startswith("qwen3") else None

        def record_output(content: str) -> None:
            if not content:
                return
            output_parts.append(content)
            emit(
                "output.delta",
                source_event="ollama.chat.delta",
                message=content,
            )

        try:
            with request.urlopen(req, timeout=300) as response:
                items: queue.Queue[tuple[str, object | None]] = queue.Queue()
                reader = threading.Thread(
                    target=self._pump_response,
                    args=(response, items),
                    daemon=True,
                    name=f"ai-room-ollama-stream-{task['id'][:8]}",
                )
                reader.start()

                while True:
                    if is_cancelled():
                        response.close()
                        raise TaskCancelled("Execução local do Ollama cancelada.")

                    try:
                        kind, value = items.get(timeout=0.1)
                    except queue.Empty:
                        continue

                    if kind == "done":
                        break
                    if kind == "error":
                        if is_cancelled():
                            raise TaskCancelled("Execução local do Ollama cancelada.")
                        raise RuntimeError(f"Falha ao ler stream do Ollama: {value}")
                    if kind != "line" or not isinstance(value, (bytes, bytearray)):
                        continue

                    line = bytes(value).decode("utf-8", errors="replace").strip()
                    if not line:
                        continue
                    event_payload = json.loads(line)
                    if event_payload.get("error"):
                        raise RuntimeError(str(event_payload["error"]))

                    message = event_payload.get("message")
                    if isinstance(message, dict):
                        content = message.get("content")
                        if isinstance(content, str) and content:
                            safe_content = think_guard.feed(content) if think_guard else content
                            record_output(safe_content)

                    if event_payload.get("done"):
                        emit(
                            "provider.lifecycle",
                            source_event="ollama.chat.completed",
                            data={
                                "model": event_payload.get("model") or model,
                                "done_reason": event_payload.get("done_reason"),
                            },
                        )
        except error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"Ollama HTTP {exc.code}: {detail or exc.reason}") from exc
        except error.URLError as exc:
            raise RuntimeError(f"Falha ao conectar ao Ollama: {exc.reason}") from exc

        if think_guard is not None:
            record_output(think_guard.finish())

        output = "".join(output_parts).strip()
        if not output:
            output = "Ollama concluiu a execução sem conteúdo textual."
        return ProviderResult(output=output, provider_session_id=local_run_id)
