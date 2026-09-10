"""Hudiy control client: register ``diag_show`` and drive the overlay.

The UI half of this app is a Hudiy *custom overlay* (``frontend/hudiy/overlays.json``).
Hudiy never shows one by itself: a connected client has to ask. This module is
that client, and it speaks exactly the three messages the inventory documents
(``docs/HUDIY_UI_API_INVENTORY.md`` section 2):

1. ``HelloRequest`` with our own name, then keep the socket open - a disconnect
   silently unregisters us and makes every menu tap a no-op again.
2. ``RegisterActionRequest('diag_show')`` once per connection. Hudiy does not
   persist registrations across its own restarts, so this is re-sent on *every*
   reconnect, not just the first.
3. ``SetCustomOverlayVisibility(identifier, visibility)`` addressed by
   *identifier* (never by index): ``ALWAYS`` to show the overlay when the menu
   entry is tapped, ``NONE`` for the page's own Exit path.

It subscribes to **no** OBD status. The diagnostics lane does its own OBD work
through the charts bridge, and on an install that also runs race-dash this
connection is precisely the one Hudiy does not serve OBD to
(``docs/ARCHITECTURE_NOTES.md``, DEF CONSTRAINT) - asking for PID notifications
here would only add another starving client.

Universality: ``common/Api_pb2.py`` (and protobuf itself) are located at runtime.
When either is missing the lane degrades to a no-op that reports *why* through
``status()`` - the HTTP server keeps serving, the menu entry is simply inert.
Nothing numeric from the protocol is baked in: message ids, enum values and the
hello version all come from the loaded module.

Reconnect policy (copied from the proven ``race_dash_toggle.py`` loop): connect,
hello, register, read; on any drop, back off 2 s, then x1.5 up to 30 s, with a
small jitter so two clients on one Pi do not retry in lockstep. Hudiy is silent
between messages, so a quiet socket is *not* a dead one - the read timeout only
bounds shutdown, it never triggers a reconnect on its own.
"""

from __future__ import annotations

import importlib.util
import logging
import os
import random
import socket
import struct
import threading
import time
from typing import Any, Dict, Optional, Tuple

LOG = logging.getLogger("hudiy-diag.hudiy")

#: Hello name. Distinctive on purpose: Hudiy logs it, and it must not be
#: mistaken for the charts process when reading ``hudiy.N.log``.
HELLO_NAME = "HudiyDiagnostics"

#: Menu action registered with Hudiy (matches applications_menu.json).
ACTION_SHOW = "diag_show"

#: Overlay identifier (matches overlays.json).
OVERLAY_IDENTIFIER = "diag"

#: Visibility values by name - resolved through the loaded module, so these
#: strings are labels, not numbers (inventory section 4, rule 9).
VISIBILITY_NONE = "NONE"
VISIBILITY_ALWAYS = "ALWAYS"
VISIBILITY_NATIVE_UI_ONLY = "NATIVE_UI_ONLY"

_VISIBILITY_PREFIX = "OVERLAY_VISIBILITY_"

#: ``DIAG_HUDIY_API_PB2`` accepts either the checkout root (containing
#: ``common/Api_pb2.py``) or the module file itself, and wins over the defaults.
API_PATH_ENV = "DIAG_HUDIY_API_PB2"
DEFAULT_API_DIRS = (
    "~/.local/share/hudiy-diagnostics",
    "/opt/hudiy-diag",
    "/opt/hudiy-obd-charts",
)

#: Wire framing (``common/Client.py``): ``struct.pack('<III', len(payload), id,
#: flags)`` then the payload. Hudiy never has a payload anywhere near this cap.
HEADER = struct.Struct("<III")
MAX_PAYLOAD = 4 * 1024 * 1024

#: Attributes the module must offer for us to speak the protocol at all. A
#: Hudiy API missing any of these is one we do not understand -> degraded.
REQUIRED_API_ATTRIBUTES = (
    "MESSAGE_HELLO_REQUEST", "MESSAGE_HELLO_RESPONSE", "MESSAGE_PING",
    "MESSAGE_PONG", "MESSAGE_BYEBYE", "MESSAGE_REGISTER_ACTION_REQUEST",
    "MESSAGE_REGISTER_ACTION_RESPONSE", "MESSAGE_DISPATCH_ACTION",
    "MESSAGE_SET_CUSTOM_OVERLAY_VISIBILITY", "HelloRequest", "HelloResponse",
    "RegisterActionRequest", "RegisterActionResponse", "DispatchAction",
    "SetCustomOverlayVisibility",
)


