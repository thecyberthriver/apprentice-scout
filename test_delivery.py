#!/usr/bin/env python3
"""
test_delivery.py — `python test_delivery.py`. No network, no Telegram, no scrape.

Covers the parts where a silent failure would be invisible: a refused delivery
must never look like a send, the seen-cache must only advance on a real send,
polling errors must be explicit, and nothing logged may contain a token.
"""

from __future__ import annotations

import sys
import types

import apprentice_scout as A

# Tests monkeypatch module-level functions; without this the patches leak into
# the next test and quietly make it pass (or fail) for the wrong reason.
_ORIGINALS = {n: getattr(A, n) for n in
              ("send_message", "save_seen", "_gather", "gather_ats", "draft_script",
               "_load_offset", "log", "_reply", "_handle_command")}
_PATHS = {n: getattr(A, n) for n in ("SEEN_FILE", "POLL_OFFSET_FILE")}
_REQ = {n: getattr(A.requests, n) for n in ("post", "get")}


# --- fakes -----------------------------------------------------------------
class FakeResp:
    def __init__(self, status=200, payload=None, text=""):
        self.status_code = status
        self._payload = payload if payload is not None else {"ok": status == 200}
        self.text = text

    def json(self):
        if self._payload is _BAD_JSON:
            raise ValueError("not json")
        return self._payload


_BAD_JSON = object()


def install_post(responses):
    """Queue of FakeResp / exceptions returned by successive requests.post calls."""
    calls = []

    def fake_post(url, json=None, timeout=None, **kw):
        calls.append({"url": url, "json": json})
        item = responses[min(len(calls) - 1, len(responses) - 1)]
        if isinstance(item, Exception):
            raise item
        return item

    A.requests.post = fake_post
    return calls


def capture_log():
    lines = []
    A.log = lambda m: lines.append(str(m))
    return lines


def setup():
    for name, fn in _ORIGINALS.items():
        setattr(A, name, fn)
    for name, fn in _REQ.items():
        setattr(A.requests, name, fn)
    for name, path in _PATHS.items():
        setattr(A, name, path)
    A.TELEGRAM_BOT_TOKEN = "123456:AAFtoken_that_must_never_be_logged"
    A.TELEGRAM_CHAT_ID = "999"
    A.SOURCE_FAILURES.clear()
    A.SOURCE_OK.clear()
    A.time.sleep = lambda *_: None      # no real backoff waits in tests
    return capture_log()


# --- delivery failure handling ---------------------------------------------
def test_403_is_a_failure_and_not_retried():
    lines = setup()
    calls = install_post([FakeResp(403, {"ok": False, "description": "Forbidden: bot was blocked by the user"})])
    assert A.send_message("hello") is False, "403 must report failure, not success"
    assert len(calls) == 1, f"permanent failure must not retry (tried {len(calls)}x)"
    assert any("403" in l and "permanent" in l for l in lines), lines


def test_429_retries_then_gives_up_bounded():
    lines = setup()
    calls = install_post([FakeResp(429, {"description": "Too Many Requests: retry after 1"})])
    assert A.send_message("hello") is False
    assert len(calls) == A._SEND_ATTEMPTS, f"expected {A._SEND_ATTEMPTS} bounded attempts, got {len(calls)}"
    assert any("gave up" in l for l in lines), lines


def test_transient_then_success():
    setup()
    calls = install_post([FakeResp(500, {"description": "Bad Gateway"}), FakeResp(200)])
    assert A.send_message("hello") is True
    assert len(calls) == 2


def test_network_exception_is_failure():
    lines = setup()
    install_post([A.requests.RequestException("connection reset")] if hasattr(A.requests, "RequestException")
                 else [OSError("connection reset")])
    assert A.send_message("hello") is False
    assert any("HTTP 0" in l for l in lines), lines


def test_partial_delivery_reports_failure():
    lines = setup()
    long_text = "\n".join(["x" * 300] * 40)      # forces >1 chunk
    parts = A._chunk_lines(long_text.split("\n"))
    assert len(parts) > 1, "fixture must span multiple messages"
    install_post([FakeResp(200), FakeResp(403, {"description": "Forbidden"})])
    assert A.send_message(long_text) is False
    assert any("delivery incomplete" in l for l in lines), lines


def test_placeholder_token_refuses_to_send():
    setup()
    A.TELEGRAM_BOT_TOKEN = "CHANGE-ME:paste-token-from-BotFather"
    install_post([FakeResp(200)])
    assert A.send_message("hello") is False


