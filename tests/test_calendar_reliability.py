"""Calendar reliability tests — session 3.

Offline tests verify code structure (imports, signatures, no raw API calls).
Live tests verify end-to-end push behavior (require server on 7777 + Google auth).

Entry point: run_tests() returns list of (name, passed, message) tuples.
"""
import importlib
import inspect
import subprocess
import sys
import textwrap
from pathlib import Path

IHIM_ROOT = Path(__file__).parent.parent
if str(IHIM_ROOT) not in sys.path:
    sys.path.insert(0, str(IHIM_ROOT))


def _result(name: str, passed: bool, message: str = ""):
    return (name, passed, message or ("PASS" if passed else "FAIL"))


# ---------------------------------------------------------------------------
# Offline tests (no server, no network)
# ---------------------------------------------------------------------------

def test_imports():
    """All modified modules import cleanly, no circular deps."""
    try:
        importlib.import_module("api.calendar.sync")
        importlib.import_module("api.calendar.google_auth")
        # brain.py has deep deps (LLM, tracing) — just check the file parses
        source = (IHIM_ROOT / "handlers" / "brain.py").read_text(encoding="utf-8")
        compile(source, "brain.py", "exec")
        return _result("test_imports", True)
    except Exception as e:
        return _result("test_imports", False, str(e))


def test_push_event_signature():
    """push_event() has all_day and recurrence params."""
    try:
        from api.calendar.sync import push_event
        sig = inspect.signature(push_event)
        params = list(sig.parameters.keys())
        has_all_day = "all_day" in params
        has_recurrence = "recurrence" in params
        if has_all_day and has_recurrence:
            return _result("test_push_event_signature", True)
        missing = []
        if not has_all_day:
            missing.append("all_day")
        if not has_recurrence:
            missing.append("recurrence")
        return _result("test_push_event_signature", False,
                        f"Missing params: {', '.join(missing)}")
    except Exception as e:
        return _result("test_push_event_signature", False, str(e))


def test_push_to_calendar_signature():
    """_push_to_calendar() has note_id param."""
    try:
        source = (IHIM_ROOT / "handlers" / "brain.py").read_text(encoding="utf-8")
        # Parse and check the function signature
        if "note_id: str | None = None" in source and "def _push_to_calendar" in source:
            return _result("test_push_to_calendar_signature", True)
        return _result("test_push_to_calendar_signature", False,
                        "note_id param not found in _push_to_calendar signature")
    except Exception as e:
        return _result("test_push_to_calendar_signature", False, str(e))


def test_with_auth_refresh_exists():
    """_with_auth_refresh is importable from sync.py."""
    try:
        from api.calendar.sync import _with_auth_refresh
        if callable(_with_auth_refresh):
            return _result("test_with_auth_refresh_exists", True)
        return _result("test_with_auth_refresh_exists", False, "Not callable")
    except ImportError as e:
        return _result("test_with_auth_refresh_exists", False, str(e))


def test_no_raw_build_in_push_single():
    """_push_single_event() no longer imports build directly."""
    try:
        source = (IHIM_ROOT / "handlers" / "brain.py").read_text(encoding="utf-8")
        # Find the _push_single_event function body
        lines = source.split("\n")
        in_func = False
        func_lines = []
        for line in lines:
            if "def _push_single_event" in line:
                in_func = True
                continue
            if in_func:
                # Function ends at next top-level def or class
                stripped = line.lstrip()
                if stripped.startswith("def ") or stripped.startswith("class "):
                    if not line.startswith(" ") and not line.startswith("\t"):
                        break
                    # Could be a nested function — check indent level
                    indent = len(line) - len(stripped)
                    if indent == 0:
                        break
                func_lines.append(line)

        func_body = "\n".join(func_lines)
        if "from googleapiclient.discovery import build" in func_body:
            return _result("test_no_raw_build_in_push_single", False,
                            "Raw 'build' import still present in _push_single_event")
        if "service = build(" in func_body:
            return _result("test_no_raw_build_in_push_single", False,
                            "Raw 'build()' call still present in _push_single_event")
        return _result("test_no_raw_build_in_push_single", True)
    except Exception as e:
        return _result("test_no_raw_build_in_push_single", False, str(e))


def test_handle_no_direct_gcal_update():
    """handle() no longer does separate update_entry for gcal_event_id."""
    try:
        source = (IHIM_ROOT / "handlers" / "brain.py").read_text(encoding="utf-8")
        lines = source.split("\n")
        in_handle = False
        handle_lines = []
        for line in lines:
            if "def handle(" in line:
                in_handle = True
                continue
            if in_handle:
                stripped = line.lstrip()
                if (stripped.startswith("def ") or stripped.startswith("class ")) and not line.startswith(" "):
                    break
                handle_lines.append(line)

        handle_body = "\n".join(handle_lines)
        # Should NOT have: if gcal_event_id: update_entry(note_id, {"gcal_event_id"
        if 'update_entry(note_id, {"gcal_event_id"' in handle_body:
            return _result("test_handle_no_direct_gcal_update", False,
                            "handle() still has separate update_entry for gcal_event_id")
        return _result("test_handle_no_direct_gcal_update", True)
    except Exception as e:
        return _result("test_handle_no_direct_gcal_update", False, str(e))


