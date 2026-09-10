"""Replay-fixture loading: turn captured Phase 1 files into a replayable map.

A *replay fixture* is what makes the diagnostics lane testable and demoable
without a car: a mapping of OBD command -> captured response, in the same shape
the Phase 1 probes wrote to ``fixtures/``. The shapes in that directory are:

``<name>.json``   capture map - ``{"0100": {"desc": ..., "answered": true,
                  "raw": ["41 00 BE 3E A8 13"]}}``. This is the format
                  ``fixtures/round1_full_capture.json`` uses and the only one
                  that can be replayed as a full scan.
``<name>.jsonl``  one probe record per line. Records that name their command
                  (``command``/``cmd``) are replayable; the positional probe
                  logs (``readiness_m0101_m0141.jsonl``,
                  ``m02_freezeframe_probe.jsonl``) are not - a bare
                  ``{req, data}`` line carries no command, so replaying it
                  would mean guessing. Those raise :class:`FixtureError` with
                  the reason instead of silently replaying nonsense.

Nothing here is vehicle-specific: a fixture is a recording, and the engine that
consumes it still discovers everything it reports.
"""

from __future__ import annotations

import json
import os
from typing import Dict, List, Optional

#: Preferred file when the caller hands us the fixtures directory. The full
#: capture is the only fixture that covers a whole scan, so it wins.
PREFERRED_CAPTURE = "round1_full_capture.json"

#: Capture-map keys that are metadata rather than commands.
_META_KEYS = ("probe_meta", "_meta", "meta", "notes")

#: Record keys that may name the command in a JSONL probe log.
_COMMAND_KEYS = ("command", "cmd", "pid")

_HEX_DIGITS = set("0123456789ABCDEFabcdef")


class FixtureError(ValueError):
    """Raised when a fixture path cannot be replayed (with the reason why)."""


def is_capture_map(obj) -> bool:
    """Does ``obj`` look like a command -> response capture map?"""
    if not isinstance(obj, dict) or not obj:
        return False
    saw_command = False
    for key, value in obj.items():
        name = str(key).strip()
        if name in _META_KEYS:
            continue
        if not name or any(char not in _HEX_DIGITS for char in name):
            return False
        if not isinstance(value, (dict, list, str, type(None))):
            return False
        saw_command = True
    return saw_command


def normalize_entry(value) -> dict:
    """Coerce one capture entry into ``{"raw": [...], ...}``.

    A recorded non-answer (``raw: null``, or ``answered: false``) becomes an
    empty string, which is exactly how Hudiy reports ``NO DATA``. That matters:
    an unanswered command is a *negative fixture*, a fact about the car, not an
    excuse to invent a response.
    """
    if isinstance(value, dict):
        entry = dict(value)
    elif isinstance(value, list):
        entry = {"raw": value}
    elif isinstance(value, str):
        entry = {"raw": [value]}
    elif value is None:
        entry = {"raw": []}
    else:
        raise FixtureError("unsupported capture entry type: %r" % type(value).__name__)

    raw = entry.get("raw")
    if raw is None:
        raw = []
    elif isinstance(raw, str):
        raw = [raw]
    elif not isinstance(raw, list):
        raise FixtureError("capture entry 'raw' must be a list or string")
    raw = [frame for frame in raw if frame is not None]
    entry["raw"] = raw if raw else [""]
    return entry


def normalize_capture(obj, source: str = "") -> Dict[str, dict]:
    """Validate and normalise a whole capture map."""
    if not is_capture_map(obj):
        raise FixtureError(
            "%s is not a capture map: expected {command: {raw: [...]}} keyed by "
            "hex commands (see fixtures/round1_full_capture.json)" % (source or "input"))
    capture: Dict[str, dict] = {}
    for key, value in obj.items():
        if str(key).strip().lower() in _META_KEYS:
            continue
        name = str(key).strip().upper()
        capture[name] = normalize_entry(value)
    return capture


