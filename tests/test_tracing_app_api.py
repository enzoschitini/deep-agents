"""API da interface do rastreamento (`tracing_app`): repositório + servidor, com dados gerados pelo `dev_seed` (offline)."""

from __future__ import annotations

import json
import shutil
import threading
import urllib.error
import urllib.request

import pytest

from deep_agents.tracing_app.dev_seed import generate
from deep_agents.tracing_app.repository import ApiError, TraceRepository
from deep_agents.tracing_app.server import make_server


@pytest.fixture(scope="module")
def seed(tmp_path_factory):
    out = tmp_path_factory.mktemp("seed")
    summary = generate(out, runs=10, seed=3, running=True)
    return out, summary


@pytest.fixture()
def repo(seed):
    return TraceRepository(seed[0])


def ids(repo, **params):
    return [i["run_id"] for i in repo.dispatch("/runs", {"limit": "500", **params})["items"]]


def test_meta(repo, seed):
    m = repo.dispatch("/meta")
    assert m["n_runs"] == 11 and m["n_sessions"] >= 2 and m["n_configs"] >= 2
    assert {"data_dir", "first_run_at", "last_run_at", "models", "origins", "statuses", "generated_at"} <= set(m)
    assert "running" in m["statuses"] and "cli" in m["origins"]


def test_runs_item_fields_and_pagination(repo):
    res = repo.dispatch("/runs", {"limit": "4"})
    assert res["total"] == 11 and len(res["items"]) == 4 and res["limit"] == 4 and res["offset"] == 0
    item = next(i for i in res["items"] + repo.dispatch("/runs", {"limit": "50"})["items"] if i["status"] == "completed")
    for k in ("run_id", "session_id", "turn", "origin", "status", "started_at", "duration_s", "user_message", "answer_preview", "model",
              "config_hash", "input_tokens", "output_tokens", "total_tokens", "cache_read_tokens", "cost_usd", "llm_calls", "tool_calls",
              "subagent_calls", "errors", "ttft_s", "tools", "skills_used", "path"):
        assert k in item, k
    assert not any(k.startswith("_") for k in item)
    page2 = repo.dispatch("/runs", {"limit": "4", "offset": "4"})
    assert not {i["run_id"] for i in res["items"]} & {i["run_id"] for i in page2["items"]}
    assert len(repo.dispatch("/runs", {"limit": "9999"})["items"]) == 11     # limite máximo 500, não erro


def test_runs_sort_and_order(repo):
    desc = [i["started_at"] for i in repo.dispatch("/runs", {"limit": "50"})["items"]]
    assert desc == sorted(desc, reverse=True)
    asc = [i["started_at"] for i in repo.dispatch("/runs", {"order": "asc"})["items"]]
    assert asc == sorted(asc)
    by_dur = repo.dispatch("/runs", {"sort": "duration_s"})["items"]
    durs = [i["duration_s"] for i in by_dur if i["duration_s"] is not None]
    assert durs == sorted(durs, reverse=True) and by_dur[-1]["duration_s"] is None      # o run em andamento (sem duração) vai por último
    with pytest.raises(ApiError) as e:
        repo.dispatch("/runs", {"sort": "xx"})
    assert e.value.status == 400


def test_runs_filters(repo):
    assert set(ids(repo, status="error")) and all(i["status"] == "error" for i in repo.dispatch("/runs", {"status": "error"})["items"])
    assert len(ids(repo, status="error,cancelled")) == len(ids(repo, status="error")) + len(ids(repo, status="cancelled"))
    first = repo.dispatch("/runs", {"limit": "500"})["items"][0]
    assert ids(repo, session=first["session_id"]) and all(
        i["session_id"] == first["session_id"] for i in repo.dispatch("/runs", {"session": first["session_id"]})["items"])
    assert set(ids(repo, origin="cli")) | set(ids(repo, origin="web")) == set(ids(repo))
    assert all(i["model"] == first["model"] for i in repo.dispatch("/runs", {"model": first["model"]})["items"])
    assert ids(repo, tool="internet_search") and all("internet_search" in i["tools"] for i in repo.dispatch("/runs", {"tool": "internet_search"})["items"])
    assert all((i["errors"] or 0) > 0 or i["status"] == "error" for i in repo.dispatch("/runs", {"has_errors": "1"})["items"])
    slow = repo.dispatch("/runs", {"min_duration": "10"})["items"]
    assert all(i["duration_s"] >= 10 for i in slow)
    word = first["user_message"].split()[0].lower()
    assert first["run_id"] in ids(repo, q=word) and ids(repo, q="zzz-nada-assim") == []
    assert first["run_id"] in ids(repo, q=first["run_id"][:10])
    assert ids(repo, since="1h") == [i["run_id"] for i in repo.dispatch("/runs", {"since": "1h"})["items"]]
    all_iso = ids(repo, since="2000-01-01T00:00:00Z")
    assert len(all_iso) == 11 and ids(repo, until="2000-01-01") == []
    with pytest.raises(ApiError):
        repo.dispatch("/runs", {"since": "ontem"})


