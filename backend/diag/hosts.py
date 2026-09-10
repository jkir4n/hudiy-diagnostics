"""Host adapters: the three ways one query can reach the car.

:class:`~backend.diag.lane.DiagLink` owns the *discipline* (single flight, pacing,
one retry); a host owns the *transport*. There are exactly three, and which one
is used is a runtime decision - never a build-time one:

``BridgeHost`` (proxy lane)
    Hudiy serves OBD query responses to exactly ONE process - the race-dash
    charts process (AGENTS.md HARD CONSTRAINT 1, ARCHITECTURE_NOTES.md DEF
    CONSTRAINT). So when charts is running, our queries ride its bridge:
    ``POST <charts_bridge_url>`` with a tiny JSON body, response carrying the raw
    Hudiy ``message.data`` items. This is the default on a real install.

``StandaloneHost`` (own the slot)
    Only for installs where race-dash is absent: we open our own Hudiy TCP
    connection and become the served client. The transport is injected as a
    ``HudiyClient`` so the protobuf wiring stays in one small adapter instead of
    leaking into the scan.

``ReplayHost``
    No car at all: answers come from a recorded fixture in the Phase 1 capture
    format (``{command: {"raw": [...]}}``). This is what makes the whole backend
    testable and what lets the frontend develop with no vehicle attached.

Every host reports ``health()`` in the same shape, because the lane reads
``hudiy_connected`` and ``last_obd_age_s`` off it to tell a stale ObdManager
apart from a car that is simply asleep (AGENTS.md 4a).
"""

from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request
from typing import Dict, Iterable, List, Optional, Protocol, Sequence

from . import config

#: Marks a bridged request so a charts-side log shows where it came from.
BRIDGE_CLIENT = "hudiy-diag/1"


class HostError(RuntimeError):
    """A transport failure (not a car failure - those are lane timeouts)."""


# ---------------------------------------------------------------------------
# Replay
# ---------------------------------------------------------------------------

class ReplayHost:
    """Answers from a recorded fixture; never touches a car or a socket."""

    name = "replay"

    def __init__(self, fixture: object, *, name: Optional[str] = None,
                 age_s: float = 0.5, connected: bool = True) -> None:
        self.name = name or "replay"
        if isinstance(fixture, str):
            with open(fixture, "r", encoding="utf-8") as handle:
                fixture = json.load(handle)
        if not isinstance(fixture, dict):
            raise HostError("replay fixture must be a JSON object")
        self.fixture: Dict[str, dict] = fixture
        self._age_s = age_s
        self._connected = connected
        self._pending: Dict[int, List[str]] = {}
        self.sent: List[str] = []

    # --- HostAdapter ----------------------------------------------------
    def health(self) -> dict:
        return {"hudiy_connected": self._connected,
                "last_obd_age_s": self._age_s,
                "source": "replay",
                "commands": len(self.fixture)}

    def send(self, command: str, request_code: int) -> bool:
        self.sent.append(command)
        entry = self.fixture.get(command)
        if entry is None:
            # An unrecorded command is NOT invented: Hudiy reports "NO DATA" as
            # an empty string, which the parser reads as a valid negative answer.
            self._pending[request_code] = [""]
            return True
        raw = entry.get("raw") if isinstance(entry, dict) else entry
        if raw is None:
            raw = [""]
        if isinstance(raw, (str, bytes)):
            raw = [raw]
        self._pending[request_code] = [str(item) for item in raw]
        return True

    def wait(self, request_code: int, timeout: float) -> Optional[List[str]]:
        return self._pending.pop(request_code, None)

    # --- helpers --------------------------------------------------------
    def set_age(self, age_s: float) -> None:
        """Simulate a stale ObdManager (AGENTS.md 4a) in tests."""
        self._age_s = age_s

    def set_connected(self, connected: bool) -> None:
        self._connected = connected


# ---------------------------------------------------------------------------
# Bridge (proxy lane through the charts process)
# ---------------------------------------------------------------------------

