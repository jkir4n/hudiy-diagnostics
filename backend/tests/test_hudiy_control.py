"""Hudiy control-lane tests - stdlib only, loopback, no protobuf required.

Run:  python3 -m unittest discover -s backend/tests

The lane under test is a *client* of Hudiy's TCP API: it says hello, registers
the ``diag_show`` menu action, and answers the dispatches Hudiy sends back by
showing/hiding the custom overlay. Hudiy is not installed on a developer box, so
these tests run a fake Hudiy on an ephemeral loopback port and speak the same
framing the real thing speaks (12-byte little-endian header, then the payload:
``<payload size, message id, flags>`` - see the upstream ``common/Client.py``).

Two things are pinned here that a code reading would miss:

* Hudiy never shows a custom overlay on its own and never closes one. So the
  lane must *push* ``OVERLAY_VISIBILITY_ALWAYS`` on every matching dispatch (not
  once at startup), and the overlay's own Exit has to come back through
  ``POST /ui/hide``.
* Losing Hudiy is normal (it restarts with the car). The lane must reconnect and
  re-register, and ``/health`` must still answer 200 the whole time.
"""

from __future__ import annotations

import json
import os
import socket
import struct
import tempfile
import threading
import time
import types
import unittest

from backend import server as server_mod
from backend.diag import config as config_mod
from backend.diag import hudiy_control as hudiy_mod
from backend.tests.test_diag_server import replay_config

HELLO_NAME = hudiy_mod.HELLO_NAME
ACTION = hudiy_mod.ACTION_SHOW
OVERLAY = hudiy_mod.OVERLAY_IDENTIFIER

HEADER = struct.Struct("<III")


# --------------------------------------------------------------------------- #
# A fake Api_pb2                                                                #
# --------------------------------------------------------------------------- #
class _FakeVersion:
    def __init__(self, major=0, minor=0):
        self.major, self.minor = major, minor

    def _to_dict(self):
        return {"major": self.major, "minor": self.minor}

    def _from_dict(self, data):
        self.major = data.get("major", 0)
        self.minor = data.get("minor", 0)


class _FakeMessage:
    """Minimal protobuf stand-in: the payload is JSON instead of wire-format."""

    FIELDS: dict = {}

    def __init__(self, **kwargs):
        for name, factory in self.FIELDS.items():
            setattr(self, name, kwargs.get(name, factory()))

    def SerializeToString(self) -> bytes:
        data = {}
        for name in self.FIELDS:
            value = getattr(self, name)
            data[name] = value._to_dict() if hasattr(value, "_to_dict") else value
        return json.dumps(data).encode("utf-8")

    def ParseFromString(self, payload: bytes) -> None:
        data = json.loads(payload.decode("utf-8") or "{}")
        for name in self.FIELDS:
            if name not in data:
                continue
            current = getattr(self, name)
            if hasattr(current, "_from_dict"):
                current._from_dict(data[name])
            else:
                setattr(self, name, data[name])


class _HelloRequest(_FakeMessage):
    FIELDS = {"name": str, "api_version": _FakeVersion}


class _HelloResponse(_FakeMessage):
    FIELDS = {"result": int}


class _RegisterActionRequest(_FakeMessage):
    FIELDS = {"action": str}


class _RegisterActionResponse(_FakeMessage):
    FIELDS = {"action": str, "result": bool}


class _DispatchAction(_FakeMessage):
    FIELDS = {"action": str}


class _SetCustomOverlayVisibility(_FakeMessage):
    FIELDS = {"identifier": str, "visibility": int}


