"""HTTP surface for the diagnostics lane (stdlib only, no web framework).

The Hudiy UI (and any desktop browser while developing) talks to the car through
these endpoints. Design rules this module obeys:

1. **stdlib only.** ``python3 -m backend.server`` must run on the head unit with
   nothing installed but Python, exactly like the charts process.
2. **Never 5xx your way out of a car problem.** A car that is asleep, an ECU
   that stopped answering and a lane whose host could not be built are all
   *normal* states here: they answer ``200`` with ``{"status": "offline" |
   "unavailable"}`` and a reason, so the UI can show "ECU reconnecting"
   instead of a stack trace (AGENTS.md 4a). ``4xx`` is reserved for a bad
   *request*; ``500`` means we have a bug.
3. **One scan at a time.** A second concurrent ``/scan`` gets ``409`` rather
   than queueing behind a 60 s scan, because the ELM link is single-flight and
   the charts poller must not be starved.
4. **Loopback by default, no auth.** ``DIAG_HTTP_HOST`` can widen the bind
   (see README); doing so is a deliberate act, and the server logs a warning.
5. **Degrade, don't guess.** Nothing here invents vehicle data: a missing
   fixture, DTC database or OBD link is reported as such.

Endpoints (``/diag/<name>`` is accepted as an alias of every one of them, and
``/diag/status`` is the V1_SPEC name for ``/health``):

``GET /health``            lane + OBD state, mode, uptime, last scan
``GET /scan``              full scan -> structured JSON report
``GET /scan?sections=``    the same, restricted to named phases
``GET /report?format=``    text (default), csv or json rendering of the report
``GET /dtc?code=&maker=``  DTC text lookup (generic + maker-specific)
``GET /vin?vin=&online=``  offline VIN decode, optional bounded online enrich
``POST /ui/hide``          hide our own overlay (the page's Exit path)

The one write endpoint is the UI's own Exit: closing a Hudiy custom overlay is
a *control* action on Hudiy, so it is a POST to ``/ui/hide``. It changes
nothing on the car and never fails the request because the control link is
down - it answers ``200`` with ``sent: false`` and a reason instead.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import threading
import time
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Dict, Optional

#: Repo root, so ``python3 backend/server.py`` and ``python3 -m backend.server``
#: both work. The unit file uses the module form; the direct form is what you
#: type while debugging.
_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

#: Read-only static tree for the overlay page: /app/<path> serves frontend/<path>.
#: The Hudiy config fragments live in frontend/hudiy/ and are served from
#: /app/hudiy/*.json so an install can fetch them over HTTP if it wants to.
_FRONTEND_DIR = os.path.join(_REPO_ROOT, "frontend")

#: The whole MIME table the frontend needs - no new dependencies.
_STATIC_TYPES = {
    ".html": "text/html; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".js": "application/javascript; charset=utf-8",
    ".json": "application/json; charset=utf-8",
    ".svg": "image/svg+xml",
    ".png": "image/png",
    ".ico": "image/x-icon",
    ".md": "text/markdown; charset=utf-8",
    ".txt": "text/plain; charset=utf-8",
}

from backend.diag import __version__ as diag_version  # noqa: E402
from backend.diag import config as config_mod  # noqa: E402
from backend.diag import dtc as dtc_mod  # noqa: E402
from backend.diag import fixtures as fixtures_mod  # noqa: E402
from backend.diag import hosts as hosts_mod  # noqa: E402
from backend.diag import hudiy_control as hudiy_mod  # noqa: E402
from backend.diag import lane as lane_mod  # noqa: E402
from backend.diag import report as report_mod  # noqa: E402
from backend.diag import scan as scan_mod  # noqa: E402
from backend.diag import vin as vin_mod  # noqa: E402

log = logging.getLogger("hudiy-diag.http")

SERVICE_NAME = "hudiy-diagnostics"
API_VERSION = 1

#: Machine-readable status values every JSON body carries. The UI branches on
#: these, never on HTTP codes alone (an offline car is a 200).
STATUS_OK = "ok"
STATUS_PARTIAL = "partial"          # scan ran, but aborted on a timeout
STATUS_OFFLINE = "offline"          # the car/ELM link is not answering
STATUS_UNAVAILABLE = "unavailable"  # the lane itself could not be built
STATUS_BAD_REQUEST = "bad_request"
STATUS_BUSY = "busy"                # a scan is already running
STATUS_NOT_FOUND = "not_found"
STATUS_ERROR = "error"

#: ``format=`` aliases -> :data:`backend.diag.report.FORMATS` keys.
FORMAT_ALIASES = {"text": "txt", "txt": "txt", "json": "json", "csv": "csv"}

#: Online VIN decode is a courtesy, never a reason to hold a request open.
VIN_ONLINE_MAX_S = 5.0

#: OBD states that mean "do not even try to scan".
_BLOCKING_STATES = ("offline", lane_mod.STATE_UNAVAILABLE)


# ---------------------------------------------------------------------------
# Response / error plumbing
# ---------------------------------------------------------------------------

class Response:
    """One HTTP response, fully formed before a byte hits the socket."""

    __slots__ = ("status", "body", "content_type", "headers")

    def __init__(self, status: int = 200, body: bytes | str = b"",
                 content_type: str = "application/json; charset=utf-8",
                 headers: Optional[Dict[str, str]] = None) -> None:
        if isinstance(body, str):
            body = body.encode("utf-8")
        self.status = int(status)
        self.body = bytes(body)
        self.content_type = content_type
        self.headers = headers or {}


def json_response(payload: dict, status: int = 200) -> Response:
    body = json.dumps(payload, indent=2, sort_keys=False, default=str)
    return Response(status, body, "application/json; charset=utf-8")


class ServiceError(Exception):
    """An error the HTTP layer can turn into a deliberate status code."""

    status_code = 500
    status = STATUS_ERROR

    def __init__(self, message: str, status_code: Optional[int] = None) -> None:
        super().__init__(message)
        if status_code is not None:
            self.status_code = status_code


class BadRequest(ServiceError):
    status_code = 400
    status = STATUS_BAD_REQUEST


class NotFound(ServiceError):
    status_code = 404
    status = STATUS_NOT_FOUND


class Busy(ServiceError):
    status_code = 409
    status = STATUS_BUSY


# ---------------------------------------------------------------------------
# The application
# ---------------------------------------------------------------------------

class DiagService:
    """Owns one lane's session and serves every endpoint.

    Kept free of any HTTP detail so it can be tested directly (no socket, no
    server thread) and reused by a future in-process Hudiy hook.
    """

    def __init__(self, cfg: Optional[config_mod.Config] = None, *,
                 host=None, link=None, engine=None, store=None,
                 hudiy=None, host_factory=None, clock=time.time) -> None:
        self.cfg = cfg or config_mod.load_config()
        self._clock = clock
        self._started = clock()
        self._build_lock = threading.RLock()
        self._scan_lock = threading.Lock()
        self._built = False
        self._error: Optional[str] = None
        self._host_factory = host_factory
        self.host = host
        self.link = link
        self.engine = engine
        self.store = store
        self.fixture_source: Optional[str] = None
        self.fixture_commands: Optional[int] = None
        self.last_scan: Optional[dict] = None
        # The control lane is independent of the OBD lane: it registers our menu
        # action with Hudiy and drives the overlay. Injection exists so tests can
        # run without Hudiy and without the generated Api_pb2.
        self.hudiy = hudiy
        if self.hudiy is None and getattr(self.cfg, "hudiy_control_enabled", True):
            self.hudiy = hudiy_mod.HudiyControl(self.cfg)

    # --- session ------------------------------------------------------------

    def _default_host_factory(self):
        if self.cfg.normalized_mode() == config_mod.MODE_REPLAY:
            path = fixtures_mod.resolve(self.cfg.replay_fixture,
                                       hosts_mod.default_fixture_path())
            capture = fixtures_mod.load_fixture(path)
            self.fixture_source = path
            self.fixture_commands = len(capture)
            log.info("replay mode: %d commands from %s", len(capture), path)
            return hosts_mod.ReplayHost(capture,
                                        name="replay:%s" % os.path.basename(path))
        return hosts_mod.make_host(self.cfg)

    def _build(self) -> None:
        cfg = self.cfg
        if self.host is None:
            self.host = (self._host_factory or self._default_host_factory)()
        if self.link is None:
            self.link = lane_mod.DiagLink(self.host, cfg)
        if self.store is None:
            self.store = dtc_mod.default_store(cfg)
        if self.engine is None:
            self.engine = scan_mod.ScanEngine(self.link, cfg, db=self.store)
        log.info("lane ready: mode=%s host=%s",
                 cfg.normalized_mode(), getattr(self.host, "name", "?"))

    def _ensure(self) -> None:
        """Build the session once. A build failure is sticky and explainable."""
        if self._built:
            return
        with self._build_lock:
            if self._built:
                return
            try:
                self._build()
            except Exception as exc:  # HostError, FixtureError, ImportError...
                self._error = "%s: %s" % (type(exc).__name__, exc)
                self.host = self.link = self.engine = None
                log.error("lane unavailable: %s", self._error)
            self._built = True

    # --- state --------------------------------------------------------------

    def obd_state(self) -> dict:
        """Classify the OBD link for the UI: online/offline/unknown/..."""
        if self._error:
            return {"state": lane_mod.STATE_UNAVAILABLE, "reason": self._error,
                    "host": None, "host_name": None}
        if self.link is None:
            return {"state": lane_mod.STATE_UNAVAILABLE,
                    "reason": "no link (lane not built)", "host": None,
                    "host_name": None}
        health = self.link.health()
        host_health = health.get("host") or {}
        state = self._classify(health, host_health)
        reason = (host_health.get("error") or health.get("last_error")
                  or (self._error if state == lane_mod.STATE_UNAVAILABLE else None))
        out = {
            "state": state,
            "reason": reason,
            "host": host_health,
            "host_name": health.get("host_name"),
            "link_state": health.get("state"),
            "last_ok_age_s": health.get("last_ok_age_s"),
            "consecutive_timeouts": health.get("consecutive_timeouts"),
            "queries": health.get("queries"),
        }
        if self.fixture_source:
            out["fixture"] = self.fixture_source
        return out

    @staticmethod
    def _classify(health: dict, host_health: dict) -> str:
        raw = health.get("state")
        if raw in (lane_mod.STATE_RECONNECTING, lane_mod.STATE_STALE_HANDLE,
                   lane_mod.STATE_SCANNING):
            # A known-bad link beats a healthy-looking host: a stale ObdManager
            # still reports "connected" while dropping every query.
            return raw
        if host_health.get("reachable") is False:
            return "offline"
        if host_health.get("hudiy_connected") is False:
            return "offline"
        if host_health.get("hudiy_connected") is True:
            return "online"
        return "unknown"

    # --- endpoints ----------------------------------------------------------

    def health(self) -> dict:
        self._ensure()
        uptime = round(self._clock() - self._started, 2)
        engine = self.engine
        payload = {
            "ok": True,  # the service is answering; car reachability is obd.state
            "status": STATUS_OK,
            "service": SERVICE_NAME,
            "version": diag_version,
            "api": API_VERSION,
            "mode": self.cfg.normalized_mode(),
            "mode_requested": self.cfg.mode,
            "uptime": uptime,
            "uptime_s": uptime,
            "http": {"host": self.cfg.http_host, "port": self.cfg.http_port},
            "obd": self.obd_state(),
            "hudiy": self.hudiy_status(),
            "dtc_db": self.store_status(),
            "scan": {
                "running": bool(getattr(engine, "running", False)),
                "last": self.last_scan,
            },
        }
        if self.fixture_source:
            payload["replay"] = {"source": self.fixture_source,
                                 "commands": self.fixture_commands}
        return payload

    def store_status(self) -> dict:
        if self.store is None:
            return {"available": False, "reason": "no DTC store", "rows": []}
        return self.store.status()

    # --- Hudiy control lane -------------------------------------------------

    def hudiy_status(self) -> dict:
        """State of the menu-action/overlay lane - not the car's state.

        Kept separate from ``obd`` on purpose: the car can be asleep while the
        menu still opens this app, and the app can be unable to reach Hudiy
        while the car answers fine. ``state`` is always one of
        online/connecting/offline/unavailable/disabled.
        """
        if self.hudiy is None:
            return {"enabled": False, "available": False, "state": "disabled",
                    "degraded": True, "reason": "DIAG_HUDIY_CONTROL=0",
                    "hello_name": hudiy_mod.HELLO_NAME,
                    "action": hudiy_mod.ACTION_SHOW,
                    "identifier": hudiy_mod.OVERLAY_IDENTIFIER}
        try:
            status = dict(self.hudiy.status())
        except Exception as exc:  # pragma: no cover - status() is defensive
            return {"enabled": True, "available": False, "state": "unavailable",
                    "degraded": True,
                    "reason": "%s: %s" % (type(exc).__name__, exc)}
        status["enabled"] = True
        return status

    def start_control(self) -> bool:
        """Bring up the control lane (menu action + overlay). Idempotent.

        Never raises and never blocks the HTTP listener: an install without
        Api_pb2 keeps serving and reports the miss through ``/health``.
        """
        if self.hudiy is None:
            log.info("Hudiy control lane disabled by configuration "
                     "(DIAG_HUDIY_CONTROL=0)")
            return False
        try:
            started = bool(self.hudiy.start())
        except Exception as exc:
            log.error("could not start the Hudiy control lane: %s: %s",
                      type(exc).__name__, exc)
            return False
        if not started:
            log.error("Hudiy control lane NOT started: %s",
                      self.hudiy_status().get("reason"))
        return started

    def stop_control(self) -> None:
        """Stop the control lane (best effort, never raises)."""
        if self.hudiy is None:
            return
        try:
            self.hudiy.stop()
        except Exception as exc:  # pragma: no cover - exit path
            log.warning("error stopping the Hudiy control lane: %s", exc)

    def ui_hide(self) -> dict:
        """Hide our own overlay - the page's Exit path (``POST /ui/hide``).

        ``ok`` says "the request was handled"; ``sent`` says whether Hudiy
        actually got the message. The page hides itself either way, so a dead
        control link must not look like a failed request.
        """
        if self.hudiy is None:
            return {"ok": True, "status": STATUS_OK, "sent": False,
                    "reason": "the Hudiy control lane is disabled",
                    "hudiy": self.hudiy_status()}
        sent = bool(self.hudiy.hide_overlay())
        status = self.hudiy_status()
        return {
            "ok": True,
            "status": STATUS_OK,
            "sent": sent,
            "reason": None if sent else (status.get("reason")
                                         or "the Hudiy control link is not up"),
            "hudiy": status,
        }

    def scan(self, sections=None) -> dict:
        """Run a scan (or reuse the running one's outcome) and describe it."""
        self._ensure()
        try:
            wanted = scan_mod.normalize_sections(sections)
        except ValueError as exc:  # bad ?sections= -> 400, not a 500
            raise BadRequest(str(exc))
        listed = sorted(wanted) if wanted is not None else None
        if self._error:
            return self._degraded(STATUS_UNAVAILABLE, self._error, listed)
        obd = self.obd_state()
        if obd["state"] in _BLOCKING_STATES:
            return self._degraded(
                STATUS_OFFLINE,
                obd.get("reason") or "the OBD link is not answering",
                listed, obd=obd)
        if not self._scan_lock.acquire(blocking=False):
            raise Busy("a scan is already running on this lane")
        engine = self.engine
        if engine is None:
            self._scan_lock.release()
            return self._degraded(STATUS_UNAVAILABLE,
                                  self._error or "no scan engine", listed, obd=obd)
        started = self._clock()
        try:
            report = engine.run(sections=wanted)
        except RuntimeError as exc:  # engine-level single-flight guard
            raise Busy(str(exc))
        finally:
            self._scan_lock.release()

        scan_meta = report.get("scan") or {}
        aborted = bool(scan_meta.get("aborted"))
        status = STATUS_PARTIAL if aborted else STATUS_OK
        duration = round(self._clock() - started, 2)
        summary = report_mod.summary_line(report)
        self.last_scan = {
            "finished_at": scan_meta.get("finished_at"),
            "duration_s": duration,
            "status": status,
            "summary": summary,
            "abort_reason": scan_meta.get("abort_reason"),
            "sections": listed,
        }
        return {
            "ok": not aborted,
            "status": status,
            "reason": scan_meta.get("abort_reason"),
            "sections": listed,
            "duration_s": duration,
            "summary": summary,
            "obd": obd,
            "report": report,
        }

    def report_response(self, fmt: str = "text") -> Response:
        """Render the current report; scan first if none has run yet."""
        self._ensure()
        key = FORMAT_ALIASES.get(str(fmt or "text").strip().lower().lstrip("."))
        if key is None:
            raise BadRequest("unknown report format %r (allowed: %s)"
                             % (fmt, ", ".join(sorted(FORMAT_ALIASES))))
        if self.engine is not None and getattr(self.engine, "report", None) is None:
            payload = self.scan()
            if payload.get("report") is None:
                # Offline/unavailable: answer JSON even though a file format was
                # asked for, because there is nothing to render and the UI needs
                # the reason. Status stays 200 - this is not a request error.
                return json_response(payload, 200)
        report = getattr(self.engine, "report", None)
        if report is None:
            return json_response(self._degraded(
                STATUS_UNAVAILABLE, self._error or "no report available", None), 200)
        body = report_mod.render(report, key)
        content_type = report_mod.content_type(key)
        if content_type.startswith("text/"):
            content_type += "; charset=utf-8"
        return Response(200, body, content_type)

    def dtc_lookup(self, code: Optional[str], maker: Optional[str] = None) -> dict:
        self._ensure()
        if not code or not str(code).strip():
            raise BadRequest("code is required, e.g. /dtc?code=P0401")
        if not self.cfg.dtc_lookup_enabled:
            return {"ok": False, "status": STATUS_UNAVAILABLE,
                    "reason": "DTC text lookup is disabled (DIAG_DTC_LOOKUP=0)",
                    "lookup": None}
        store = self.store
        if store is None:
            return {"ok": False, "status": STATUS_UNAVAILABLE,
                    "reason": self._error or "no DTC store available",
                    "lookup": None}
        hint = maker or self.cfg.dtc_default_maker or None
        lookup = store.lookup(code, maker=hint)
        return {"ok": bool(lookup.get("available")), "status": STATUS_OK,
                "lookup": lookup, "code": lookup.get("code"), "maker": hint}

    def vin_response(self, raw: Optional[str], online=None,
                     maker: Optional[str] = None) -> dict:
        """Offline VIN decode, with a *bounded* optional online enrichment."""
        if not raw or not str(raw).strip():
            raise BadRequest("vin is required, e.g. /vin?vin=WVWZZZ1KZAW123456")
        self._ensure()
        enabled = self.cfg.vin_decode_enabled if online is None else _as_bool(online)
        hint = maker or self.cfg.dtc_default_maker or None
        timeout = min(float(self.cfg.vin_decode_timeout_s), VIN_ONLINE_MAX_S)
        if not enabled:
            info = vin_mod.resolve(raw, maker_hint=hint, online_enabled=False)
            return {"ok": True, "status": STATUS_OK, "vin": info}
        # The online decode runs in a worker so a dead network can never hold
        # the request hostage; on timeout we answer with the local decode only.
        holder: Dict[str, dict] = {}

        def work() -> None:
            holder["info"] = vin_mod.resolve(
                raw, maker_hint=hint, online_url=self.cfg.vin_decode_url,
                online_enabled=True, timeout=timeout)

        worker = threading.Thread(target=work, name="vin-decode", daemon=True)
        worker.start()
        worker.join(timeout + 0.75)
        info = holder.get("info")
        timed_out = info is None
        if info is None:
            info = vin_mod.resolve(raw, maker_hint=hint, online_enabled=False)
            info["online"] = {
                "available": False, "skipped": False,
                "error": "online decode did not answer within %.1f s" % timeout,
                "fields": {}, "source": self.cfg.vin_decode_url,
            }
        return {"ok": True, "status": STATUS_OK, "vin": info,
                "online_timed_out": timed_out}

    def index(self) -> dict:
        return {
            "ok": True,
            "status": STATUS_OK,
            "service": SERVICE_NAME,
            "version": diag_version,
            "endpoints": {
                "/health": "lane + OBD state",
                "/scan": "full scan (add ?sections=discovery,dtc,pending,"
                         "readiness,mode06,identity,live)",
                "/report": "rendered report (?format=text|csv|json)",
                "/dtc": "DTC text lookup (?code=P0401&maker=volkswagen)",
                "/vin": "VIN decode (?vin=...&online=0|1)",
                "POST /ui/hide": "hide our own Hudiy overlay (the Exit button)",
            },
            "aliases": "/diag/<name> and /diag/status + /diag/report.txt work too",
        }

    # --- request routing ----------------------------------------------------

    def handle(self, method: str, path: str, query: Optional[dict] = None) -> Response:
        """Turn one request into a response. Never raises for a car problem."""
        query = query or {}
        if method not in ("GET", "HEAD", "POST"):
            raise ServiceError("%s is not supported (read-only service)" % method,
                               status_code=405)
        # The overlay page is static: served before route normalisation so that
        # paths like /app/hudiy/overlays.json keep their extension.
        if path == "/app" or path.startswith("/app/"):
            return _static_response(path[4:] if path.startswith("/app/") else "")
        target, forced_format = _normalize_path(path)
        if target.startswith("/ui/"):
            if method != "POST":
                raise ServiceError("%s /ui/* is not supported (use POST)" % method,
                                   status_code=405)
            if target == "/ui/hide":
                return json_response(self.ui_hide())
            raise NotFound("no UI endpoint %r (see / for the list)" % path)
        if method == "POST":
            # Only the UI's own control endpoints accept a body; everything else
            # stays read-only, and a POST must never look like a scan trigger.
            raise ServiceError("POST is only supported on /ui/*", status_code=405)
        try:
            if target == "/health":
                return json_response(self.health())
            if target == "/scan":
                payload = self.scan(sections=_first(query, "sections"))
                payload["ok"] = bool(payload.get("ok"))
                return json_response(payload, 200)
            if target == "/report":
                return self.report_response(
                    forced_format or _first(query, "format") or "text")
            if target == "/dtc":
                return json_response(self.dtc_lookup(_first(query, "code"),
                                                     _first(query, "maker")))
            if target == "/vin":
                return json_response(self.vin_response(_first(query, "vin"),
                                                       online=_first(query, "online"),
                                                       maker=_first(query, "maker")))
            if target == "/":
                return json_response(self.index())
            raise NotFound("no endpoint %r (see / for the list)" % path)
        except ValueError as exc:
            # scan.normalize_sections() reports unknown phases this way.
            raise BadRequest(str(exc))
        except ServiceError:
            raise

    def _degraded(self, status: str, reason: Optional[str], sections,
                  obd: Optional[dict] = None) -> dict:
        return {
            "ok": False,
            "status": status,
            "reason": reason,
            "sections": sections,
            "obd": obd if obd is not None else self.obd_state(),
            "summary": "no scan: %s" % status,
            "report": None,
            "last_scan": self.last_scan,
            "hint": ("The lane keeps trying: start the car or check the ELM link"
                     if status == STATUS_OFFLINE else
                     "Check the lane configuration (DIAG_MODE, "
                     "DIAG_REPLAY_FIXTURES)."),
        }


# ---------------------------------------------------------------------------
# Small helpers
# ---------------------------------------------------------------------------

def _first(query: dict, key: str) -> Optional[str]:
    """First value of a query parameter, or None (a list-wrapped parse_qs)."""
    value = query.get(key)
    if value is None:
        return None
    if isinstance(value, (list, tuple)):
        value = value[0] if value else None
    if value is None:
        return None
    value = str(value).strip()
    return value or None


def _as_bool(value) -> bool:
    """Query-string boolean: absent/truthy conventions, never an exception."""
    if value is None:
        return False
    if isinstance(value, bool):
        return value
    text = str(value).strip().lower()
    if text in ("1", "true", "yes", "on", "y", "t"):
        return True
    if text in ("0", "false", "no", "off", "n", "f"):
        return False
    raise BadRequest("expected a boolean, got %r" % value)


def _normalize_path(path: str):
    """Map a request path onto a route, keeping V1_SPEC's spellings working.

    Returns ``(route, forced_format)``: ``/diag/report.csv`` carries its format
    in the path, which is how V1_SPEC specifies the report endpoint.
    """
    clean = (path or "/").split("?", 1)[0].strip()
    if clean.startswith("/diag"):
        clean = clean[5:] or "/"
    if not clean.startswith("/"):
        clean = "/" + clean
    forced = None
    for suffix, fmt in ((".txt", "text"), (".csv", "csv"), (".json", "json")):
        if clean.endswith(suffix):
            clean, forced = clean[:-len(suffix)], fmt
            break
    clean = clean.rstrip("/") or "/"
    if clean in ("/status", "/diag/status"):
        return "/health", forced
    if clean == "/info":
        return "/", forced
    return clean, forced


def _static_response(relpath: str) -> Response:
    """Serve one file from the repo's ``frontend/`` tree, read-only.

    ``/app/diag.html`` -> ``frontend/diag.html``. Path traversal is refused by
    normalising first and then requiring the result to stay inside the tree, so
    ``/app/../backend/server.py`` is a 404 rather than a source leak.
    """
    rel = urllib.parse.unquote(relpath or "").strip("/")
    if not rel:
        rel = "diag.html"          # /app and /app/ land on the overlay page
    root = os.path.normpath(_FRONTEND_DIR)
    target = os.path.normpath(os.path.join(root, rel))
    if target != root and not target.startswith(root + os.sep):
        raise NotFound("no such static file %r" % relpath)
    if not os.path.isfile(target):
        raise NotFound("no such static file %r (the overlay page lives in "
                       "frontend/)" % relpath)
    with open(target, "rb") as handle:
        body = handle.read()
    ext = os.path.splitext(target)[1].lower()
    return Response(200, body, _STATIC_TYPES.get(ext,
                                                "application/octet-stream"))


# ---------------------------------------------------------------------------
# HTTP plumbing
# ---------------------------------------------------------------------------

class DiagRequestHandler(BaseHTTPRequestHandler):
    server_version = "%s/%s" % (SERVICE_NAME, API_VERSION)
    sys_version = ""
    protocol_version = "HTTP/1.1"

    def log_message(self, format: str, *args) -> None:  # pragma: no cover - noise
        log.info("%s %s", self.address_string(), format % args)

    def do_GET(self) -> None:
        self._serve("GET")

    def do_HEAD(self) -> None:
        self._serve("HEAD")

    def do_POST(self) -> None:
        """Only the UI's own control endpoints (e.g. ``POST /ui/hide``)."""
        self._drain_body()
        self._serve("POST")

    def _drain_body(self) -> None:
        """Consume the request body so HTTP/1.1 keep-alive stays in sync."""
        try:
            length = int(self.headers.get("Content-Length") or 0)
        except (TypeError, ValueError):
            length = 0
        if length > 0:
            try:
                self.rfile.read(length)
            except OSError:  # pragma: no cover - client vanished
                pass

    def _serve(self, method: str) -> None:
        started = time.monotonic()
        try:
            parsed = urllib.parse.urlsplit(self.path)
            query = urllib.parse.parse_qs(parsed.query, keep_blank_values=True)
            server = self.server
            service = server.service if isinstance(server, DiagHTTPServer) else None
            if service is None:  # pragma: no cover - misconfigured server
                raise ServiceError("server has no diagnostics service")
            response = service.handle(method, parsed.path, query)
        except ServiceError as exc:
            response = json_response(_error_body(exc.status, str(exc)),
                                     getattr(exc, "status_code", 500))
        except Exception as exc:  # a bug, not a car problem
            log.exception("unhandled error for %s %s", method, self.path)
            response = json_response(_error_body(
                STATUS_ERROR, "%s: %s" % (type(exc).__name__, exc)), 500)
        body = response.body
        try:
            self.send_response(response.status)
            self.send_header("Content-Type", response.content_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Diag-Service", SERVICE_NAME)
            for name, value in (response.headers or {}).items():
                self.send_header(name, value)
            self.end_headers()
            if method != "HEAD" and body:
                self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError):  # pragma: no cover
            log.info("client went away during %s %s", method, self.path)
        finally:
            log.info("%s %s -> %s in %.1f ms", method, self.path, response.status,
                     (time.monotonic() - started) * 1000.0)


def _error_body(status: str, message: str) -> dict:
    return {"ok": False, "status": status,
            "error": message, "message": message,
            "hint": "see / for the endpoint list"}


class DiagHTTPServer(ThreadingHTTPServer):
    """Threaded server: a 60 s scan must not block ``/health``."""

    daemon_threads = True
    allow_reuse_address = True
    request_queue_size = 16

    def __init__(self, address, service: DiagService,
                 handler=DiagRequestHandler) -> None:
        self.service = service
        super().__init__(address, handler)


def create_server(cfg: Optional[config_mod.Config] = None,
                  service: Optional[DiagService] = None,
                  handler=DiagRequestHandler):
    """Build (server, service) without serving - used by tests and by main()."""
    service = service or DiagService(cfg)
    cfg = service.cfg
    server = DiagHTTPServer((cfg.http_host, int(cfg.http_port)), service, handler)
    return server, service


def _warn_if_exposed(host: str) -> None:
    if host not in ("127.0.0.1", "localhost", "::1"):
        log.warning("binding %s publishes vehicle data to the network with no "
                    "authentication - keep it loopback unless you mean it", host)


def parse_args(argv=None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="python3 -m backend.server",
        description="Hudiy diagnostics HTTP lane (read-only, no car required in "
                    "replay mode).")
    parser.add_argument("--host", help="bind host (default DIAG_HTTP_HOST=127.0.0.1)")
    parser.add_argument("--port", type=int, help="bind port (default 44414)")
    parser.add_argument("--mode", choices=config_mod.MODES,
                        help="force auto|proxy|standalone|replay")
    parser.add_argument("--replay-fixtures",
                        help="fixture file or directory for replay mode")
    parser.add_argument("--log-level", help="DEBUG|INFO|WARNING|ERROR")
    parser.add_argument("--no-hudiy-control", action="store_true",
                        help="do not register the menu action / drive the overlay")
    parser.add_argument("--version", action="store_true",
                        help="print the version and exit")
    return parser.parse_args(argv)


def main(argv=None) -> int:
    args = parse_args(argv)
    if args.version:
        print("%s v%s" % (SERVICE_NAME, diag_version))
        return 0
    cfg = config_mod.load_config()
    if args.host:
        cfg.http_host = args.host
    if args.port:
        cfg.http_port = int(args.port)
    if args.mode:
        cfg.mode = args.mode
    if args.replay_fixtures:
        cfg.replay_fixture = args.replay_fixtures
    if args.no_hudiy_control:
        cfg.hudiy_control_enabled = False
    logging.basicConfig(
        level=getattr(logging, (args.log_level or cfg.log_level).upper(), logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    _warn_if_exposed(cfg.http_host)
    server, service = create_server(cfg)
    # The control lane listens on Hudiy's TCP API; it is what makes the menu
    # entry work at all, and its state is reported under /health -> "hudiy".
    service.start_control()
    log.info("%s v%s listening on http://%s:%d (mode=%s)", SERVICE_NAME,
             diag_version, cfg.http_host, cfg.http_port, cfg.normalized_mode())
    try:
        server.serve_forever(poll_interval=0.5)
    except KeyboardInterrupt:
        log.info("shutting down")
    finally:
        service.stop_control()
        server.server_close()
        if service.store is not None:
            try:
                service.store.close()
            except Exception:  # pragma: no cover - best effort on exit
                pass
    return 0


if __name__ == "__main__":  # pragma: no cover - process entry point
    raise SystemExit(main())