class BridgeHost:
    """Rides the charts process's OBD bridge over loopback HTTP.

    Wire contract (small on purpose, so the charts-side patch stays tiny):

    ``POST <charts_bridge_url>``
        request:  ``{"command": "0100", "timeout_s": 15.0, "client": "hudiy-diag/1",
                     "token": "..."}``
        response: ``{"raw": ["4100983BA013"], "error": null, "age_s": 1.2}``
        - ``raw`` is the Hudiy ``message.data`` list, verbatim; an empty list or
          an empty string means "NO DATA" and is a valid answer.
        - ``error`` is only set for bridge/transport problems, never for a car
          that did not answer.

    ``GET <health_url>``
        response: ``{"hudiy_connected": true, "last_obd_age_s": 1.2, ...}``
        (charts already exposes this; the bridge does not need its own).
    """

    name = "bridge"

    def __init__(self, cfg: config.Config, *, opener=None, clock=time.monotonic) -> None:
        self.cfg = cfg
        self._opener = opener or urllib.request.urlopen
        self._clock = clock
        self._pending: Dict[int, List[str]] = {}
        self._health_cache: dict = {}
        self._health_at: Optional[float] = None
        self.last_error: Optional[str] = None

    # --- HostAdapter ----------------------------------------------------
    def health(self) -> dict:
        now = self._clock()
        if self._health_cache and self._health_at is not None \
                and now - self._health_at < 5.0:
            return self._health_cache
        payload = self._get_json(self.cfg.charts_health_url) or {}
        health = {
            "hudiy_connected": payload.get("hudiy_connected"),
            "last_obd_age_s": payload.get("last_obd_age_s"),
            "bridge": True,
            "reachable": bool(payload),
            "error": None if payload else self.last_error,
        }
        self._health_cache = health
        self._health_at = now
        return health

    def send(self, command: str, request_code: int) -> bool:
        body = {
            "command": command,
            "timeout_s": self.cfg.bridge_timeout_s,
            "client": BRIDGE_CLIENT,
            "request_code": request_code,
        }
        if self.cfg.bridge_token:
            body["token"] = self.cfg.bridge_token
        payload = self._post_json(self.cfg.charts_bridge_url, body)
        if payload is None:
            return False
        if payload.get("error"):
            self.last_error = str(payload["error"])
            return False
        raw = payload.get("raw")
        if raw is None:
            raw = payload.get("data") or []
        if isinstance(raw, (str, bytes)):
            raw = [raw]
        self._pending[request_code] = [str(item) for item in raw]
        return True

    def wait(self, request_code: int, timeout: float) -> Optional[List[str]]:
        # The bridge call is synchronous: by the time send() returns, the answer
        # either exists or the car did not answer. ``None`` means "no answer",
        # which the lane records as a timeout - the honest outcome.
        items = self._pending.pop(request_code, None)
        return items or None

    # --- HTTP helpers ---------------------------------------------------
    def _get_json(self, url: str) -> Optional[dict]:
        try:
            request = urllib.request.Request(url, headers={"Accept": "application/json",
                                                           "User-Agent": BRIDGE_CLIENT})
            with self._opener(request, timeout=self.cfg.charts_probe_timeout_s) as response:
                return json.loads(response.read(256 * 1024).decode("utf-8", "replace"))
        except (urllib.error.URLError, OSError, ValueError) as exc:
            self.last_error = "%s: %s" % (type(exc).__name__, exc)
            return None

    def _post_json(self, url: str, body: dict) -> Optional[dict]:
        data = json.dumps(body).encode("utf-8")
        headers = {"Content-Type": "application/json", "Accept": "application/json",
                   "User-Agent": BRIDGE_CLIENT}
        if self.cfg.bridge_token:
            headers["X-Diag-Token"] = self.cfg.bridge_token
        try:
            request = urllib.request.Request(url, data=data, headers=headers, method="POST")
            with self._opener(request, timeout=self.cfg.bridge_timeout_s + 2.0) as response:
                return json.loads(response.read(256 * 1024).decode("utf-8", "replace"))
        except (urllib.error.URLError, OSError, ValueError) as exc:
            self.last_error = "%s: %s" % (type(exc).__name__, exc)
            return None


# ---------------------------------------------------------------------------
# Standalone (own the served slot)
# ---------------------------------------------------------------------------

class HudiyClient(Protocol):
    """The bit of Hudiy's TCP API a standalone host needs, nothing more."""

    def health(self) -> dict:  # pragma: no cover - protocol documentation
        ...

    def send_query(self, command: str, request_code: int) -> bool:
        ...

    def wait_for_query(self, request_code: int, timeout: float) -> Optional[List[str]]:
        ...