def test_facets_exclude_their_own_filter(repo):
    plain = repo.dispatch("/runs", {"limit": "1"})["facets"]
    assert set(plain) == {"status", "model", "origin", "session"} and sum(plain["status"].values()) == 11
    filtered = repo.dispatch("/runs", {"status": "error", "limit": "1"})
    assert filtered["facets"]["status"] == plain["status"]                                  # a faceta ignora o próprio filtro
    assert sum(filtered["facets"]["model"].values()) == filtered["total"]                   # as demais respeitam
    assert sum(filtered["facets"]["origin"].values()) == filtered["total"]


def test_run_and_files(repo):
    rid = ids(repo, status="completed")[0]
    run = repo.dispatch(f"/runs/{rid}")
    assert run["run_id"] == rid and "totals" in run
    for name in ("llm_calls.json", "events.json", "tool_calls.json"):
        assert repo.dispatch(f"/runs/{rid}/files/{name}")["run_id"] == rid
    with pytest.raises(ApiError) as e:
        repo.dispatch(f"/runs/{rid}/files/nope.json")
    assert e.value.status == 404
    with pytest.raises(ApiError) as e:
        repo.dispatch("/runs/naoexiste")
    assert e.value.status == 404


def _run_with_subagent(repo):
    return next(i["run_id"] for i in repo.dispatch("/runs", {"limit": "500"})["items"] if (i["subagent_calls"] or 0) > 0)


def test_trace_briefs(repo):
    rid = _run_with_subagent(repo)
    t = repo.dispatch(f"/runs/{rid}/trace")
    assert t["run"]["run_id"] == rid and t["root_ids"] and t["spans"]
    assert all(isinstance(s["offset_s"], float) and isinstance(s["duration_s"], float) and "brief" in s for s in t["spans"])
    llm = next(s for s in t["spans"] if s["type"] == "llm")
    for k in ("model", "purpose", "input_tokens", "output_tokens", "cost_usd", "latency_s", "ttft_s", "finish_reason", "n_messages", "tool_names", "requested_tools"):
        assert k in llm["brief"], k
    tools = [s for s in t["spans"] if s["type"] == "tool"]
    task = next(s for s in tools if s["name"] == "task")
    assert task["brief"]["subagent_type"] in ("pesquisador", "redator") and task["brief"]["kind"] == "subagent"
    for k in ("name", "kind", "status", "duration_s", "input_preview", "output_preview", "tool_call_id"):
        assert k in task["brief"], k
    assert any("task" in s["brief"].get("requested_tools", []) for s in t["spans"] if s["type"] == "llm")
    assert all(s["brief"] == {} for s in t["spans"] if s["type"] == "chain")


def test_span_detail(repo):
    rid = _run_with_subagent(repo)
    t = repo.dispatch(f"/runs/{rid}/trace")
    task = next(s for s in t["spans"] if s["name"] == "task" and s["type"] == "tool")
    d = repo.dispatch(f"/runs/{rid}/spans/{task['span_id']}")
    assert d["span"]["span_id"] == task["span_id"] and d["tool_call"]["name"] == "task"
    assert d["delegation"]["subagent_type"] and d["delegation"]["id"] == d["tool_call"]["tool_call_id"]
    chain = d["parent_chain"]
    assert chain[0]["span_id"] == task["span_id"] and chain[-1]["parent_id"] is None
    llm = next(s for s in t["spans"] if s["type"] == "llm")
    dl = repo.dispatch(f"/runs/{rid}/spans/{llm['span_id']}")
    assert dl["llm_call"]["request"]["messages"] and isinstance(dl["llm_call"]["tool_schemas"], list) and "delegation" not in dl
    with pytest.raises(ApiError) as e:
        repo.dispatch(f"/runs/{rid}/spans/inexistente")
    assert e.value.status == 404