class HudiyError(RuntimeError):
    """The control session is broken (or cannot be started) - rebuild it."""


class HudiyConfigError(HudiyError):
    """A configuration/API mismatch: retrying will not help. Never fatal."""


# ---------------------------------------------------------------------------
# Api_pb2 discovery / loading
# ---------------------------------------------------------------------------

def locate_api_file(api_path: Optional[str] = None) -> Optional[str]:
    """Find ``Api_pb2.py``: explicit value, ``DIAG_HUDIY_API_PB2``, defaults.

    Every candidate may be either the file itself or a directory that holds it
    (directly or under ``common/``), which covers both the race-dash deployment
    (``/opt/hudiy-obd-charts/common/Api_pb2.py``) and a vendored copy.
    """
    candidates = []
    for value in (api_path, os.environ.get(API_PATH_ENV)):
        if value:
            candidates.append(value)
    candidates.extend(DEFAULT_API_DIRS)
    for candidate in candidates:
        base = os.path.expanduser(str(candidate))
        probes = (base,
                  os.path.join(base, "common", "Api_pb2.py"),
                  os.path.join(base, "Api_pb2.py"))
        for probe in probes:
            if os.path.basename(probe) == "Api_pb2.py" and os.path.isfile(probe):
                return probe
    return None


def load_api(api_path: Optional[str] = None) -> Tuple[Optional[Any], Optional[str],
                                                      Optional[str]]:
    """Import the frozen Hudiy protobuf module.

    Returns ``(module, path, reason)``. On success ``reason`` is ``None``; on
    any failure ``module`` is ``None`` and ``reason`` says exactly what was
    wrong, because that string is what ``/health`` and the log carry.
    """
    path = locate_api_file(api_path)
    if path is None:
        looked = ", ".join([API_PATH_ENV] + list(DEFAULT_API_DIRS))
        return None, None, ("common/Api_pb2.py not found (set %s; looked in %s)"
                           % (API_PATH_ENV, looked))
    try:
        spec = importlib.util.spec_from_file_location("hudiy_api_pb2", path)
        if spec is None or spec.loader is None:
            return None, path, "could not load %s" % path
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
    except ImportError as exc:
        # Almost always: protobuf itself is not installed on this host.
        return None, path, ("could not import %s (%s) - is protobuf installed? "
                           "pip install protobuf" % (path, exc))
    except Exception as exc:
        return None, path, "could not import %s: %s: %s" % (path,
                                                           type(exc).__name__, exc)
    missing = [name for name in REQUIRED_API_ATTRIBUTES if not hasattr(module, name)]
    if missing:
        return None, path, ("%s is missing %s - this Hudiy API is not one we "
                           "know" % (path, ", ".join(sorted(missing))))
    return module, path, None


def visibility_name(value) -> str:
    """Canonical ``OVERLAY_VISIBILITY_*`` name for a name or a number."""
    if isinstance(value, bool):
        raise HudiyConfigError("expected an overlay visibility, got a bool")
    if isinstance(value, int):
        return "%s%d" % (_VISIBILITY_PREFIX, value)
    name = str(value or "").strip().upper()
    if not name:
        raise HudiyConfigError("empty overlay visibility")
    return name if name.startswith(_VISIBILITY_PREFIX) else _VISIBILITY_PREFIX + name


def visibility_label(value) -> str:
    """Short report label: ``ALWAYS`` / ``NONE`` / ``NATIVE_UI_ONLY`` / ``3``."""
    name = visibility_name(value)
    return name[len(_VISIBILITY_PREFIX):]


def visibility_value(api, value) -> int:
    """Numeric visibility, looked up in the loaded module - never hard-coded."""
    if isinstance(value, int) and not isinstance(value, bool):
        return int(value)
    name = visibility_name(value)
    if hasattr(api, name):
        return int(getattr(api, name))
    enum = getattr(api, "OverlayVisibility", None)
    if enum is not None:
        try:
            return int(enum.Value(name))
        except Exception:
            pass
        candidate = getattr(enum, name, None)
        if isinstance(candidate, int):
            return int(candidate)
    raise HudiyConfigError("this Hudiy API has no overlay visibility %r" % name)