def load_jsonl(path: str) -> Dict[str, dict]:
    """Load a JSONL probe log - only if its records name their commands."""
    capture: Dict[str, dict] = {}
    with open(path, "r", encoding="utf-8") as handle:
        for number, line in enumerate(handle, start=1):
            line = line.strip()
            if not line:
                continue
            try:
                record = json.loads(line)
            except ValueError as exc:
                raise FixtureError("%s line %d is not JSON: %s" % (path, number, exc))
            if not isinstance(record, dict):
                raise FixtureError("%s line %d is not a JSON object" % (path, number))
            command = None
            for key in _COMMAND_KEYS:
                if record.get(key):
                    command = str(record[key]).strip().upper()
                    break
            if not command:
                raise FixtureError(
                    "%s is a positional probe log (line %d has no command field), "
                    "so it cannot be replayed on its own - replay a capture map "
                    "such as fixtures/%s instead, or add a 'command' field per line"
                    % (os.path.basename(path), number, PREFERRED_CAPTURE))
            payload = record.get("raw")
            if payload is None:
                payload = record.get("data", record.get("response"))
            capture[command] = normalize_entry({"raw": payload,
                                                "desc": record.get("desc")})
    if not capture:
        raise FixtureError("%s contains no replayable records" % path)
    return capture


def load_file(path: str) -> Dict[str, dict]:
    """Load one fixture file (.json capture map or .jsonl probe log)."""
    if path.endswith(".jsonl") or path.endswith(".ndjson"):
        return load_jsonl(path)
    try:
        with open(path, "r", encoding="utf-8") as handle:
            obj = json.load(handle)
    except ValueError as exc:
        raise FixtureError("%s is not valid JSON: %s" % (path, exc))
    return normalize_capture(obj, source=os.path.basename(path))


def merge(*captures: Dict[str, dict]) -> Dict[str, dict]:
    """Merge capture maps; later maps win per command."""
    merged: Dict[str, dict] = {}
    for capture in captures:
        for command, entry in (capture or {}).items():
            if str(command).strip().lower() in _META_KEYS:
                continue
            merged[command] = entry
    return merged


def _replayable_files(directory: str) -> List[str]:
    names = sorted(os.listdir(directory))
    return [os.path.join(directory, name) for name in names
            if name.endswith(".json") and not name.startswith("_")]


def load_fixture(path: Optional[str]) -> Dict[str, dict]:
    """Load a fixture from a file or a directory.

    A directory is resolved to its best single capture: the full scan capture if
    it is there, otherwise every capture map in the directory merged together.
    """
    if not path:
        raise FixtureError(
            "replay mode needs a fixture: set DIAG_REPLAY_FIXTURES=<file or dir> "
            "(defaults to fixtures/%s)" % PREFERRED_CAPTURE)
    path = os.path.expanduser(path)
    if os.path.isdir(path):
        preferred = os.path.join(path, PREFERRED_CAPTURE)
        if os.path.isfile(preferred):
            return load_file(preferred)
        captures, errors = [], []
        for candidate in _replayable_files(path):
            try:
                captures.append(load_file(candidate))
            except FixtureError as exc:
                errors.append(str(exc))
        if not captures:
            raise FixtureError("no replayable capture map in %s%s"
                               % (path, (": " + "; ".join(errors[:3])) if errors else ""))
        return merge(*captures)
    if not os.path.isfile(path):
        raise FixtureError("fixture path does not exist: %s" % path)
    return load_file(path)


def describe(source, capture: Optional[Dict[str, dict]] = None) -> dict:
    """Small summary of what a fixture can answer (for ``/health``)."""
    if capture is None:
        capture = load_fixture(source)
    return {
        "source": str(source),
        "commands": len(capture),
        "answered": sorted(command for command, entry in capture.items()
                           if entry.get("raw") and entry["raw"] != [""]),
    }


def resolve(path: Optional[str], default: Optional[str] = None) -> str:
    """Pick the fixture path to use: explicit first, then the fallback."""
    if path:
        return path
    if default:
        return default
    raise FixtureError("no replay fixture configured (DIAG_REPLAY_FIXTURES)")
