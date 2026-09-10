"""End-to-end smoke for the Hudiy control lane (overlay show/hide).

Runs the REAL backend server (`python3 -m backend.server`, replay mode) against
a fake Hudiy that speaks the wire framing with the module Hudiy actually ships
(`common/Api_pb2.py`), then drives the documented paths:

    GET  /health         -> hudiy.state online, registered true
    dispatch our action  -> SetCustomOverlayVisibility(ALWAYS) on the wire
    POST /ui/hide        -> ok + sent true, SetCustomOverlayVisibility(NONE)

It exists because the unit tests build their messages with a stub api module:
this is the only check that exercises the real generated protobuf (required
proto2 fields included) through a real socket and the real HTTP route. The NONE
frames are counted only from a mark taken after the dispatch, because
registering resets the overlay to NONE on purpose.

    python3 tools/smoke_control_lane.py                # needs Api_pb2.py
    DIAG_HUDIY_API_PB2=/opt/hudiy-obd-charts python3 tools/smoke_control_lane.py

Exit code 0 means every step passed; the captured frames are printed either way.
Nothing here touches a live Hudiy: both ports are fresh loopback sockets.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import os
import socket
import struct
import subprocess
import sys
import threading
import time
import urllib.request

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)

from backend.diag import hudiy_control as hudiy_mod  # noqa: E402

HEADER = struct.Struct("<III")


def free_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


def load_api(api_path: str):
    """Import Hudiy's generated Api_pb2 from a dir or the file itself."""
    resolved = hudiy_mod.locate_api_file(api_path)
    if resolved is None:
        raise SystemExit("no Api_pb2.py found (pass --api-dir or set %s)"
                         % hudiy_mod.API_PATH_ENV)
    spec = importlib.util.spec_from_file_location("hudiy_api_pb2", resolved)
    if spec is None or spec.loader is None:
        raise SystemExit("cannot load %s as a module" % resolved)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module, resolved


class FakeHudiy:
    """A Hudiy that answers hello/register and records every frame."""

    def __init__(self, api, port: int):
        self.api = api
        self.frames: list = []        # (message_id, decoded message)
        self.connections: list = []
        self._lock = threading.RLock()
        self._listener = socket.socket()
        self._listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._listener.bind(("127.0.0.1", port))
        self._listener.listen(4)
        self.port = port
        threading.Thread(target=self._accept_loop, daemon=True).start()

    # --- sockets ---------------------------------------------------------- #
    def _accept_loop(self) -> None:
        while True:
            try:
                conn, _ = self._listener.accept()
            except OSError:
                return
            with self._lock:
                self.connections.append(conn)
            threading.Thread(target=self._read_loop, args=(conn,),
                             daemon=True).start()

    def _read_loop(self, conn: socket.socket) -> None:
        api = self.api
        classes = {
            api.MESSAGE_HELLO_REQUEST: api.HelloRequest,
            api.MESSAGE_REGISTER_ACTION_REQUEST: api.RegisterActionRequest,
            api.MESSAGE_DISPATCH_ACTION: api.DispatchAction,
            api.MESSAGE_SET_CUSTOM_OVERLAY_VISIBILITY: api.SetCustomOverlayVisibility,
        }
        buffer = b""
        while True:
            try:
                chunk = conn.recv(4096)
            except OSError:
                return
            if not chunk:
                return
            buffer += chunk
            while len(buffer) >= HEADER.size:
                size, message_id, _flags = HEADER.unpack_from(buffer, 0)
                if len(buffer) < HEADER.size + size:
                    break
                payload = buffer[HEADER.size:HEADER.size + size]
                buffer = buffer[HEADER.size + size:]
                cls = classes.get(message_id)
                message = cls() if cls is not None else None
                if message is not None:
                    message.ParseFromString(payload)
                with self._lock:
                    self.frames.append((message_id, message))
                self._answer(conn, message_id, message)

    def _answer(self, conn, message_id, message) -> None:
        api = self.api
        if message_id == api.MESSAGE_HELLO_REQUEST:
            response = api.HelloResponse(result=1)
            response.app_version.major = 1
            response.app_version.minor = 3
            response.api_version.major = api.API_MAJOR_VERSION
            response.api_version.minor = api.API_MINOR_VERSION
            self.send(conn, api.MESSAGE_HELLO_RESPONSE, response)
        elif message_id == api.MESSAGE_REGISTER_ACTION_REQUEST:
            self.send(conn, api.MESSAGE_REGISTER_ACTION_RESPONSE,
                      api.RegisterActionResponse(action=getattr(message, "action", ""),
                                                 result=True))

    def send(self, conn, message_id: int, message) -> None:
        payload = message.SerializeToString()
        conn.sendall(HEADER.pack(len(payload), message_id, 0) + payload)

    # --- helpers ---------------------------------------------------------- #
    def mark(self) -> int:
        """Frame count now, so later assertions can ignore earlier frames."""
        with self._lock:
            return len(self.frames)

    def client(self, timeout: float = 10.0):
        end = time.time() + timeout
        while time.time() < end:
            with self._lock:
                if self.connections:
                    return self.connections[0]
            time.sleep(0.1)
        raise SystemExit("the lane never connected")

    def seen(self, message_id: int, visibility=None, since: int = 0) -> list:
        with self._lock:
            frames = list(self.frames)[since:]
        return [m for mid, m in frames
                if mid == message_id
                and (visibility is None or getattr(m, "visibility", None) == visibility)]

    def ids(self) -> list:
        with self._lock:
            return [mid for mid, _ in self.frames]

    def wait(self, predicate, timeout: float = 10.0):
        end = time.time() + timeout
        while time.time() < end:
            try:
                value = predicate()
            except Exception:
                value = None        # server not listening yet
            if value:
                return value
            time.sleep(0.1)
        return None

    def close(self) -> None:
        for conn in list(self.connections):
            try:
                conn.close()
            except OSError:
                pass
        try:
            self._listener.close()
        except OSError:
            pass