def hello_result_ok(api) -> int:
    """Value of ``HELLO_RESPONSE_RESULT_OK`` however the proto exposes it."""
    for holder in (api, getattr(api, "HelloResponse", None)):
        value = getattr(holder, "HELLO_RESPONSE_RESULT_OK", None) if holder else None
        if isinstance(value, int):
            return int(value)
    return 1


def hello_result_name(api, value: int) -> str:
    """Enum name for a hello result, for logs the human has to read."""
    descriptor = getattr(getattr(api, "HelloResponse", None), "DESCRIPTOR", None)
    if descriptor is not None:
        try:
            enum = descriptor.fields_by_name["result"].enum_type
            return enum.values_by_number[int(value)].name
        except Exception:
            pass
    return str(value)


def _cfg_value(cfg, name: str, default):
    """Read one optional config attribute; a plain object works in tests too."""
    value = getattr(cfg, name, None) if cfg is not None else None
    if value is None:
        return default
    if isinstance(value, str) and not value.strip():
        return default
    return value


# ---------------------------------------------------------------------------
# The control client
# ---------------------------------------------------------------------------

class HudiyControl:
    """One reconnect-capable control connection to Hudiy's TCP API.

    Threading: :meth:`start` spawns ONE daemon thread that owns connect, hello,
    registration and reading. Other threads (the HTTP request thread behind
    ``POST /ui/hide``) only call :meth:`set_overlay_visibility`, which takes the
    send lock and writes to the same socket; a failed send is reported as
    ``False`` and the reader thread notices the dead socket by itself.

    ``status()`` is always safe to call, never blocks on the socket and never
    raises: it is what ``/health`` reports.
    """

    def __init__(self, cfg=None, *, api=None, api_path=None,
                 name: str = HELLO_NAME, action: str = ACTION_SHOW,
                 identifier: str = OVERLAY_IDENTIFIER,
                 connect_timeout_s: float = 2.5,
                 read_timeout_s: Optional[float] = None,
                 initial_backoff_s: float = 2.0, max_backoff_s: float = 30.0,
                 backoff_factor: float = 1.5,
                 jitter_s: Tuple[float, float] = (0.1, 1.0)) -> None:
        self.cfg = cfg
        self._api = api
        self._api_path = api_path or _cfg_value(cfg, "hudiy_api_path", "") or None
        self._name = name
        self._action = action
        self._identifier = identifier
        self._host = str(_cfg_value(cfg, "hudiy_host", "127.0.0.1"))
        self._port = int(_cfg_value(cfg, "hudiy_port", 44405))
        self._connect_timeout_s = float(connect_timeout_s)
        self._read_timeout_s = float(_cfg_value(cfg, "hudiy_control_timeout_s",
                                                read_timeout_s or 30.0))
        self._initial_backoff_s = float(initial_backoff_s)
        self._max_backoff_s = float(max_backoff_s)
        self._backoff_factor = float(backoff_factor)
        self._jitter_s = jitter_s

        self._lock = threading.RLock()       # state
        self._send_lock = threading.Lock()   # socket writes
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._sock: Optional[socket.socket] = None

        self._api_checked = False
        self._api_source: Optional[str] = None
        self._reason: Optional[str] = None

        self._connected = False
        self._registered = False
        self._last_error: Optional[str] = None
        self._last_hello_at: Optional[float] = None
        self._last_register_at: Optional[float] = None
        self._last_dispatch_at: Optional[float] = None
        self._last_visibility: Optional[dict] = None
        self._backoff_s = float(initial_backoff_s)
        self._reset_sent = False

        # Counters (also what the tests assert on).
        self.sessions = 0
        self.hellos = 0
        self.registrations = 0
        self.dispatches = 0
        self.ignored_dispatches = 0
        self.sends = 0

    # --- api loading --------------------------------------------------------

    def _ensure_api(self):
        if self._api is not None:
            return self._api
        with self._lock:
            if self._api is not None:
                return self._api
            if self._api_checked:
                return None
            self._api_checked = True
            module, source, reason = load_api(self._api_path)
            self._api = module
            self._api_source = source
            self._reason = reason
            if module is None:
                LOG.error("Hudiy control lane unavailable: %s", reason)
            else:
                LOG.info("Hudiy control lane using %s", source)
            return self._api

    def _require_api(self):
        """The loaded Hudiy API module, or ``HudiyError`` when we have none."""
        api = self._ensure_api()
        if api is None:
            raise HudiyError(self._reason or "Api_pb2 unavailable")
        return api

    @property
    def reason(self) -> Optional[str]:
        """Why the lane cannot work, or ``None`` when it can."""
        self._ensure_api()
        return self._reason

    @property
    def api_source(self) -> Optional[str]:
        self._ensure_api()
        return self._api_source

    @property
    def available(self) -> bool:
        return self._ensure_api() is not None

    # --- lifecycle ----------------------------------------------------------

    def start(self) -> bool:
        """Start the control thread. ``False`` (logged) when degraded."""
        if self._ensure_api() is None:
            LOG.error("not starting the Hudiy control lane: %s", self._reason)
            return False
        with self._lock:
            if self._thread is not None and self._thread.is_alive():
                return True
            self._stop.clear()
            self._thread = threading.Thread(target=self._run, name="hudiy-control",
                                            daemon=True)
            self._thread.start()
        LOG.info("Hudiy control lane started (hello=%s, action=%s, overlay=%s -> %s:%d)",
                 self._name, self._action, self._identifier, self._host, self._port)
        return True

    def stop(self, timeout: float = 2.0) -> None:
        """Stop the thread and drop the socket (idempotent, never raises)."""
        self._stop.set()
        self._close_socket()
        thread = self._thread
        if (thread is not None and thread.is_alive()
                and thread is not threading.current_thread()):
            thread.join(timeout)

    # --- session ------------------------------------------------------------

    def _run(self) -> None:
        backoff = self._initial_backoff_s
        while not self._stop.is_set():
            try:
                self._session()
                backoff = self._initial_backoff_s
            except Exception as exc:  # one bad session must not kill the lane
                message = "%s: %s" % (type(exc).__name__, exc)
                with self._lock:
                    self._last_error = message
                if not self._stop.is_set():
                    LOG.error("Hudiy control session ended: %s", message)
            finally:
                self._close_socket()
                with self._lock:
                    self._connected = False
                    self._registered = False
                    self._backoff_s = backoff
            if self._stop.is_set():
                break
            delay = backoff + random.uniform(*self._jitter_s)
            LOG.info("reconnecting to Hudiy in %.1f s", delay)
            if self._stop.wait(delay):
                break
            backoff = min(max(backoff * self._backoff_factor, self._initial_backoff_s),
                          self._max_backoff_s)

    def _session(self) -> None:
        self._require_api()  # fails before connecting if we have no API module
        sock = socket.create_connection((self._host, self._port),
                                        timeout=self._connect_timeout_s)
        sock.settimeout(self._read_timeout_s)
        with self._lock:
            self._sock = sock
            self._connected = True
            self._registered = False
            self._last_error = None
            self._backoff_s = self._initial_backoff_s
            self.sessions += 1
        buffer = bytearray()
        try:
            self._hello()
            while not self._stop.is_set():
                frame = self._read_frame(sock, buffer)
                if frame is None:
                    continue  # read timeout: silence is healthy, keep waiting
                consumed, message_id, _flags, payload = frame
                del buffer[:consumed]
                self._handle(message_id, payload)
        finally:
            self._close_socket()

    def _read_frame(self, sock, buffer: bytearray):
        """One frame ``(consumed, id, flags, payload)``, or ``None`` on timeout."""
        while True:
            if len(buffer) >= HEADER.size:
                size, message_id, flags = HEADER.unpack_from(buffer, 0)
                if size > MAX_PAYLOAD:
                    raise HudiyError("Hudiy announced a %d byte payload (cap %d)"
                                     % (size, MAX_PAYLOAD))
                if len(buffer) >= HEADER.size + size:
                    payload = bytes(buffer[HEADER.size:HEADER.size + size])
                    return HEADER.size + size, message_id, flags, payload
            try:
                chunk = sock.recv(65536)
            except socket.timeout:
                return None
            except OSError as exc:
                raise HudiyError("recv failed: %s" % exc) from exc
            if not chunk:
                raise HudiyError("Hudiy closed the connection")
            buffer.extend(chunk)

    def _handle(self, message_id: int, payload: bytes) -> None:
        api = self._require_api()
        if message_id == getattr(api, "MESSAGE_PING", None):
            self._send(api.MESSAGE_PONG)
        elif message_id == getattr(api, "MESSAGE_BYEBYE", None):
            raise HudiyError("Hudiy said byebye")
        elif message_id == api.MESSAGE_HELLO_RESPONSE:
            self._on_hello_response(payload)
        elif message_id == api.MESSAGE_REGISTER_ACTION_RESPONSE:
            self._on_register_response(payload)
        elif message_id == api.MESSAGE_DISPATCH_ACTION:
            self._on_dispatch_action(payload)
        else:
            # We subscribe to nothing outside the control lane, so anything else
            # is not for us - log it once and move on.
            LOG.debug("ignoring Hudiy message id %s", message_id)

    def _hello(self) -> None:
        api = self._require_api()
        request = api.HelloRequest()
        request.name = self._name
        request.api_version.major = int(getattr(api, "API_MAJOR_VERSION", 1))
        request.api_version.minor = int(getattr(api, "API_MINOR_VERSION", 0))
        self._send(api.MESSAGE_HELLO_REQUEST, request.SerializeToString())
        with self._lock:
            self.hellos += 1
            self._last_hello_at = time.time()
        LOG.info("hello sent to Hudiy as %r (API %d.%d, socket %s:%d)", self._name,
                 request.api_version.major, request.api_version.minor,
                 self._host, self._port)

    def _register(self) -> None:
        api = self._require_api()
        request = api.RegisterActionRequest()
        request.action = self._action
        self._send(api.MESSAGE_REGISTER_ACTION_REQUEST, request.SerializeToString())
        with self._lock:
            self.registrations += 1
            self._last_register_at = time.time()
        LOG.info("registering action %r with Hudiy", self._action)

    def _on_hello_response(self, payload: bytes) -> None:
        api = self._require_api()
        response = api.HelloResponse()
        response.ParseFromString(payload)
        result = int(response.result)
        ok = hello_result_ok(api)
        if result != ok:
            # Loud on purpose: a refused hello means the menu entry stays dead
            # and nothing else in the log explains why (inventory section 4).
            raise HudiyError("Hudiy refused the hello: %s (result=%d, wanted %d)"
                             % (hello_result_name(api, result), result, ok))
        LOG.info("Hudiy accepted the hello (%s)", hello_result_name(api, result))
        # The registration does not survive a Hudiy restart, so it is re-sent on
        # every connect - and the overlay state is re-asserted with it, because
        # a forgotten overlay can outlive the client that asked for it.
        self._register()
        self.reset_overlay_visibility()

    def _on_register_response(self, payload: bytes) -> None:
        api = self._require_api()
        response = api.RegisterActionResponse()
        response.ParseFromString(payload)
        action = str(getattr(response, "action", "") or self._action)
        if action != self._action:
            LOG.info("ignoring registration answer for %r", action)
            return
        accepted = bool(response.result)
        if not accepted:
            raise HudiyError("Hudiy REFUSED to register action %r (result=false) - "
                             "the menu entry stays inert" % self._action)
        with self._lock:
            self._registered = True
        LOG.info("action %r registered with Hudiy (result=true) - the menu entry "
                 "now opens overlay %r", self._action, self._identifier)

    def _on_dispatch_action(self, payload: bytes) -> None:
        api = self._require_api()
        message = api.DispatchAction()
        message.ParseFromString(payload)
        action = str(getattr(message, "action", "") or "").strip()
        with self._lock:
            self._last_dispatch_at = time.time()
            self.dispatches += 1
        if action != self._action:
            with self._lock:
                self.ignored_dispatches += 1
            LOG.info("ignoring dispatch for %r (not our action)", action)
            return
        LOG.info("menu tapped: showing overlay %r", self._identifier)
        try:
            self._send_visibility(self._identifier, VISIBILITY_ALWAYS)
        except HudiyConfigError as exc:
            # A config bug must not turn into a reconnect loop.
            LOG.error("cannot show overlay %r: %s", self._identifier, exc)

    # --- sending ------------------------------------------------------------

    def _send(self, message_id: int, payload: bytes = b"") -> None:
        frame = HEADER.pack(len(payload), message_id, 0) + payload
        with self._send_lock:
            sock = self._sock
            if sock is None:
                raise HudiyError("not connected to Hudiy")
            try:
                sock.sendall(frame)
            except OSError as exc:
                raise HudiyError("send failed: %s" % exc) from exc
            with self._lock:
                self.sends += 1

    def _send_visibility(self, identifier: str, visibility) -> bool:
        """Send one ``SetCustomOverlayVisibility``. Raises ``HudiyError``."""
        api = self._require_api()
        value = visibility_value(api, visibility)
        # Report the caller's own label ("ALWAYS"), not the resolved int: the
        # proto hands back a number, and "1" tells an operator nothing.
        label = visibility_label(visibility)
        message = api.SetCustomOverlayVisibility()
        message.identifier = str(identifier)
        message.visibility = value
        self._send(api.MESSAGE_SET_CUSTOM_OVERLAY_VISIBILITY,
                   message.SerializeToString())
        with self._lock:
            self._last_visibility = {"identifier": str(identifier),
                                     "visibility": label,
                                     "value": value, "at": time.time()}
        LOG.info("overlay %r visibility -> %s", identifier, label)
        return True

    def set_overlay_visibility(self, identifier, visibility) -> bool:
        """Ask Hudiy to show/hide an overlay. ``False`` = not sent.

        This is the hide path the HTTP layer uses; it never raises, because a
        dead control link is a reported state, not a request error.
        """
        try:
            return self._send_visibility(identifier, visibility)
        except HudiyError as exc:
            LOG.warning("could not set overlay %r visibility to %s: %s",
                        identifier, visibility, exc)
            return False

    def show_overlay(self) -> bool:
        """Show the diagnostics overlay (what a menu tap does)."""
        return self.set_overlay_visibility(self._identifier, VISIBILITY_ALWAYS)

    def hide_overlay(self) -> bool:
        """Hide the overlay - the page's own Exit path."""
        return self.set_overlay_visibility(self._identifier, VISIBILITY_NONE)

    def reset_overlay_visibility(self) -> bool:
        """Re-assert ``NONE`` after (re)connecting.

        A Hudiy restart forgets the overlay but a client crash can leave one
        stuck visible; re-asserting on connect makes the menu entry the single
        way in, every time.
        """
        sent = self.set_overlay_visibility(self._identifier, VISIBILITY_NONE)
        with self._lock:
            self._reset_sent = sent
        return sent

    # --- introspection ------------------------------------------------------

    def _close_socket(self) -> None:
        with self._send_lock:
            sock, self._sock = self._sock, None
        if sock is None:
            return
        try:
            sock.shutdown(socket.SHUT_RDWR)
        except OSError:
            pass
        except Exception:  # pragma: no cover - fake sockets in tests
            pass
        try:
            sock.close()
        except Exception:  # pragma: no cover - fake sockets in tests
            pass

    def status(self) -> Dict[str, Any]:
        """A JSON-safe snapshot for ``/health``. Never raises, never blocks."""
        api = self._ensure_api()
        with self._lock:
            connected = self._connected
            registered = self._registered
            payload = {
                "available": api is not None,
                "connected": connected,
                "registered": registered,
                "hello_name": self._name,
                "action": self._action,
                "identifier": self._identifier,
                "host": self._host,
                "port": self._port,
                "api_source": self._api_source,
                "sessions": self.sessions,
                "hellos": self.hellos,
                "registrations": self.registrations,
                "dispatches": self.dispatches,
                "ignored_dispatches": self.ignored_dispatches,
                "sends": self.sends,
                "backoff_s": self._backoff_s,
                "last_error": self._last_error,
                "last_dispatch_age_s": (None if self._last_dispatch_at is None
                                        else round(time.time() - self._last_dispatch_at, 2)),
                "last_visibility": (dict(self._last_visibility)
                                    if self._last_visibility else None),
            }
        if api is None:
            payload["state"] = "unavailable"
            payload["degraded"] = True
            payload["reason"] = self._reason
        elif connected and registered:
            payload["state"] = "online"
            payload["degraded"] = False
            payload["reason"] = None
        elif connected:
            payload["state"] = "connecting"
            payload["degraded"] = True
            payload["reason"] = self._last_error
        else:
            payload["state"] = "offline"
            payload["degraded"] = True
            payload["reason"] = self._last_error or "not connected yet"
        return payload

    def is_online(self) -> bool:
        """True once hello was accepted, the action registered and the socket up."""
        with self._lock:
            return bool(self._connected and self._registered)

    def wait_until_online(self, timeout: float = 5.0, interval: float = 0.02) -> bool:
        """Block until the action is registered (tests and install smoke checks)."""
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if self.is_online():
                return True
            time.sleep(interval)
        return self.is_online()