def test_tool_schemas_resolved_from_pool(tmp_path):
    rd = tmp_path / "runs" / "r1"
    rd.mkdir(parents=True)
    (rd / "run.json").write_text(json.dumps({"run_id": "r1", "status": "completed", "started_at": "2026-01-01T00:00:00+00:00"}))
    (rd / "spans.json").write_text(json.dumps({"root_ids": ["s1"], "spans": [
        {"span_id": "s1", "parent_id": None, "children": [], "type": "llm", "name": "X", "ref": {"llm_call_id": "s1"}}]}))
    (rd / "llm_calls.json").write_text(json.dumps({"tool_schemas": {"abc": [{"function": {"name": "t"}}]},
                                                   "calls": [{"llm_call_id": "s1", "tools_hash": "abc", "request": {"messages": []}}]}))
    d = TraceRepository(tmp_path).dispatch("/runs/r1/spans/s1")
    assert d["llm_call"]["tool_schemas"] == [{"function": {"name": "t"}}]
    t = TraceRepository(tmp_path).dispatch("/runs/r1/trace")        # span sem duração/offset: números mesmo assim
    assert t["spans"][0]["offset_s"] == 0.0 and t["spans"][0]["duration_s"] == 0.0


def test_stats_contract_and_sums(repo):
    s = repo.dispatch("/stats")
    assert set(s) >= {"range", "kpis", "prev_kpis", "series", "status_counts", "by_model", "by_tool", "by_agent", "latency_hist",
                      "tokens_hist", "slowest_runs", "recent_errors"}
    k = s["kpis"]
    for key in ("runs", "errors", "error_rate", "input_tokens", "output_tokens", "total_tokens", "cache_read_tokens", "cache_hit_rate",
                "reasoning_tokens", "cost_usd", "latency_avg_s", "latency_p50_s", "latency_p95_s", "latency_p99_s", "avg_ttft_s",
                "llm_calls", "tool_calls", "subagent_calls", "avg_tokens_per_run"):
        assert key in k, key
    assert k["runs"] == 11 and s["prev_kpis"] is None
    assert sum(p["runs"] for p in s["series"]) == k["runs"] and sum(p["errors"] for p in s["series"]) == k["errors"]
    assert sum(p["input_tokens"] for p in s["series"]) == k["input_tokens"]
    assert sum(p["llm_calls"] for p in s["series"]) == k["llm_calls"] and sum(p["tool_calls"] for p in s["series"]) == k["tool_calls"]
    assert abs(sum(p["cost_usd"] for p in s["series"]) - k["cost_usd"]) < 1e-6
    assert sum(s["status_counts"].values()) == k["runs"] and sum(m["runs"] for m in s["by_model"]) == k["runs"]
    assert 0 <= k["error_rate"] <= 1 and k["latency_p50_s"] <= k["latency_p95_s"] <= k["latency_p99_s"]
    h = s["latency_hist"]
    assert len(h["edges"]) == len(h["counts"]) + 1 and sum(h["counts"]) == sum(1 for r in repo.dispatch("/runs", {"limit": "500"})["items"] if r["duration_s"] is not None)
    assert sum(s["tokens_hist"]["counts"]) > 0
    assert len(s["slowest_runs"]) <= 8 and [r["duration_s"] for r in s["slowest_runs"]] == sorted((r["duration_s"] for r in s["slowest_runs"]), reverse=True)
    names = {t["name"] for t in s["by_tool"]}
    assert "internet_search" in names
    t0 = next(t for t in s["by_tool"] if t["name"] == "internet_search")
    for key in ("calls", "errors", "avg_s", "p95_s", "total_s"):
        assert key in t0
    assert any(a["agent"] == "main" for a in s["by_agent"])
    for e in s["recent_errors"]:
        assert {"run_id", "at", "where", "name", "type", "message"} <= set(e)
    assert s["recent_errors"], "o seed tem runs com erro"