class FakeApi:
    """Enough of the generated ``Api_pb2`` for the lane to run."""

    MESSAGE_HELLO_REQUEST = 1
    MESSAGE_HELLO_RESPONSE = 2
    MESSAGE_PING = 3
    MESSAGE_PONG = 4
    MESSAGE_BYEBYE = 5
    MESSAGE_REGISTER_ACTION_REQUEST = 6
    MESSAGE_REGISTER_ACTION_RESPONSE = 7
    MESSAGE_DISPATCH_ACTION = 8
    MESSAGE_SET_CUSTOM_OVERLAY_VISIBILITY = 9

    HELLO_RESPONSE_RESULT_OK = 1
    OVERLAY_VISIBILITY_NONE = 0
    OVERLAY_VISIBILITY_ALWAYS = 1
    OVERLAY_VISIBILITY_NATIVE_UI_ONLY = 2

    API_MAJOR_VERSION = 1
    API_MINOR_VERSION = 0

    HelloRequest = _HelloRequest
    HelloResponse = _HelloResponse
    RegisterActionRequest = _RegisterActionRequest
    RegisterActionResponse = _RegisterActionResponse
    DispatchAction = _DispatchAction
    SetCustomOverlayVisibility = _SetCustomOverlayVisibility

    def classes(self) -> dict:
        return {
            self.MESSAGE_HELLO_REQUEST: self.HelloRequest,
            self.MESSAGE_HELLO_RESPONSE: self.HelloResponse,
            self.MESSAGE_REGISTER_ACTION_REQUEST: self.RegisterActionRequest,
            self.MESSAGE_REGISTER_ACTION_RESPONSE: self.RegisterActionResponse,
            self.MESSAGE_DISPATCH_ACTION: self.DispatchAction,
            self.MESSAGE_SET_CUSTOM_OVERLAY_VISIBILITY: self.SetCustomOverlayVisibility,
        }


# --------------------------------------------------------------------------- #
# A fake Hudiy (one listener, one thread per accepted session)                  #
# --------------------------------------------------------------------------- #
def wait_for(predicate, timeout=5.0, interval=0.01) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if predicate():
            return True
        time.sleep(interval)
    return predicate()


class FakeSession:
    """One accepted connection: reads frames, answers hello/register."""

    def __init__(self, fake: "FakeHudiy", conn: socket.socket):
        self.fake = fake
        self.api = fake.api
        self.conn = conn
        self.received: list = []  # (message_id, decoded message)
        self.closed = threading.Event()
        self.buffer = b""
        self._thread = threading.Thread(target=self._read_loop, daemon=True)
        self._thread.start()

    # --- wire ------------------------------------------------------------- #
    def send(self, message_id: int, message) -> None:
        payload = message.SerializeToString()
        self.conn.sendall(HEADER.pack(len(payload), message_id, 0) + payload)

    def drop(self) -> None:
        try:
            self.conn.shutdown(socket.SHUT_RDWR)
        except OSError:
            pass
        try:
            self.conn.close()
        except OSError:
            pass

    # --- reader ----------------------------------------------------------- #
    def _read_loop(self) -> None:
        classes = self.api.classes()
        try:
            while True:
                chunk = self.conn.recv(4096)
                if not chunk:
                    break
                self.buffer += chunk
                while len(self.buffer) >= HEADER.size:
                    size, message_id, _flags = HEADER.unpack_from(self.buffer, 0)
                    if len(self.buffer) < HEADER.size + size:
                        break
                    payload = self.buffer[HEADER.size:HEADER.size + size]
                    self.buffer = self.buffer[HEADER.size + size:]
                    self._handle(message_id, payload, classes)
        except OSError:
            pass
        finally:
            self.closed.set()

    def _handle(self, message_id: int, payload: bytes, classes: dict) -> None:
        cls = classes.get(message_id)
        message = cls() if cls is not None else None
        if message is not None:
            message.ParseFromString(payload)
        self.received.append((message_id, message))
        api = self.api
        if message_id == api.MESSAGE_HELLO_REQUEST:
            result = self.fake.hello_result
            if result is None:
                result = api.HELLO_RESPONSE_RESULT_OK
            self.send(api.MESSAGE_HELLO_RESPONSE, api.HelloResponse(result=result))
        elif message_id == api.MESSAGE_REGISTER_ACTION_REQUEST:
            self.send(api.MESSAGE_REGISTER_ACTION_RESPONSE, api.RegisterActionResponse(
                action=getattr(message, "action", ""),
                result=self.fake.register_result))

    # --- assertion helpers ------------------------------------------------ #
    def ids(self) -> list:
        return [message_id for message_id, _ in self.received]

    def payloads(self, message_id: int) -> list:
        return [m for mid, m in self.received if mid == message_id]

    def last_payload(self, message_id: int):
        found = self.payloads(message_id)
        return found[-1] if found else None


