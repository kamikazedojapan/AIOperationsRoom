"""Local Codex CLI TaskProvider for Agent Console bounded tasks."""

from __future__ import annotations

import json
import os
import queue
import shutil
import subprocess
import tempfile
import threading
from pathlib import Path

from backend.db import connect
from backend import projects
from backend.task_runner import ProviderResult, TaskCancelled


class CodexTaskProvider:
    """Run one bounded Agent Console task through `codex exec --json`.

    Lifecycle hooks remain responsible for global Codex observability. This provider
    only drives a task explicitly submitted from Agent Console and mirrors structured
    Codex JSONL events into that task's local timeline.
    """

    source = "codex"

    def __init__(self) -> None:
        self._automation_args_cache: tuple[str, ...] | None = None

    def _executable(self) -> str | None:
        return shutil.which("codex")

    def available(self) -> bool:
        return self._executable() is not None

    def unavailable_reason(self) -> str | None:
        if self._executable() is None:
            return "Codex CLI não foi encontrado no PATH."
        return None

    def _automation_args(self, executable: str) -> list[str]:
        """Choose the safest unattended workspace-write mode supported by this CLI.

        Codex 0.163 replaced the former `--full-auto` exec flag with
        `--approve-for-me`. Older versions may still expose `--full-auto`, so the
        provider probes `codex exec --help` once and keeps a compatibility fallback.
        """
        if self._automation_args_cache is not None:
            return list(self._automation_args_cache)

        help_text = ""
        try:
            result = subprocess.run(
                [executable, "exec", "--help"],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=5,
                check=False,
            )
            help_text = f"{result.stdout}\n{result.stderr}"
        except (OSError, subprocess.TimeoutExpired):
            pass

        if "--approve-for-me" in help_text:
            args = ("--approve-for-me",)
        elif "--full-auto" in help_text:
            args = ("--full-auto",)
        elif "--sandbox" in help_text:
            args = ("--sandbox", "workspace-write")
        else:
            args = ()

        self._automation_args_cache = args
        return list(args)

    def _cwd(self, task: dict) -> str | None:
        project_id = task.get("project_id")
        if project_id is None:
            return None
        with connect() as con:
            project = projects.get(con, int(project_id))
        if project is None:
            raise RuntimeError("Projeto selecionado não foi encontrado.")
        path = Path(project["caminho_local"]).expanduser()
        if not path.exists() or not path.is_dir():
            raise RuntimeError(f"Pasta do projeto não existe: {path}")
        return str(path)

    @staticmethod
    def _thread_id(payload: dict) -> str | None:
        direct = payload.get("thread_id")
        if isinstance(direct, str) and direct:
            return direct
        thread = payload.get("thread")
        if isinstance(thread, dict):
            value = thread.get("id")
            if isinstance(value, str) and value:
                return value
        return None

    @staticmethod
    def _pump_stdout(stream, lines: queue.Queue[str | None]) -> None:
        """Read Codex stdout off the runner thread so cancellation never blocks on I/O."""
        try:
            for raw_line in stream:
                lines.put(raw_line)
        finally:
            lines.put(None)

    @staticmethod
    def _stop_process(process: subprocess.Popen, *, windows: bool | None = None) -> None:
        """Stop the Codex process promptly, including its child tree on Windows."""
        if process.poll() is not None:
            return

        use_windows = os.name == "nt" if windows is None else windows
        if use_windows:
            try:
                subprocess.run(
                    ["taskkill", "/PID", str(process.pid), "/T", "/F"],
                    capture_output=True,
                    text=True,
                    timeout=5,
                    check=False,
                )
                try:
                    process.wait(timeout=1)
                except subprocess.TimeoutExpired:
                    process.kill()
                return
            except (OSError, subprocess.TimeoutExpired):
                pass

        process.terminate()
        try:
            process.wait(timeout=3)
        except subprocess.TimeoutExpired:
            process.kill()

    def run(self, task: dict, emit, is_cancelled) -> ProviderResult:
        executable = self._executable()
        if executable is None:
            raise RuntimeError("Codex CLI não foi encontrado no PATH.")

        fd, output_name = tempfile.mkstemp(prefix="ai-room-codex-", suffix=".txt")
        os.close(fd)
        output_path = Path(output_name)
        provider_session_id: str | None = None

        args = [
            executable,
            "exec",
            "--json",
            *self._automation_args(executable),
            "--output-last-message",
            str(output_path),
            "-",
        ]

        process = subprocess.Popen(
            args,
            cwd=self._cwd(task),
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            bufsize=1,
        )

        try:
            assert process.stdin is not None
            process.stdin.write(task["prompt"])
            process.stdin.close()

            assert process.stdout is not None
            lines: queue.Queue[str | None] = queue.Queue()
            reader = threading.Thread(
                target=self._pump_stdout,
                args=(process.stdout, lines),
                daemon=True,
                name=f"ai-room-codex-stdout-{task['id'][:8]}",
            )
            reader.start()

            while True:
                if is_cancelled():
                    self._stop_process(process)
                    raise TaskCancelled("Execução do Codex cancelada.")

                try:
                    raw_line = lines.get(timeout=0.1)
                except queue.Empty:
                    continue

                if raw_line is None:
                    break

                line = raw_line.strip()
                if not line:
                    continue
                try:
                    payload = json.loads(line)
                except json.JSONDecodeError:
                    continue

                source_event = payload.get("type")
                if not isinstance(source_event, str):
                    continue

                thread_id = self._thread_id(payload)
                if thread_id and thread_id != provider_session_id:
                    provider_session_id = thread_id
                    emit(
                        "provider.session",
                        source_event=source_event,
                        data={"provider_session_id": thread_id},
                    )

                item = payload.get("item")
                data: dict = {}
                if isinstance(item, dict):
                    if isinstance(item.get("type"), str):
                        data["item_type"] = item["type"]
                    if isinstance(item.get("id"), str):
                        data["item_id"] = item["id"]

                emit(
                    "provider.lifecycle",
                    source_event=source_event,
                    data=data,
                )

            while process.poll() is None:
                if is_cancelled():
                    self._stop_process(process)
                    raise TaskCancelled("Execução do Codex cancelada.")
                try:
                    process.wait(timeout=0.1)
                except subprocess.TimeoutExpired:
                    continue

            return_code = process.returncode
            stderr = process.stderr.read().strip() if process.stderr is not None else ""
            if return_code != 0:
                detail = stderr[-4000:] if stderr else f"Codex encerrou com código {return_code}."
                raise RuntimeError(detail)

            try:
                output = output_path.read_text(encoding="utf-8").strip()
            except OSError:
                output = ""
            if not output:
                output = "Codex concluiu a execução sem mensagem final."

            return ProviderResult(
                output=output,
                provider_session_id=provider_session_id,
            )
        finally:
            if process.poll() is None:
                self._stop_process(process)
            try:
                output_path.unlink(missing_ok=True)
            except OSError:
                pass