def test_stats_buckets_prev_and_filters(repo):
    s = repo.dispatch("/stats", {"since": "30d", "bucket": "day"})
    assert s["prev_kpis"] is not None and s["range"]["bucket"] == "day" and len(s["series"]) >= 30
    assert sum(p["runs"] for p in s["series"]) == s["kpis"]["runs"]
    assert all(p["runs"] == 0 and p["input_tokens"] == 0 for p in s["series"][:5])          # buckets vazios preenchidos com zeros
    h = repo.dispatch("/stats", {"since": "24h"})
    assert h["range"]["bucket"] == "hour" and len(h["series"]) in (24, 25, 26)
    e = repo.dispatch("/stats", {"status": "error"})
    assert e["kpis"]["runs"] == e["kpis"]["errors"] == e["status_counts"]["error"]
    with pytest.raises(ApiError):
        repo.dispatch("/stats", {"bucket": "mes"})


def test_sessions(repo):
    items = repo.dispatch("/sessions")["items"]
    assert len(items) >= 2
    s = items[0]
    for k in ("session_id", "started_at", "last_run_at", "n_runs", "models", "totals", "first_message", "n_errors", "duration_s", "statuses"):
        assert k in s, k
    assert set(s["totals"]) >= {"llm_calls", "tool_calls", "input_tokens", "output_tokens", "cost_usd"}
    assert [i["last_run_at"] for i in items] == sorted((i["last_run_at"] for i in items), reverse=True)
    d = repo.dispatch(f"/sessions/{s['session_id']}")
    assert d["session"]["session_id"] == s["session_id"] and len(d["runs"]) == s["n_runs"]
    assert d["messages"][0]["role"] == "user" and {m["role"] for m in d["messages"]} <= {"user", "assistant"}
    assert all({"role", "content", "run_id", "at"} <= set(m) for m in d["messages"])
    turns = [r["turn"] for r in d["runs"]]
    assert turns == sorted(turns)
    with pytest.raises(ApiError) as e:
        repo.dispatch("/sessions/nao-existe")
    assert e.value.status == 404


def test_configs_and_diff(repo, seed):
    items = repo.dispatch("/configs")["items"]
    assert len(items) >= 2
    c = items[0]
    for k in ("hash", "model", "provider", "created_at", "system_prompt_chars", "n_rules", "n_skills", "n_subagents", "runs", "first_used_at", "last_used_at"):
        assert k in c, k
    assert c["runs"] >= 1 and c["system_prompt_chars"] > 100 and c["first_used_at"] <= c["last_used_at"]
    full = repo.dispatch(f"/configs/{c['hash']}")
    assert full["prompts"]["system_prompt"] and full["runs"] and full["runs"][0]["config_hash"] == c["hash"]
    a, b = items[0]["hash"], items[1]["hash"]
    d = repo.dispatch("/configs/diff", {"a": a, "b": b})
    assert d["a"] == a and d["b"] == b
    names = {s["name"]: s for s in d["sections"]}
    assert {"model", "system_prompt", "summary_prompt", "harness_profile", "limits"} <= set(names)
    assert names["system_prompt"]["status"] == "changed" and names["summary_prompt"]["status"] == "same"
    changed = names["system_prompt"]["lines"]
    assert {l["op"] for l in changed} <= {" ", "+", "-"} and any(l["op"] in "+-" for l in changed)
    same = repo.dispatch("/configs/diff", {"a": a, "b": a})
    assert all(s["status"] == "same" for s in same["sections"])
    with pytest.raises(ApiError) as e:
        repo.dispatch("/configs/diff", {"a": a})
    assert e.value.status == 400
    with pytest.raises(ApiError) as e:
        repo.dispatch("/configs/diff", {"a": a, "b": "ffffffffffffffff"})
    assert e.value.status == 404
    with pytest.raises(ApiError):
        repo.dispatch("/configs/..%2f..")