class StandaloneHost:
    """Opens our own Hudiy connection and becomes the served client.

    Only correct where race-dash is absent: Hudiy serves exactly one process, so
    running this next to charts starves us *silently* (HARD CONSTRAINT 1). The
    client object is injected so the protobuf/protocol decisions live in one
    adapter (see ``load_hudiy_client``).
    """

    name = "standalone"

    def __init__(self, client: HudiyClient) -> None:
        self.client = client
        self.last_error: Optional[str] = None
        self._pending: Dict[int, List[str]] = {}

    def health(self) -> dict:
        health: dict
        try:
            health = dict(self.client.health())
        except Exception as exc:  # pragma: no cover - defensive
            self.last_error = "%s: %s" % (type(exc).__name__, exc)
            health = {"hudiy_connected": None, "last_obd_age_s": None}
        health.setdefault("bridge", False)
        return health

    def send(self, command: str, request_code: int) -> bool:
        try:
            return bool(self.client.send_query(command, request_code))
        except Exception as exc:  # pragma: no cover - defensive
            self.last_error = "%s: %s" % (type(exc).__name__, exc)
            return False

    def wait(self, request_code: int, timeout: float) -> Optional[List[str]]:
        try:
            items = self.client.wait_for_query(request_code, timeout)
        except Exception as exc:  # pragma: no cover - defensive
            self.last_error = "%s: %s" % (type(exc).__name__, exc)
            return None
        return items or None


# ---------------------------------------------------------------------------
# Choosing a host
# ---------------------------------------------------------------------------

def charts_alive(cfg: config.Config, opener=None) -> bool:
    """True when a race-dash charts process answers its health endpoint."""
    opener = opener or urllib.request.urlopen
    try:
        request = urllib.request.Request(cfg.charts_health_url,
                                         headers={"Accept": "application/json",
                                                  "User-Agent": BRIDGE_CLIENT})
        with opener(request, timeout=cfg.charts_probe_timeout_s) as response:
            if getattr(response, "status", 200) != 200:
                return False
            payload = json.loads(response.read(64 * 1024).decode("utf-8", "replace"))
        return bool(payload) if isinstance(payload, dict) else True
    except (urllib.error.URLError, OSError, ValueError):
        return False


def resolve_mode(cfg: config.Config, *, opener=None,
                 hudiy_client: Optional[HudiyClient] = None) -> str:
    """Decide the mode at runtime. Proxy wins whenever charts is running."""
    mode = cfg.normalized_mode()
    if mode == config.MODE_REPLAY:
        return config.MODE_REPLAY
    if mode == config.MODE_PROXY:
        return config.MODE_PROXY
    if mode == config.MODE_STANDALONE:
        return config.MODE_STANDALONE
    # auto: charts present -> ride its bridge, otherwise own the slot.
    return config.MODE_PROXY if charts_alive(cfg, opener=opener) else config.MODE_STANDALONE


def make_host(cfg: config.Config, *, mode: Optional[str] = None, opener=None,
              hudiy_client: Optional[HudiyClient] = None,
              fixture: Optional[object] = None):
    """Build the host for ``cfg`` (or an explicit ``mode``), never guessing twice."""
    chosen = mode or resolve_mode(cfg, opener=opener, hudiy_client=hudiy_client)
    if chosen == config.MODE_REPLAY:
        return ReplayHost(fixture or cfg.replay_fixture,
                          name="replay:%s" % _fixture_name(cfg, fixture))
    if chosen == config.MODE_PROXY:
        return BridgeHost(cfg, opener=opener)
    if chosen == config.MODE_STANDALONE:
        if hudiy_client is None:
            hudiy_client = load_hudiy_client(cfg)
        if hudiy_client is None:  # pragma: no cover - load_hudiy_client raises
            raise HostError("standalone mode needs a Hudiy client")
        return StandaloneHost(hudiy_client)
    raise HostError("unknown diag mode %r" % chosen)


def _fixture_name(cfg: config.Config, fixture: Optional[object]) -> str:
    if isinstance(fixture, str):
        return os.path.basename(fixture)
    return os.path.basename(cfg.replay_fixture) if cfg.replay_fixture else "inline"


def default_fixture_path() -> str:
    """The reference capture shipped with the repo (kept for replay mode)."""
    here = os.path.dirname(os.path.abspath(__file__))
    repo_fixture = os.path.normpath(os.path.join(here, "..", "..", "fixtures",
                                                "round1_full_capture.json"))
    return repo_fixture if os.path.isfile(repo_fixture) else ""


def load_hudiy_client(cfg: config.Config):
    """Load the standalone Hudiy client, or explain why we cannot.

    The client lives outside this package (it is the same protobuf surface the
    Phase 1 capture tool used). Import failure is reported, never papered over:
    a standalone host that cannot talk to Hudiy must fail loudly at startup
    rather than return empty answers that look like a clean car.
    """
    try:
        from hudiy_client import HudiyTcpClient  # type: ignore
    except Exception as exc:  # pragma: no cover - environment dependent
        raise HostError(
            "standalone mode needs the Hudiy TCP client (host %s:%s); import "
            "failed: %s: %s" % (cfg.hudiy_host, cfg.hudiy_port,
                                type(exc).__name__, exc)) from exc
    return HudiyTcpClient(cfg.hudiy_host, cfg.hudiy_port)
