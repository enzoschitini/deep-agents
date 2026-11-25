"""TraceStore: escrita atômica dos JSONs, index.json, sessions.json e configs/. Leitura para a futura interface."""

from __future__ import annotations

import json
import os
import threading
import time
import uuid
from pathlib import Path
from typing import Any

from deep_agents.tracing.serialize import iso

SCHEMA_VERSION = 1


class TraceStore:
    def __init__(self, base_dir: Path, *, pretty: bool = True) -> None:
        self.base_dir = Path(base_dir)
        self.pretty = pretty
        self._lock = threading.Lock()

    # -- caminhos --
    def run_dir(self, run_id: str) -> Path:
        return self.base_dir / "runs" / run_id

    @property
    def index_path(self) -> Path:
        return self.base_dir / "index.json"

    @property
    def sessions_path(self) -> Path:
        return self.base_dir / "sessions.json"

    def config_path(self, config_hash: str) -> Path:
        return self.base_dir / "configs" / f"{config_hash}.json"

    # -- escrita --
    def write_json(self, path: Path, obj: Any) -> int:
        """Escreve com arquivo temporário + `os.replace` (nunca deixa um JSON pela metade). Devolve os bytes."""
        path.parent.mkdir(parents=True, exist_ok=True)
        data = json.dumps(obj, ensure_ascii=False, indent=2 if self.pretty else None, default=str).encode("utf-8")
        tmp = path.with_name(f".{path.name}.{uuid.uuid4().hex[:8]}.tmp")
        tmp.write_bytes(data)
        os.replace(tmp, path)
        return len(data)

    def read_json(self, path: Path, default: Any = None) -> Any:
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return default

    def write_run_files(self, run_id: str, files: dict[str, Any]) -> dict[str, int]:
        sizes: dict[str, int] = {}
        for name, content in files.items():
            sizes[name] = self.write_json(self.run_dir(run_id) / name, content)
        return sizes

    def save_config(self, config_hash: str, snapshot: dict[str, Any]) -> None:
        path = self.config_path(config_hash)
        if not path.exists():
            self.write_json(path, {"schema_version": SCHEMA_VERSION, "config_hash": config_hash, **snapshot})

    # -- index / sessions --
    def upsert_index(self, entry: dict[str, Any], updated_at: str) -> None:
        with self._lock:
            index = self.read_json(self.index_path, None)
            if not isinstance(index, dict) or not isinstance(index.get("runs"), list):
                index = {"schema_version": SCHEMA_VERSION, "runs": []}
            runs = [r for r in index["runs"] if r.get("run_id") != entry["run_id"]]
            runs.append(entry)
            runs.sort(key=lambda r: r.get("started_at") or "")
            self.write_json(self.index_path, {"schema_version": SCHEMA_VERSION, "updated_at": updated_at, "runs": runs})

    def update_session(self, entry: dict[str, Any], updated_at: str) -> None:
        sid = entry.get("session_id")
        if not sid:
            return
        with self._lock:
            doc = self.read_json(self.sessions_path, None)
            if not isinstance(doc, dict) or not isinstance(doc.get("sessions"), dict):
                doc = {"schema_version": SCHEMA_VERSION, "sessions": {}}
            sessions = doc["sessions"]
            s = sessions.get(sid) or {"session_id": sid, "started_at": entry.get("started_at"), "run_ids": [], "models": [],
                                      "totals": {"llm_calls": 0, "tool_calls": 0, "input_tokens": 0, "output_tokens": 0, "cost_usd": 0.0}}
            if entry["run_id"] not in s["run_ids"]:
                s["run_ids"].append(entry["run_id"])
            s["n_runs"] = len(s["run_ids"])
            s["last_run_at"] = entry.get("started_at")
            if entry.get("model") and entry["model"] not in s["models"]:
                s["models"].append(entry["model"])
            # os totais são recalculados do índice (idempotente se o run for gravado duas vezes)
            index = self.read_json(self.index_path, {"runs": []}) or {"runs": []}
            mine = [r for r in index.get("runs", []) if r.get("session_id") == sid]
            s["totals"] = {
                "llm_calls": sum(r.get("llm_calls") or 0 for r in mine),
                "tool_calls": sum(r.get("tool_calls") or 0 for r in mine),
                "input_tokens": sum(r.get("input_tokens") or 0 for r in mine),
                "output_tokens": sum(r.get("output_tokens") or 0 for r in mine),
                "cost_usd": round(sum(r.get("cost_usd") or 0 for r in mine), 6),
            }
            sessions[sid] = s
            self.write_json(self.sessions_path, {"schema_version": SCHEMA_VERSION, "updated_at": updated_at, "sessions": sessions})

    # -- leitura --
    def list_runs(self, *, session_id: str | None = None, status: str | None = None, limit: int | None = None) -> list[dict]:
        index = self.read_json(self.index_path, None)
        if not isinstance(index, dict):
            index = self.rebuild_index()
        runs = [r for r in index.get("runs", [])
                if (session_id is None or r.get("session_id") == session_id) and (status is None or r.get("status") == status)]
        runs.sort(key=lambda r: r.get("started_at") or "", reverse=True)
        return runs[:limit] if limit else runs

    def load_run(self, run_id: str, files: list[str] | None = None) -> dict[str, Any]:
        """Todos os JSONs do run (ou só os pedidos), por nome de arquivo."""
        out: dict[str, Any] = {}
        folder = self.run_dir(run_id)
        if not folder.is_dir():
            return out
        for path in sorted(folder.glob("*.json")):
            if files is None or path.name in files:
                out[path.name] = self.read_json(path)
        return out

    def rebuild_index(self) -> dict[str, Any]:
        """Refaz index.json a partir dos `run.json` (se o índice se perdeu ou ficou defasado)."""
        runs = []
        for path in sorted((self.base_dir / "runs").glob("*/run.json")):
            run = self.read_json(path)
            if isinstance(run, dict):
                entry = run.get("index_entry")
                if isinstance(entry, dict):
                    runs.append(entry)
        runs.sort(key=lambda r: r.get("started_at") or "")
        index = {"schema_version": SCHEMA_VERSION, "updated_at": iso(time.time()), "runs": runs}
        with self._lock:
            self.write_json(self.index_path, index)
        return index
