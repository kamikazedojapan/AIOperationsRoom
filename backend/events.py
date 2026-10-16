"""Read the normalized event queue and persist provider-aware sessions."""

from __future__ import annotations

import hashlib
import json
import sqlite3
import threading

from backend.config import events_path
from backend.identity import session_key
from backend import runs


_lock = threading.Lock()


def ingest(con: sqlite3.Connection) -> int:
    path = events_path()

    if not path.exists():
        return 0

    with _lock:
        con.execute("BEGIN IMMEDIATE")

        row = con.execute(
            """
            SELECT valor
            FROM ingestao
            WHERE chave = 'events_offset'
            """
        ).fetchone()

        offset = int(row["valor"]) if row else 0

        previous = con.execute(
            """
            SELECT valor
            FROM ingestao
            WHERE chave = 'events_prefix'
            """
        ).fetchone()

        processed = 0

        with path.open("rb") as stream:
            size = stream.seek(0, 2)
            stream.seek(0)

            prefix = (
                hashlib.sha256(
                    stream.read(min(offset, 4096))
                ).hexdigest()
                if offset
                else ""
            )

            if (
                size < offset
                or (
                    offset
                    and previous
                    and previous["valor"] != prefix
                )
            ):
                offset = 0

            stream.seek(offset)

            while True:
                start = stream.tell()
                raw = stream.readline()

                if not raw:
                    break

                if not raw.endswith(b"\n"):
                    stream.seek(start)
                    break

                try:
                    event = json.loads(
                        raw.decode("utf-8")
                    )
                except (
                    UnicodeDecodeError,
                    json.JSONDecodeError,
                ):
                    continue

                if not isinstance(event, dict):
                    continue

                sid = event.get("session_id")
                name = event.get("evento")
                source = event.get("source")
                when = event.get("t")

                if (
                    not isinstance(sid, str)
                    or not sid
                    or not isinstance(name, str)
                    or not name
                    or not isinstance(source, str)
                    or not source
                    or not isinstance(when, str)
                    or not when
                ):
                    continue

                skey = session_key(
                    source,
                    sid,
                )

                event_id = event.get("id")

                if (
                    not isinstance(event_id, str)
                    or not event_id
                ):
                    event_id = hashlib.sha256(
                        json.dumps(
                            event,
                            sort_keys=True,
                            ensure_ascii=False,
                        ).encode("utf-8")
                    ).hexdigest()

                cursor = con.execute(
                    """
                    INSERT OR IGNORE INTO evento (
                        id,
                        session_key,
                        source,
                        session_id,
                        nome,
                        ocorrido_em,
                        dados
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        event_id,
                        skey,
                        source,
                        sid,
                        name,
                        when,
                        runs.event_data(event),
                    ),
                )

                inserted = cursor.rowcount > 0

                if inserted:
                    runs.apply(
                        con,
                        event,
                    )

                    cwd = event.get("cwd")

                    con.execute(
                        """
                        INSERT INTO sessao (
                            session_key,
                            source,
                            session_id,
                            cwd,
                            ultimo_evento,
                            ultima_atualizacao
                        )
                        VALUES (?, ?, ?, ?, ?, ?)

                        ON CONFLICT(session_key)
                        DO UPDATE SET
                            cwd = CASE
                                WHEN excluded.ultima_atualizacao
                                     >= sessao.ultima_atualizacao
                                     AND excluded.cwd <> ''
                                THEN excluded.cwd
                                ELSE sessao.cwd
                            END,

                            ultimo_evento = CASE
                                WHEN excluded.ultima_atualizacao
                                     >= sessao.ultima_atualizacao
                                THEN excluded.ultimo_evento
                                ELSE sessao.ultimo_evento
                            END,

                            ultima_atualizacao = MAX(
                                sessao.ultima_atualizacao,
                                excluded.ultima_atualizacao
                            )
                        """,
                        (
                            skey,
                            source,
                            sid,
                            (
                                cwd
                                if isinstance(cwd, str)
                                else ""
                            ),
                            name,
                            when,
                        ),
                    )

                processed += int(inserted)

            offset = stream.tell()

            stream.seek(0)

            prefix = (
                hashlib.sha256(
                    stream.read(min(offset, 4096))
                ).hexdigest()
                if offset
                else ""
            )

        con.execute(
            """
            INSERT INTO ingestao (
                chave,
                valor
            )
            VALUES (
                'events_offset',
                ?
            )

            ON CONFLICT(chave)
            DO UPDATE SET
                valor = excluded.valor
            """,
            (offset,),
        )

        con.execute(
            """
            INSERT INTO ingestao (
                chave,
                valor
            )
            VALUES (
                'events_prefix',
                ?
            )

            ON CONFLICT(chave)
            DO UPDATE SET
                valor = excluded.valor
            """,
            (prefix,),
        )

        return processed