def test_llm_calls(repo):
    res = repo.dispatch("/llm_calls", {"limit": "5"})
    assert res["total"] > 5 and len(res["items"]) == 5
    it = res["items"][0]
    for k in ("llm_call_id", "span_id", "run_id", "started_at", "agent", "purpose", "model", "status", "input_tokens", "output_tokens",
              "cache_read_tokens", "cost_usd", "latency_s", "ttft_s", "finish_reason", "requested_tools", "preview_in", "preview_out"):
        assert k in it, k
    assert len(it["preview_in"]) <= 160 and len(it["preview_out"]) <= 160
    summ = repo.dispatch("/llm_calls", {"purpose": "summary"})
    assert summ["total"] >= 1 and all(i["purpose"] == "summary" for i in summ["items"])
    srt = repo.dispatch("/llm_calls", {"sort": "latency_s", "order": "asc", "limit": "500"})["items"]
    lat = [i["latency_s"] for i in srt]
    assert lat == sorted(lat)
    assert all(i["latency_s"] >= 2 for i in repo.dispatch("/llm_calls", {"min_latency": "2", "limit": "500"})["items"])
    one = repo.dispatch("/llm_calls", {"run": it["run_id"], "limit": "500"})
    assert one["total"] >= 1 and all(i["run_id"] == it["run_id"] for i in one["items"])
    sub = repo.dispatch("/llm_calls", {"agent": "pesquisador", "limit": "500"})
    assert sub["total"] >= 1 and all(i["agent"] == "pesquisador" for i in sub["items"])
    q = repo.dispatch("/llm_calls", {"q": "Você é um pesquisador", "limit": "500"})            # busca no conteúdo completo da requisição
    assert 1 <= q["total"] < res["total"]
    assert repo.dispatch("/llm_calls", {"q": "zzz-nada-assim"})["total"] == 0
    assert repo.dispatch("/llm_calls", {"limit": "3", "offset": "3"})["items"][0]["llm_call_id"] != res["items"][0]["llm_call_id"]


def test_tool_calls(repo):
    res = repo.dispatch("/tool_calls", {"limit": "500"})
    assert res["total"] == len(res["items"]) > 3
    it = res["items"][0]
    for k in ("tool_call_id", "span_id", "run_id", "started_at", "name", "kind", "agent", "status", "duration_s", "input_preview", "output_preview", "output_chars"):
        assert k in it, k
    only = repo.dispatch("/tool_calls", {"name": "task", "limit": "500"})["items"]
    assert only and all(i["name"] == "task" and i["kind"] == "subagent" for i in only)
    assert all(i["kind"] == "tool" for i in repo.dispatch("/tool_calls", {"kind": "tool", "limit": "500"})["items"])
    errs = repo.dispatch("/tool_calls", {"status": "error"})["items"]
    assert errs and all(i["status"] == "error" for i in errs)
    srt = [i["duration_s"] for i in repo.dispatch("/tool_calls", {"sort": "duration_s", "limit": "500"})["items"]]
    assert srt == sorted(srt, reverse=True)
    assert all(i["duration_s"] >= 2 for i in repo.dispatch("/tool_calls", {"min_duration": "2", "limit": "500"})["items"])
    assert repo.dispatch("/tool_calls", {"q": "trecho de conteúdo inexistente xyz"})["total"] == 0
    assert repo.dispatch("/tool_calls", {"q": "Segundo a análise", "limit": "500"})["total"] >= 1


def test_path_traversal_rejected(repo):
    for bad in ("/runs/..", "/runs/../trace", "/runs/.hidden", "/runs/a%2Fb", "/runs/x/files/../../index.json", "/runs/x/spans/.."):
        with pytest.raises(ApiError) as e:
            repo.dispatch(bad)
        assert e.value.status in (400, 404)
    rid = ids(repo)[0]
    for name in ("index.json", "run.json/..", "..", "a/b.json", "run.txt", "../../index.json", ".run.json"):
        with pytest.raises(ApiError) as e:
            repo.dispatch(f"/runs/{rid}/files/{name}")
        assert e.value.status in (400, 404)
    with pytest.raises(ApiError):
        repo.dispatch("/sessions/..")
    assert repo.dispatch("/llm_calls", {"run": "../x"})["total"] == 0           # `run` só compara com ids existentes