class FakeHudiy:
    """A fake Hudiy TCP API on an ephemeral loopback port."""

    def __init__(self, hello_result=None, register_result=True):
        self.api = FakeApi()
        self.hello_result = hello_result
        self.register_result = register_result
        self.sessions: list = []
        self._lock = threading.RLock()
        self._listener = socket.socket()
        self._listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._listener.bind(("127.0.0.1", 0))
        self._listener.listen(8)
        self.host, self.port = self._listener.getsockname()
        self._thread = threading.Thread(target=self._accept_loop, daemon=True)
        self._thread.start()

    def _accept_loop(self) -> None:
        while True:
            try:
                conn, _ = self._listener.accept()
            except OSError:
                return
            with self._lock:
                self.sessions.append(FakeSession(self, conn))

    # --- helpers ---------------------------------------------------------- #
    def session(self, index: int, timeout=5.0) -> FakeSession:
        wait_for(lambda: len(self.sessions) > index, timeout)
        return self.sessions[index]

    def frames(self, message_id: int) -> list:
        """Every payload of ``message_id`` across every session, in order."""
        out = []
        for session in list(self.sessions):
            out.extend(session.payloads(message_id))
        return out

    def visibilities(self) -> list:
        return self.frames(self.api.MESSAGE_SET_CUSTOM_OVERLAY_VISIBILITY)

    def last_visibility(self):
        found = self.visibilities()
        return found[-1] if found else None

    def close(self) -> None:
        for session in list(self.sessions):
            session.drop()
        try:
            self._listener.close()
        except OSError:
            pass


def control_for(fake: FakeHudiy, **kwargs) -> "hudiy_mod.HudiyControl":
    """A HudiyControl pointed at ``fake`` with test-speed timings."""
    cfg = types.SimpleNamespace(
        hudiy_host="127.0.0.1",
        hudiy_port=fake.port,
        hudiy_api_path="",
        hudiy_control_timeout_s=0.2,
    )
    options = dict(api_path="", connect_timeout_s=1.0, read_timeout_s=0.2,
                   initial_backoff_s=0.05, max_backoff_s=0.2, backoff_factor=2.0,
                   jitter_s=(0.0, 0.0))
    options.update(kwargs)
    return hudiy_mod.HudiyControl(cfg, api=fake.api, **options)


