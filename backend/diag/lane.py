"""The query lane: single-flight, paced, retrying OBD access.

Everything that touches the car goes through one :class:`DiagLink`. It knows
nothing about Hudiy, protobuf or HTTP - a *host adapter* does the transport and
this class owns the discipline (docs/V1_SPEC.md, "Sequence discipline"):

* **single flight** - one outstanding request, ever. The lock is per-lane, so a
  diagnostics query can never interleave with another diagnostics query.
* **pacing** - a minimum gap between sends. The ELM327 path is slow and the
  charts poller is the primary user of it; the lane yields to it (the lane
  never touches charts' own lock, it merely waits its turn).
* **at most one retry** - a timeout is retried once, then reported as a
  timeout. Retrying harder is what wedged the ELM in Phase 1.
* **stale-handle detection** - if Hudiy still claims the BT link is connected
  while OBD answers stop arriving, the correct diagnosis is not "no data": it
  is a dead ObdManager (AGENTS.md section 4a, verified by power-cycle). The lane
  records that state so the UI can say "ECU reconnecting" instead of hanging.

The lane never fabricates an answer: a failed query is a failed query.
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Protocol

from . import config, framing
from .protocol import DecodedResponse, decode, normalize_command

#: Lane states, as surfaced by ``GET /diag/state`` (V1_SPEC wording first).
STATE_IDLE = "idle"
STATE_SCANNING = "scanning"
STATE_STALE_HANDLE = "stale-handle"
STATE_RECONNECTING = "reconnecting"
STATE_UNAVAILABLE = "unavailable"


class HostAdapter(Protocol):
    """Transport contract. Implemented by proxy, standalone and replay hosts."""

    name: str

    def health(self) -> dict:  # pragma: no cover - protocol documentation
        ...

    def send(self, command: str, request_code: int) -> bool:
        ...

    def wait(self, request_code: int, timeout: float) -> Optional[List[str]]:
        ...


@dataclass
class QueryResult:
    """One request/response exchange, successful or not."""

    command: str
    decoded: DecodedResponse
    raw_items: List[str] = field(default_factory=list)
    duration_s: float = 0.0
    attempts: int = 1
    error: Optional[str] = None
    host_state: dict = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return self.error is None and self.decoded.ok

    def to_dict(self) -> dict:
        payload = self.decoded.to_dict()
        payload.update({
            "duration_s": round(self.duration_s, 3),
            "attempts": self.attempts,
        })
        if self.raw_items:
            payload["raw"] = list(self.raw_items)
        if self.error:
            payload["error"] = self.error
        return payload


class DiagLink:
    """Serialised, paced access to the car through one host adapter."""

    def __init__(
        self,
        host: HostAdapter,
        cfg: Optional[config.Config] = None,
        clock=time.monotonic,
        sleeper=time.sleep,
    ) -> None:
        self.host = host
        self.cfg = cfg or config.load_config()
        self._clock = clock
        self._sleep = sleeper
        self._lock = threading.Lock()
        self._state = STATE_IDLE
        self._state_lock = threading.Lock()
        self._last_send_mono: Optional[float] = None
        self._last_ok_mono: Optional[float] = None
        self._request_counter = self.cfg.request_code_base
        self.consecutive_timeouts = 0
        self.queries = 0
        self.timeouts = 0
        self.retries = 0
        self.failures = 0
        self.aborted = False
        self.last_error: Optional[str] = None
        self.events: List[dict] = []

    # --- state ---------------------------------------------------------------
    @property
    def state(self) -> str:
        with self._state_lock:
            return self._state

    def set_state(self, state: str, note: str = "") -> None:
        with self._state_lock:
            if state != self._state:
                self._state = state
                self.events.append({"at_mono": round(self._clock(), 3),
                                    "state": state, "note": note})
        if len(self.events) > 200:
            del self.events[:-200]

    def reset_abort(self) -> None:
        self.aborted = False

    def abort(self, reason: str) -> None:
        self.aborted = True
        self.set_state(STATE_IDLE, "aborted: %s" % reason)

    def _next_request_code(self) -> int:
        self._request_counter += 1
        return self._request_counter

    # --- health -------------------------------------------------------------
    def health(self) -> dict:
        host_health = self.host.health() if self.host else {}
        age = host_health.get("last_obd_age_s")
        state = self.state
        if state == STATE_IDLE and isinstance(age, (int, float)) and \
                age > self.cfg.stale_age_s and host_health.get("hudiy_connected"):
            state = STATE_STALE_HANDLE
        now = self._clock()
        return {
            "state": state,
            "host": host_health,
            "host_name": getattr(self.host, "name", "unknown"),
            "queries": self.queries,
            "timeouts": self.timeouts,
            "retries": self.retries,
            "failures": self.failures,
            "consecutive_timeouts": self.consecutive_timeouts,
            "last_ok_age_s": (round(now - self._last_ok_mono, 2)
                              if self._last_ok_mono is not None else None),
            "last_error": self.last_error,
            "scanning": state == STATE_SCANNING,
        }

    # --- the one query path -------------------------------------------------
    def query(self, command: str, timeout: Optional[float] = None) -> QueryResult:
        """Run one command, single-flight, with at most one retry."""
        command = normalize_command(command)
        budget = float(timeout or self.cfg.query_timeout_s)
        with self._lock:
            self.queries += 1
            attempts = 0
            error: Optional[str] = None
            raw_items: List[str] = []
            started = self._clock()
            while attempts < (1 + max(0, self.cfg.query_retries)):
                attempts += 1
                if attempts > 1:
                    self.retries += 1
                    self._sleep(self.cfg.reconnect_backoff_s[0])
                self._pace()
                code = self._next_request_code()
                if not self.host.send(command, code):
                    error = "host refused to send (link down?)"
                    break
                self._last_send_mono = self._clock()
                raw_items = self.host.wait(code, budget) or []
                if raw_items:
                    error = None
                    break
                error = "timeout after %.1fs" % budget
                self.timeouts += 1
                self.consecutive_timeouts += 1
                self._note_timeout()
                if self.aborted:
                    break
            duration = self._clock() - started
            parsed = framing.parse_payload(raw_items)
            decoded = decode(command, parsed)
            if error and decoded.status in ("empty", "no_data"):
                decoded.status = "timeout"
                decoded.error = error
            result = QueryResult(
                command=command,
                decoded=decoded,
                raw_items=list(raw_items),
                duration_s=duration,
                attempts=attempts,
                error=error,
                host_state=self._host_state_summary(),
            )
            if error:
                self.failures += 1
                self.last_error = "%s: %s" % (command, error)
            else:
                self.consecutive_timeouts = 0
                self._last_ok_mono = self._clock()
                self.last_error = None
            return result

    # --- internals -----------------------------------------------------------
    def _pace(self) -> None:
        if self._last_send_mono is None:
            return
        elapsed = self._clock() - self._last_send_mono
        remaining = self.cfg.query_spacing_s - elapsed
        if remaining > 0:
            self._sleep(remaining)

    def _host_state_summary(self) -> dict:
        health = self.host.health() if self.host else {}
        summary = {
            "hudiy_connected": health.get("hudiy_connected"),
            "last_obd_age_s": health.get("last_obd_age_s"),
        }
        return summary

    def _note_timeout(self) -> None:
        """Decide whether silences are a dead handle rather than "no data"."""
        summary = self._host_state_summary()
        age = summary.get("last_obd_age_s")
        connected = summary.get("hudiy_connected")
        stale = False
        if self.consecutive_timeouts >= self.cfg.stale_confirm:
            stale = True
        if connected and isinstance(age, (int, float)) and age > self.cfg.stale_age_s:
            stale = True
        if stale:
            self.set_state(
                STATE_RECONNECTING,
                "no OBD answers although the link reports connected "
                "(age=%s) - stale ObdManager, not 'no data'" % (age,))
        else:
            self.set_state(STATE_STALE_HANDLE,
                           "query timed out (consecutive=%d)" % self.consecutive_timeouts)

    def describe(self) -> Dict[str, object]:
        """A compact, log-friendly view of the lane."""
        return {
            "host": getattr(self.host, "name", "unknown"),
            "spacing_s": self.cfg.query_spacing_s,
            "timeout_s": self.cfg.query_timeout_s,
            "max_retries": self.cfg.query_retries,
            "request_code_base": self.cfg.request_code_base,
        }