def test_tolerates_partial_and_corrupt_runs(seed, tmp_path):
    data = tmp_path / "data"
    shutil.copytree(seed[0], data)
    repo = TraceRepository(data)
    before = repo.dispatch("/runs", {"limit": "1"})["total"]
    victim = ids(repo, status="completed")[0]
    keep = ids(repo, status="completed")[1]
    vdir = data / "runs" / victim
    (vdir / "llm_calls.json").write_text("{ não é json", encoding="utf-8")        # corrompido
    (vdir / "spans.json").unlink()
    for name in ("tool_calls.json", "events.json", "errors.json", "subagents.json", "response.json", "sources.json", "conversation.json"):
        (data / "runs" / keep / name).unlink()                                    # só run.json: como um run em andamento
    partial = data / "runs" / "meio-gravado"
    partial.mkdir()
    (partial / "run.json").write_text('{"run_id": "meio-gravado", "status": "running"}', encoding="utf-8")
    (data / "runs" / "vazio").mkdir()
    (data / "runs" / "quebrado").mkdir()
    (data / "runs" / "quebrado" / "run.json").write_text("{ corrompido", encoding="utf-8")
    assert repo.dispatch("/runs", {"limit": "500"})["total"] == before + 1         # o parcial entra; vazio e corrompido (sem índice) não
    for path, params in (("/stats", {}), ("/sessions", {}), ("/configs", {}), ("/llm_calls", {"q": "x"}), ("/tool_calls", {}), ("/meta", {}),
                         (f"/runs/{victim}/trace", {}), (f"/runs/{keep}/trace", {}), ("/runs/meio-gravado/trace", {})):
        assert repo.dispatch(path, params) is not None, path
    t = repo.dispatch(f"/runs/{victim}/trace")
    assert t["spans"] == [] and t["run"]["run_id"] == victim
    assert repo.dispatch(f"/runs/{keep}/trace")["spans"]
    with pytest.raises(ApiError) as e:
        repo.dispatch(f"/runs/{victim}/files/llm_calls.json")
    assert e.value.status == 404
    with pytest.raises(ApiError) as e:
        repo.dispatch(f"/runs/{victim}/spans/qualquer")
    assert e.value.status == 404
    # run.json corrompido com linha no índice: cai para o índice
    idx = json.loads((data / "index.json").read_text(encoding="utf-8"))
    entry = idx["runs"][0]
    (data / "runs" / entry["run_id"] / "run.json").write_text("{ corrompido", encoding="utf-8")
    items = repo.dispatch("/runs", {"limit": "500"})["items"]
    assert next(i for i in items if i["run_id"] == entry["run_id"])["user_message"] == entry["user_message"]
    # pasta de dados vazia / inexistente
    empty = TraceRepository(tmp_path / "nada")
    assert empty.dispatch("/runs")["total"] == 0 and empty.dispatch("/stats")["kpis"]["runs"] == 0 and empty.dispatch("/meta")["n_runs"] == 0
    assert empty.dispatch("/sessions")["items"] == [] and empty.dispatch("/configs")["items"] == []


def test_cache_follows_file_changes(seed, tmp_path):
    data = tmp_path / "d"
    shutil.copytree(seed[0], data)
    repo = TraceRepository(data)
    rid = ids(repo, status="completed")[0]
    assert repo.dispatch(f"/runs/{rid}")["status"] == "completed"
    run = json.loads((data / "runs" / rid / "run.json").read_text(encoding="utf-8"))
    run["status"] = "error"
    run["user_message_extra"] = "x" * 50                                           # muda o tamanho: invalida o cache
    (data / "runs" / rid / "run.json").write_text(json.dumps(run), encoding="utf-8")
    assert repo.dispatch(f"/runs/{rid}")["status"] == "error"
    assert next(i for i in repo.dispatch("/runs", {"limit": "500"})["items"] if i["run_id"] == rid)["status"] == "error"


# ----------------------------------------------------------------------------------------------- servidor real
@pytest.fixture()
def server(seed):
    srv = make_server(seed[0], "127.0.0.1", 0)
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    yield f"http://127.0.0.1:{srv.server_address[1]}"
    srv.shutdown()
    srv.server_close()