class ControlLaneTests(unittest.TestCase):
    """The control lane against a fake Hudiy."""

    register_result = True
    hello_result = None

    def setUp(self):
        self.saved_env = os.environ.pop(hudiy_mod.API_PATH_ENV, None)
        self.addCleanup(self._restore_env)
        self.fake = FakeHudiy(hello_result=self.hello_result,
                              register_result=self.register_result)
        self.addCleanup(self.fake.close)

    def _restore_env(self):
        if self.saved_env is not None:
            os.environ[hudiy_mod.API_PATH_ENV] = self.saved_env

    def _start(self, **kwargs):
        control = control_for(self.fake, **kwargs)
        self.addCleanup(control.stop)
        self.assertTrue(control.start(), "the lane must start against a live fake")
        return control

    def _restart_fake(self, **kwargs) -> FakeHudiy:
        self.fake.close()
        self.fake = FakeHudiy(**kwargs)
        self.addCleanup(self.fake.close)
        return self.fake

    # --- handshake --------------------------------------------------------- #
    def test_hello_then_register_on_the_same_session(self):
        control = self._start()
        self.assertTrue(control.wait_until_online(5.0), control.status())
        session = self.fake.session(0)
        self.assertEqual(session.ids()[:2],
                         [self.fake.api.MESSAGE_HELLO_REQUEST,
                          self.fake.api.MESSAGE_REGISTER_ACTION_REQUEST],
                         "Hudiy drops a client that registers before saying hello")
        hello = session.last_payload(self.fake.api.MESSAGE_HELLO_REQUEST)
        self.assertEqual(hello.name, HELLO_NAME)
        self.assertEqual(hello.api_version.major,
                         self.fake.api.API_MAJOR_VERSION)
        register = session.last_payload(self.fake.api.MESSAGE_REGISTER_ACTION_REQUEST)
        self.assertEqual(register.action, ACTION)

    def test_registration_resets_the_overlay_to_hidden(self):
        control = self._start()
        self.assertTrue(control.wait_until_online(5.0))
        self.assertTrue(wait_for(lambda: self.fake.last_visibility() is not None),
                        "a fresh session must not inherit a visible overlay")
        reset = self.fake.last_visibility()
        self.assertEqual(reset.identifier, OVERLAY)
        self.assertEqual(reset.visibility, self.fake.api.OVERLAY_VISIBILITY_NONE)
        self.assertEqual(control.status()["last_visibility"]["visibility"], "NONE")

    def test_refused_registration_is_loud_and_retried(self):
        fake = self._restart_fake(register_result=False)
        control = self._start()
        self.assertTrue(wait_for(lambda: control.status()["sessions"] >= 2),
                        "a refused registration must be retried, not swallowed")
        status = control.status()
        self.assertFalse(status["registered"])
        self.assertNotEqual(status["state"], "online")
        self.assertTrue(wait_for(
            lambda: "REFUSED" in (control.status()["last_error"] or "")),
            "the refusal must name itself in the log/health: %s" % control.status())
        self.assertGreaterEqual(fake.sessions.__len__(), 2)

    def test_hello_refused_keeps_retrying(self):
        self._restart_fake(hello_result=2)  # 2 is not HELLO_RESPONSE_RESULT_OK
        control = self._start()
        self.assertTrue(wait_for(lambda: control.status()["sessions"] >= 2))
        self.assertFalse(control.status()["registered"])
        self.assertNotEqual(control.status()["state"], "online")
        self.assertTrue(control.status()["last_error"])

    # --- dispatch ---------------------------------------------------------- #
    def test_dispatch_shows_the_overlay(self):
        control = self._start()
        self.assertTrue(control.wait_until_online(5.0))
        self.fake.session(0).send(self.fake.api.MESSAGE_DISPATCH_ACTION,
                                  self.fake.api.DispatchAction(action=ACTION))
        self.assertTrue(wait_for(lambda: control.status()["dispatches"] >= 1))
        visibility = self.fake.last_visibility()
        self.assertEqual(visibility.identifier, OVERLAY)
        self.assertEqual(visibility.visibility,
                         self.fake.api.OVERLAY_VISIBILITY_ALWAYS)
        self.assertEqual(control.status()["last_visibility"]["visibility"], "ALWAYS")

    def test_dispatch_is_answered_every_time(self):
        control = self._start()
        self.assertTrue(control.wait_until_online(5.0))
        api = self.fake.api
        for _ in range(3):
            self.fake.session(0).send(api.MESSAGE_DISPATCH_ACTION,
                                      api.DispatchAction(action=ACTION))
        self.assertTrue(wait_for(lambda: control.status()["dispatches"] >= 3))
        # Wait for the third send to land too: the dispatch counter is bumped
        # when the message is parsed, the socket write happens right after.
        self.assertTrue(wait_for(
            lambda: len([v for v in self.fake.visibilities()
                         if v.visibility == api.OVERLAY_VISIBILITY_ALWAYS]) >= 3),
            "every dispatch must be answered with a show")
        always = [v for v in self.fake.visibilities()
                  if v.visibility == api.OVERLAY_VISIBILITY_ALWAYS]
        self.assertEqual(len(always), 3,
                         "Hudiy never re-shows on its own: push on every dispatch")

    def test_foreign_dispatch_is_ignored(self):
        control = self._start()
        self.assertTrue(control.wait_until_online(5.0))
        api = self.fake.api
        self.fake.session(0).send(api.MESSAGE_DISPATCH_ACTION,
                                  api.DispatchAction(action="race_dash_show"))
        self.assertTrue(wait_for(
            lambda: control.status()["ignored_dispatches"] >= 1))
        shown = [v for v in self.fake.visibilities()
                 if v.visibility == api.OVERLAY_VISIBILITY_ALWAYS]
        self.assertEqual(shown, [], "another app's action is not ours to show")

    # --- hide / reconnect -------------------------------------------------- #
    def test_hide_sends_none(self):
        control = self._start()
        self.assertTrue(control.wait_until_online(5.0))
        self.assertTrue(control.hide_overlay())
        visibility = self.fake.last_visibility()
        self.assertEqual(visibility.identifier, OVERLAY)
        self.assertEqual(visibility.visibility,
                         self.fake.api.OVERLAY_VISIBILITY_NONE)

    def test_reconnects_and_re_registers_after_a_drop(self):
        control = self._start()
        self.assertTrue(control.wait_until_online(5.0))
        self.fake.session(0).drop()
        self.assertTrue(wait_for(lambda: len(self.fake.sessions) >= 2),
                        "the lane must come back after Hudiy drops it")
        second = self.fake.session(1)
        self.assertTrue(wait_for(
            lambda: second.last_payload(
                self.fake.api.MESSAGE_REGISTER_ACTION_REQUEST) is not None))
        self.assertTrue(control.wait_until_online(5.0))
        self.assertGreaterEqual(control.status()["sessions"], 2)