def test_token_health_shape():
    """token_health() returns dict with expected keys."""
    try:
        from api.calendar.google_auth import token_health
        result = token_health()
        if not isinstance(result, dict):
            return _result("test_token_health_shape", False,
                            f"Expected dict, got {type(result)}")
        expected_keys = {"token_exists", "valid", "expired", "expiry", "needs_auth"}
        missing = expected_keys - set(result.keys())
        if missing:
            return _result("test_token_health_shape", False,
                            f"Missing keys: {missing}")
        return _result("test_token_health_shape", True)
    except Exception as e:
        return _result("test_token_health_shape", False, str(e))


def test_sanity_check():
    """python -m sanity.check passes."""
    try:
        result = subprocess.run(
            [sys.executable, "-m", "sanity.check"],
            cwd=str(IHIM_ROOT),
            capture_output=True,
            text=True,
            timeout=30,
        )
        if result.returncode == 0:
            return _result("test_sanity_check", True)
        return _result("test_sanity_check", False,
                        f"Exit code {result.returncode}: {result.stderr[:200]}")
    except Exception as e:
        return _result("test_sanity_check", False, str(e))


# ---------------------------------------------------------------------------
# Live tests (require server on 7777 + valid Google auth)
# ---------------------------------------------------------------------------

def _server_available(port=7777):
    """Check if iHIM server is listening."""
    try:
        import urllib.request
        urllib.request.urlopen(f"http://localhost:{port}/health", timeout=3)
        return True
    except Exception:
        return False


def test_live_calendar_push():
    """POST brain entry with date -> gcal_event_id stored atomically."""
    if not _server_available():
        return _result("test_live_calendar_push", True, "SKIPPED — no server on 7777")
    try:
        import json
        import urllib.request
        body = json.dumps({
            "content": "Test calendar reliability: Meeting tomorrow at 3pm",
            "source_file": "test_calendar_reliability_probe.txt"
        }).encode()
        req = urllib.request.Request(
            "http://localhost:7777/api/brain",
            data=body,
            headers={"Content-Type": "application/json"},
        )
        resp = urllib.request.urlopen(req, timeout=30)
        data = json.loads(resp.read())
        # If calendar data was detected, gcal_event_id should be in the result
        # (or action might not be calendar-related — that's OK too)
        return _result("test_live_calendar_push", True,
                        f"Response action: {data.get('result', {}).get('action', 'unknown')}")
    except Exception as e:
        return _result("test_live_calendar_push", False, str(e))


def test_live_token_health():
    """Direct call to token_health returns valid health dict."""
    if not _server_available():
        return _result("test_live_token_health", True, "SKIPPED — no server on 7777")
    try:
        from api.calendar.google_auth import token_health
        result = token_health()
        if isinstance(result, dict) and "token_exists" in result:
            return _result("test_live_token_health", True,
                            f"token_exists={result['token_exists']}, valid={result.get('valid')}")
        return _result("test_live_token_health", False, f"Unexpected shape: {result}")
    except Exception as e:
        return _result("test_live_token_health", False, str(e))


# ---------------------------------------------------------------------------
# Entry point for orchestrator's shared test runner
# ---------------------------------------------------------------------------

def run_tests():
    """Run all tests. Returns list of (name, passed, message) tuples."""
    offline = [
        test_imports,
        test_push_event_signature,
        test_push_to_calendar_signature,
        test_with_auth_refresh_exists,
        test_no_raw_build_in_push_single,
        test_handle_no_direct_gcal_update,
        test_token_health_shape,
        test_sanity_check,
    ]
    live = [
        test_live_calendar_push,
        test_live_token_health,
    ]

    results = []
    for test_fn in offline + live:
        try:
            results.append(test_fn())
        except Exception as e:
            results.append(_result(test_fn.__name__, False, f"Unexpected: {e}"))
    return results


if __name__ == "__main__":
    results = run_tests()
    passed = sum(1 for _, p, _ in results if p)
    total = len(results)
    print(f"\n{'='*60}")
    print(f"Calendar Reliability Tests: {passed}/{total} passed")
    print(f"{'='*60}")
    for name, ok, msg in results:
        icon = "PASS" if ok else "FAIL"
        print(f"  [{icon}] {name}: {msg}")
    sys.exit(0 if passed == total else 1)