def fetch(url, method="GET", headers=None):
    req = urllib.request.Request(url, method=method, headers=headers or {})
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            return r.status, dict(r.headers), r.read()
    except urllib.error.HTTPError as e:
        return e.code, dict(e.headers), e.read()


def test_server_serves_html_and_api(server):
    st, hd, body = fetch(server + "/")
    assert st == 200 and "text/html" in hd["Content-Type"] and "utf-8" in hd["Content-Type"].lower() and hd["Cache-Control"] == "no-store"
    assert b"<title>Deep Agents" in body
    st, hd, body = fetch(server + "/api/meta")
    assert st == 200 and "application/json" in hd["Content-Type"] and hd["Cache-Control"] == "no-store"
    assert json.loads(body)["n_runs"] == 11
    st, _, body = fetch(server + "/api/runs?limit=2&sort=duration_s&order=asc&status=completed")
    data = json.loads(body)
    assert st == 200 and len(data["items"]) == 2 and data["items"][0]["duration_s"] <= data["items"][1]["duration_s"]
    q = fetch(server + "/api/runs?q=" + "%C3%A1" * 1)[0]                          # acento na query
    assert q == 200
    rid = data["items"][0]["run_id"]
    assert fetch(f"{server}/api/runs/{rid}/trace")[0] == 200
    st, _, body = fetch(server + "/api/stats?since=30d")
    assert st == 200 and json.loads(body)["kpis"]["runs"] == 11


def test_server_errors_head_methods_and_security(server, seed):
    st, hd, body = fetch(server + "/api/runs/naoexiste")
    assert st == 404 and "application/json" in hd["Content-Type"] and "error" in json.loads(body)
    st, _, body = fetch(server + "/api/runs?sort=zzz")
    assert st == 400 and "error" in json.loads(body)
    assert fetch(server + "/api/nada")[0] == 404 and fetch(server + "/nada")[0] == 404
    assert fetch(server + "/api/runs/..%2f..%2findex.json")[0] in (400, 404)
    assert fetch(server + "/api/runs/%2e%2e/trace")[0] in (400, 404)
    st, hd, body = fetch(server + "/api/meta", method="HEAD")
    assert st == 200 and body == b"" and int(hd["Content-Length"]) > 10
    assert fetch(server + "/", method="HEAD")[2] == b""
    st, _, body = fetch(server + "/api/runs", method="POST")
    assert st == 405 and "error" in json.loads(body)
    assert fetch(server + "/api/meta", headers={"Origin": "http://evil.example"})[0] == 403
    assert fetch(server + "/api/meta", headers={"Host": "evil.example"})[0] == 403
    assert fetch(server + "/api/meta", headers={"Origin": server})[0] == 200


def test_server_500_hides_traceback(seed, monkeypatch, capsys):
    srv = make_server(seed[0], "127.0.0.1", 0)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        monkeypatch.setattr(srv.repository, "meta", lambda: 1 / 0)
        st, _, body = fetch(f"http://127.0.0.1:{srv.server_address[1]}/api/meta")
        assert st == 500 and "Traceback" not in body.decode() and "error" in json.loads(body)
        assert "ZeroDivisionError" in capsys.readouterr().err
    finally:
        srv.shutdown()
        srv.server_close()


def test_make_server_only_local_hosts_and_port_zero(seed):
    with pytest.raises(ValueError):
        make_server(seed[0], "0.0.0.0", 0)
    with pytest.raises(ValueError):
        make_server(seed[0], "192.168.0.10", 0)
    a = make_server(seed[0], "127.0.0.1", 0)
    b = make_server(seed[0], "localhost", 0)
    try:
        assert a.server_address[1] > 0 and a.server_address[1] != b.server_address[1]
        with pytest.raises(OSError):                                               # allow_reuse_address=False: a mesma porta falha
            make_server(seed[0], "127.0.0.1", a.server_address[1])
    finally:
        a.server_close()
        b.server_close()


def test_dev_seed_refuses_real_data_dir():
    from deep_agents.tracing.options import DEFAULT_DIR
    with pytest.raises(SystemExit):
        generate(DEFAULT_DIR, runs=1)