class ControlDegradationTests(unittest.TestCase):
    """No Api_pb2 on the box: the lane goes quiet, the app keeps answering."""

    def setUp(self):
        self.saved_env = os.environ.pop(hudiy_mod.API_PATH_ENV, None)
        self.saved_dirs = hudiy_mod.DEFAULT_API_DIRS
        hudiy_mod.DEFAULT_API_DIRS = ()
        self.addCleanup(self._restore)

    def _restore(self):
        hudiy_mod.DEFAULT_API_DIRS = self.saved_dirs
        if self.saved_env is not None:
            os.environ[hudiy_mod.API_PATH_ENV] = self.saved_env

    def test_missing_api_module_is_reported_not_fatal(self):
        control = hudiy_mod.HudiyControl(
            api_path="/nonexistent/Api_pb2.py")
        self.assertFalse(control.available)
        self.assertFalse(control.start(), "no API module means the lane stays down")
        status = control.status()
        self.assertIn("Api_pb2", status["reason"])
        self.assertEqual(status["state"], "unavailable")
        self.assertFalse(status["registered"])
        self.assertFalse(control.hide_overlay(), "no link, no false claim of hiding")
        self.assertFalse(control.show_overlay())

    def test_locate_api_file_resolves_dir_file_and_nesting(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertIsNone(hudiy_mod.locate_api_file(tmp),
                              "an empty dir must not resolve")
            flat = os.path.join(tmp, "Api_pb2.py")
            with open(flat, "w", encoding="utf-8") as handle:
                handle.write("# stand-in\n")
            self.assertEqual(hudiy_mod.locate_api_file(tmp), flat)
            self.assertEqual(hudiy_mod.locate_api_file(flat), flat,
                             "the module file itself is a valid value")
            nested = os.path.join(tmp, "common")
            os.makedirs(nested)
            nested_file = os.path.join(nested, "Api_pb2.py")
            with open(nested_file, "w", encoding="utf-8") as handle:
                handle.write("# stand-in\n")
            self.assertEqual(hudiy_mod.locate_api_file(tmp), nested_file,
                             "the race-dash layout (common/Api_pb2.py) wins")

    def test_env_var_points_at_the_module(self):
        with tempfile.TemporaryDirectory() as tmp:
            flat = os.path.join(tmp, "Api_pb2.py")
            with open(flat, "w", encoding="utf-8") as handle:
                handle.write("# stand-in\n")
            os.environ[hudiy_mod.API_PATH_ENV] = tmp
            self.assertEqual(hudiy_mod.locate_api_file(), flat)

    def test_health_still_answers_without_the_api_module(self):
        cfg = replay_config()
        cfg.hudiy_control_enabled = True
        cfg.hudiy_api_path = "/nonexistent/Api_pb2.py"
        service = server_mod.DiagService(cfg, hudiy=hudiy_mod.HudiyControl(
            cfg, api_path="/nonexistent/Api_pb2.py"))
        response = service.handle("GET", "/health", {})
        self.assertEqual(response.status, 200)
        payload = json.loads(response.body.decode("utf-8"))
        self.assertFalse(payload["hudiy"]["available"])
        self.assertEqual(payload["hudiy"]["state"], "unavailable")
        self.assertTrue(payload["hudiy"]["degraded"])

    def test_control_lane_can_be_disabled(self):
        cfg = replay_config()
        cfg.hudiy_control_enabled = False
        service = server_mod.DiagService(cfg)
        self.assertIsNone(service.hudiy)
        payload = service.health()
        self.assertEqual(payload["hudiy"]["state"], "disabled")

    def test_cli_flag_disables_the_lane(self):
        self.assertTrue(server_mod.parse_args(["--no-hudiy-control"])
                        .no_hudiy_control)


class ControlConfigTests(unittest.TestCase):
    def test_defaults_are_the_documented_ones(self):
        cfg = config_mod.load_config()
        self.assertTrue(getattr(cfg, "hudiy_control_enabled"))
        self.assertEqual(cfg.hudiy_host, "127.0.0.1")
        self.assertEqual(cfg.hudiy_port, 44405)
        self.assertGreaterEqual(cfg.hudiy_control_timeout_s, 1.0,
                                "a sub-second read timeout would spin")
        self.assertGreaterEqual(cfg.hudiy_control_backoff_max_s,
                                cfg.hudiy_control_backoff_s)

    def test_service_builds_a_lane_unless_told_not_to(self):
        cfg = replay_config()
        cfg.hudiy_control_enabled = True
        service = server_mod.DiagService(cfg)
        self.assertIsNotNone(service.hudiy)
        status = service.hudiy.status()
        self.assertEqual(status["action"], ACTION)
        self.assertEqual(status["identifier"], OVERLAY)
        self.assertEqual(status["hello_name"], HELLO_NAME)


class HideEndpointTests(unittest.TestCase):
    """``POST /ui/hide`` - the overlay page's Exit, and the only write route."""

    def setUp(self):
        self.fake = FakeHudiy()
        self.addCleanup(self.fake.close)
        self.control = control_for(self.fake)
        self.addCleanup(self.control.stop)
        self.service = server_mod.DiagService(replay_config(), hudiy=self.control)

    def _hide(self):
        response = self.service.handle("POST", "/ui/hide", {})
        return response, json.loads(response.body.decode("utf-8"))

    def test_hide_route_calls_the_lane(self):
        self.assertTrue(self.control.start())
        self.assertTrue(self.control.wait_until_online(5.0))
        response, payload = self._hide()
        self.assertEqual(response.status, 200)
        self.assertTrue(payload["ok"])
        self.assertTrue(payload["sent"])
        visibility = self.fake.last_visibility()
        self.assertEqual(visibility.identifier, OVERLAY)
        self.assertEqual(visibility.visibility,
                         self.fake.api.OVERLAY_VISIBILITY_NONE)

    def test_hide_route_never_fails_when_the_lane_is_down(self):
        response, payload = self._hide()
        self.assertEqual(response.status, 200,
                         "the Exit must work even with Hudiy unreachable")
        self.assertFalse(payload["sent"])
        self.assertTrue(payload["reason"])

    def test_hide_route_with_the_lane_disabled(self):
        cfg = replay_config()
        cfg.hudiy_control_enabled = False
        service = server_mod.DiagService(cfg)
        response = service.handle("POST", "/ui/hide", {})
        payload = json.loads(response.body.decode("utf-8"))
        self.assertEqual(response.status, 200)
        self.assertFalse(payload["sent"])
        self.assertIn("disabled", payload["reason"].lower())

    def test_hide_is_not_readable_as_get(self):
        with self.assertRaises(server_mod.ServiceError) as caught:
            self.service.handle("GET", "/ui/hide", {})
        self.assertEqual(getattr(caught.exception, "status_code", None), 405)

    def test_post_is_still_rejected_elsewhere(self):
        for path in ("/health", "/diag/scan", "/scan"):
            with self.assertRaises(server_mod.ServiceError) as caught:
                self.service.handle("POST", path, {})
            self.assertEqual(getattr(caught.exception, "status_code", None), 405,
                             "only /ui/* is writable: %s" % path)


class VisibilityMappingTests(unittest.TestCase):
    def test_names_map_to_the_api_ints(self):
        api = FakeApi()
        self.assertEqual(hudiy_mod.visibility_value(api, "NONE"),
                         api.OVERLAY_VISIBILITY_NONE)
        self.assertEqual(hudiy_mod.visibility_value(api, "ALWAYS"),
                         api.OVERLAY_VISIBILITY_ALWAYS)
        self.assertEqual(hudiy_mod.visibility_value(api, "NATIVE_UI_ONLY"),
                         api.OVERLAY_VISIBILITY_NATIVE_UI_ONLY)
        self.assertEqual(hudiy_mod.visibility_value(api, "overlay_visibility_always"),
                         api.OVERLAY_VISIBILITY_ALWAYS,
                         "the raw enum name from the docs is accepted too")
        self.assertEqual(hudiy_mod.visibility_value(api, api.OVERLAY_VISIBILITY_ALWAYS),
                         api.OVERLAY_VISIBILITY_ALWAYS,
                         "an int from a caller passes through unchanged")
        with self.assertRaises(hudiy_mod.HudiyConfigError):
            hudiy_mod.visibility_value(api, "SOMETIMES")


@unittest.skipUnless(hudiy_mod.load_api()[0], "real Api_pb2 not installed here")
class RealApiCompatibilityTests(unittest.TestCase):
    """Against the generated Api_pb2 Hudiy actually ships, when it is present."""

    def test_message_names_and_visibility_exist(self):
        api, path, reason = hudiy_mod.load_api()
        self.assertIsNotNone(api, reason)
        self.assertTrue(path.endswith("Api_pb2.py"))
        for attribute in ("HelloRequest", "RegisterActionRequest", "DispatchAction",
                          "SetCustomOverlayVisibility"):
            self.assertTrue(hasattr(api, attribute), attribute)
        self.assertEqual(hudiy_mod.visibility_value(api, "ALWAYS"),
                         api.OVERLAY_VISIBILITY_ALWAYS)
        self.assertEqual(hudiy_mod.visibility_value(api, "NONE"),
                         api.OVERLAY_VISIBILITY_NONE)

    def test_register_and_dispatch_round_trip(self):
        api, _path, _reason = hudiy_mod.load_api()
        request = api.RegisterActionRequest()
        request.action = ACTION
        decoded = api.RegisterActionRequest()
        decoded.ParseFromString(request.SerializeToString())
        self.assertEqual(decoded.action, ACTION)
        dispatch = api.DispatchAction()
        dispatch.ParseFromString(api.DispatchAction(action=ACTION).SerializeToString())
        self.assertEqual(dispatch.action, ACTION)


if __name__ == "__main__":
    unittest.main()