# --- nothing logged may contain a token ------------------------------------
def test_errors_are_redacted():
    lines = setup()
    token = A.TELEGRAM_BOT_TOKEN
    install_post([FakeResp(403, _BAD_JSON,
                           text=f"403 Client Error for url: https://api.telegram.org/bot{token}/sendMessage")])
    A.send_message("hello")
    blob = " ".join(lines)
    assert token not in blob, "TOKEN LEAKED INTO LOGS"
    assert "<redacted>" in blob, blob
    assert A.redact(f"https://api.telegram.org/bot{token}/getUpdates").endswith("/getUpdates")
    assert A.redact("boom 987654:OTHERTOKENSHAPE/x") == "boom 987654:OTHERTOKENSHAPE/x"  # only ours


# --- seen-cache only advances on a real send -------------------------------
def test_seen_cache_untouched_when_delivery_fails(tmpdir="."):
    setup()
    saved = []
    A.save_seen = lambda s: saved.append(s)
    A.send_message = lambda _t: False
    A._gather = lambda: ([{"title": "SOC Analyst I", "company": "Acme", "url": "u",
                           "location": "NY", "posted": "", "salary": "", "tag": "t",
                           "trans_tag": "t", "site": "greenhouse"}], [], {"role_keys": {}})
    A.gather_ats = lambda _k: []
    A.draft_script = lambda *_a, **_k: None
    assert A.main() == 1, "a failed send must exit non-zero"
    assert not saved, "seen cache must NOT be written when the digest never arrived"


def test_seen_cache_written_on_success():
    setup()
    saved = []
    A.save_seen = lambda s: saved.append(s)
    A.send_message = lambda _t: True
    A._gather = lambda: ([{"title": "SOC Analyst I", "company": "Acme", "url": "u",
                           "location": "NY", "posted": "", "salary": "", "tag": "t",
                           "trans_tag": "t", "site": "greenhouse"}], [], {"role_keys": {}})
    A.gather_ats = lambda _k: []
    A.draft_script = lambda *_a, **_k: None
    assert A.main() == 0
    assert saved and saved[0]["role_keys"], "a delivered digest must be remembered"


# --- scrape failure is not "no jobs" ---------------------------------------
def test_total_scrape_failure_is_reported_as_failure():
    setup()
    A.SOURCE_FAILURES.extend(["cyber-d7: ReadTimeout", "ats: ConnectionError"])
    assert A.sources_all_failed() is True
    msg = A.build_empty_message()
    assert "every source failed" in msg.lower(), msg
    sent = []
    A.send_message = lambda t: sent.append(t) or True
    A._gather = lambda: ([], [], {"role_keys": {}})
    A.gather_ats = lambda _k: []
    assert A.main() == 1, "an all-sources-failed run must go red in Actions"
    assert "every source failed" in sent[0].lower()


def test_genuine_empty_week_is_still_success():
    setup()
    A.SOURCE_OK.append("cyber-d7")
    assert A.sources_all_failed() is False
    msg = A.build_empty_message()
    assert "every source failed" not in msg.lower()
    A.send_message = lambda _t: True
    A._gather = lambda: ([], [], {"role_keys": {}})
    A.gather_ats = lambda _k: []
    assert A.main() == 0


def test_partial_scrape_failure_is_flagged():
    setup()
    A.SOURCE_OK.append("cyber-d7")
    A.SOURCE_FAILURES.append("ats: ReadTimeout")
    assert "Partial run" in A.build_empty_message()


def test_failed_empty_message_still_exits_nonzero():
    setup()
    A.SOURCE_OK.append("cyber-d7")
    A.send_message = lambda _t: False
    A._gather = lambda: ([], [], {"role_keys": {}})
    A.gather_ats = lambda _k: []
    assert A.main() == 1, "even the 'nothing today' note must be delivered or fail loudly"


# --- polling errors --------------------------------------------------------
def test_serve_once_409_names_the_webhook_conflict():
    lines = setup()
    A.requests.get = lambda *a, **k: FakeResp(
        409, {"description": "Conflict: can't use getUpdates method while webhook is active"})
    A._load_offset = lambda: 0
    assert A.serve_once() == 1
    blob = " ".join(lines)
    assert "409" in blob and "webhook" in blob.lower(), blob
    assert A.TELEGRAM_BOT_TOKEN not in blob


def test_serve_once_other_http_error_is_explicit():
    lines = setup()
    A.requests.get = lambda *a, **k: FakeResp(401, {"description": "Unauthorized"})
    A._load_offset = lambda: 0
    assert A.serve_once() == 1
    assert any("HTTP 401" in l and "Unauthorized" in l for l in lines), lines