def frame_name(api, message_id: int) -> str:
    for name, value in vars(api).items():
        if name.startswith("MESSAGE_") and value == message_id:
            return name
    return str(message_id)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--api-dir", default=os.environ.get(hudiy_mod.API_PATH_ENV, ""),
                        help="dir holding Api_pb2.py (or the file itself)")
    parser.add_argument("--http-port", type=int, default=0,
                        help="port for the diagnostics server (0 = pick a free one)")
    parser.add_argument("--keep-log", action="store_true",
                        help="always print the server log, not just on failure")
    args = parser.parse_args(argv)

    api, api_source = load_api(args.api_dir)
    http_port = args.http_port or free_port()
    hudiy_port = free_port()
    fake = FakeHudiy(api, hudiy_port)
    env = dict(os.environ, DIAG_MODE="replay", DIAG_HUDIY_API_PB2=api_source,
               HUDIY_TCP_PORT=str(hudiy_port), DIAG_HTTP_PORT=str(http_port))
    child = subprocess.Popen([sys.executable, "-m", "backend.server",
                              "--port", str(http_port), "--log-level", "INFO"],
                             cwd=REPO, env=env, stdout=subprocess.PIPE,
                             stderr=subprocess.STDOUT, text=True)

    def fetch(path: str, method: str = "GET"):
        request = urllib.request.Request(
            "http://127.0.0.1:%d%s" % (http_port, path), method=method)
        with urllib.request.urlopen(request, timeout=5) as response:
            body = response.read().decode("utf-8", "replace")
            try:
                return response.status, json.loads(body)
            except json.JSONDecodeError:
                return response.status, body

    checks: list = []
    results: dict = {"api_source": api_source}

    def check(name: str, condition, detail=None) -> None:
        checks.append((name, bool(condition), detail))

    server_log = ""
    try:
        health = fake.wait(lambda: fetch("/health")[1]
                           if fetch("/health")[0] == 200 else None)
        results["server_answers"] = bool(health)
        check("server_answers", bool(health), "/health never returned 200")
        health = health or {}
        hudiy = health.get("hudiy", {})
        results["hudiy_block"] = hudiy
        check("lane_online", hudiy.get("state") == "online"
              and hudiy.get("registered") is True,
              "state=%s registered=%s" % (hudiy.get("state"), hudiy.get("registered")))
        check("degraded_false", hudiy.get("degraded") is False)

        action = hudiy.get("action")
        hello = fake.seen(api.MESSAGE_HELLO_REQUEST)
        check("hello_sent", bool(hello))
        if hello:
            first = hello[0]
            results["hello"] = {"name": first.name,
                                "api_version": "%d.%d" % (first.api_version.major,
                                                          first.api_version.minor)}
            check("hello_name", first.name == hudiy.get("hello_name"),
                  "%r vs %r" % (first.name, hudiy.get("hello_name")))
            check("hello_api_version",
                  (first.api_version.major, first.api_version.minor)
                  == (api.API_MAJOR_VERSION, api.API_MINOR_VERSION),
                  results["hello"]["api_version"])
        register = fake.seen(api.MESSAGE_REGISTER_ACTION_REQUEST)
        check("registered_our_action",
              bool(register) and register[0].action == action,
              getattr(register[0], "action", None) if register else "no register frame")
        results["register_order"] = [frame_name(api, mid) for mid in fake.ids()[:2]]
        check("hello_before_register",
              fake.ids()[:2] == [api.MESSAGE_HELLO_REQUEST,
                                 api.MESSAGE_REGISTER_ACTION_REQUEST],
              results["register_order"])

        dispatch_mark = fake.mark()
        fake.send(fake.client(), api.MESSAGE_DISPATCH_ACTION,
                  api.DispatchAction(action=action))
        shown = fake.wait(lambda: fake.seen(api.MESSAGE_SET_CUSTOM_OVERLAY_VISIBILITY,
                                            api.OVERLAY_VISIBILITY_ALWAYS,
                                            since=dispatch_mark))
        results["show_frames"] = [{"identifier": m.identifier, "visibility": m.visibility}
                                  for m in (shown or [])]
        check("show_on_dispatch", bool(shown), results["show_frames"])

        hide_mark = fake.mark()
        status, payload = fetch("/ui/hide", "POST")
        results["hide_response"] = payload if isinstance(payload, dict) else str(payload)
        check("hide_http_200", status == 200, status)
        check("hide_ok_and_sent",
              isinstance(payload, dict) and payload.get("ok") is True
              and payload.get("sent") is True, payload)
        hidden = fake.wait(lambda: fake.seen(api.MESSAGE_SET_CUSTOM_OVERLAY_VISIBILITY,
                                             api.OVERLAY_VISIBILITY_NONE,
                                             since=hide_mark))
        results["hide_frames"] = [{"identifier": m.identifier, "visibility": m.visibility}
                                  for m in (hidden or [])]
        check("hide_sends_none_on_wire", bool(hidden), results["hide_frames"])

        status, body = fetch("/app/diag.js")
        with open(os.path.join(REPO, "frontend", "diag.js"), encoding="utf-8") as handle:
            expected = handle.read()
        check("overlay_page_served",
              status == 200 and body == expected,
              "status=%s bytes=%s expected=%s" % (status, len(str(body)), len(expected)))
    finally:
        results["frames"] = [frame_name(api, mid) for mid in fake.ids()]
        child.terminate()
        try:
            child.wait(timeout=5)
        except subprocess.TimeoutExpired:
            child.kill()
        server_log = child.stdout.read() if child.stdout else ""
        fake.close()

    print(json.dumps(results, indent=2, default=str))
    print("---- checks ----")
    failed = 0
    for name, passed, detail in checks:
        print("%s %s%s" % ("PASS" if passed else "FAIL", name,
                           "" if passed or detail is None else "  (%s)" % (detail,)))
        failed += 0 if passed else 1
    if failed or args.keep_log:
        print("---- server log (tail) ----")
        print("\n".join(server_log.strip().splitlines()[-15:]))
    print("\n%d/%d checks passed" % (len(checks) - failed, len(checks)))
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