def test_serve_once_network_error_is_explicit():
    lines = setup()

    def boom(*a, **k):
        raise OSError("dns failure")

    A.requests.get = boom
    A._load_offset = lambda: 0
    assert A.serve_once() == 1
    assert any("getUpdates failed" in l for l in lines), lines


def test_reply_returns_false_on_refusal():
    lines = setup()
    install_post([FakeResp(403, {"description": "Forbidden: bot was blocked by the user"})])
    assert A._reply("999", "hi") is False
    assert any("reply failed (HTTP 403)" in l for l in lines), lines


# --- state that must survive between runs ----------------------------------
# Actions runners are wiped between runs: anything that must outlive a run is
# either committed back to the repo (seen.json, roles_index.json) or kept in
# actions/cache (poll_offset.json). These tests pin the round-trip both use.
def test_seen_cache_round_trips_through_a_file():
    setup()
    import tempfile, json as _json, pathlib as _pl
    with tempfile.TemporaryDirectory() as d:
        A.SEEN_FILE = _pl.Path(d) / "seen.json"
        A.save_seen({"role_keys": {"k1": A.date.today().isoformat()},
                     "hook_recent": ["h"], "tip_recent": []})
        assert A.SEEN_FILE.exists(), "state must be written somewhere durable"
        back = A.load_seen()                      # simulates the next run
        assert "k1" in back["role_keys"], back
        assert back["hook_recent"] == ["h"]
        raw = _json.loads(A.SEEN_FILE.read_text(encoding="utf-8"))
        assert A.TELEGRAM_BOT_TOKEN not in _json.dumps(raw), "no secret may be persisted"


def test_seen_cache_expires_old_keys_but_keeps_fresh_ones():
    setup()
    import tempfile, pathlib as _pl
    old = (A.date.today() - A.timedelta(days=A.SEEN_TTL_DAYS + 5)).isoformat()
    new = A.date.today().isoformat()
    with tempfile.TemporaryDirectory() as d:
        A.SEEN_FILE = _pl.Path(d) / "seen.json"
        A.save_seen({"role_keys": {"stale": old, "fresh": new}})
        back = A.load_seen()["role_keys"]
        assert "fresh" in back and "stale" not in back, back


def test_missing_state_file_is_a_cold_start_not_a_crash():
    setup()
    import tempfile, pathlib as _pl
    with tempfile.TemporaryDirectory() as d:
        A.SEEN_FILE = _pl.Path(d) / "does-not-exist.json"
        seen = A.load_seen()          # a fresh runner with no cache restored
        assert seen["role_keys"] == {}
        A.POLL_OFFSET_FILE = _pl.Path(d) / "no-offset.json"
        assert A._load_offset() == 0


def test_poll_offset_round_trips():
    setup()
    import tempfile, pathlib as _pl
    with tempfile.TemporaryDirectory() as d:
        A.POLL_OFFSET_FILE = _pl.Path(d) / "poll_offset.json"
        A._save_offset(4242)
        assert A._load_offset() == 4242, "offset must survive into the next run"


def test_duplicate_updates_are_answered_once_per_batch():
    setup()
    replied = []
    A._reply = lambda chat, text: replied.append((chat, text)) or True
    A._handle_command = lambda chat, text: replied.append((chat, text))
    import tempfile, pathlib as _pl
    with tempfile.TemporaryDirectory() as d:
        A.POLL_OFFSET_FILE = _pl.Path(d) / "poll_offset.json"
        batch = {"result": [
            {"update_id": 1, "message": {"chat": {"id": 7}, "text": "/search NY"}},
            {"update_id": 2, "message": {"chat": {"id": 7}, "text": "/search NY"}},
            {"update_id": 3, "message": {"chat": {"id": 7}, "text": "/help"}},
        ]}
        A.requests.get = lambda *a, **k: FakeResp(200, batch)
        assert A.serve_once() == 0
        assert len(replied) == 2, f"the repeated /search must collapse: {replied}"
        assert A._load_offset() == 4, "offset must advance past the whole batch"


def main() -> int:
    tests = [v for k, v in sorted(globals().items())
             if k.startswith("test_") and isinstance(v, types.FunctionType)]
    failed = 0
    for t in tests:
        try:
            t()
            print(f"  ok   {t.__name__}")
        except AssertionError as e:
            failed += 1
            print(f"  FAIL {t.__name__}: {e}")
        except Exception as e:  # noqa: BLE001
            failed += 1
            print(f"  ERROR {t.__name__}: {type(e).__name__}: {e}")
    print(f"\n{len(tests) - failed}/{len(tests)} passed")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
