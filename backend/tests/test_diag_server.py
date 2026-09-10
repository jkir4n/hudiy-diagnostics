"""HTTP lane tests - stdlib only, no car, no network beyond loopback.

Run:  python3 -m unittest discover -s backend -t .

The point of these tests is the *degradation contract*: a car that is asleep, a
link that cannot be built and a fixture that is missing must all come back as
readable JSON with a status the UI can branch on - never a 500, never a hang.
"""

from __future__ import annotations

import json
import os
import threading
import unittest
import urllib.error
import urllib.request

from backend import server as server_mod
from backend.diag import config as config_mod
from backend.diag import fixtures as fixtures_mod
from backend.diag import hosts as hosts_mod
from backend.diag import lane as lane_mod

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
ROUND1 = os.path.join(REPO, "fixtures", "round1_full_capture.json")

#: Reference-car values, recorded in Phase 1 (docs/DECODED_FIXTURES.md).
VIN = "WVWZZZ1KZAW555555"


def replay_config(fixture: str = ROUND1) -> config_mod.Config:
    """A config pointed at a fixture, with pacing off so tests stay fast."""
    cfg = config_mod.load_config()
    cfg.mode = config_mod.MODE_REPLAY
    cfg.replay_fixture = fixture
    cfg.query_spacing_s = 0.0
    cfg.http_host = "127.0.0.1"
    cfg.http_port = 0
    cfg.vin_decode_enabled = False  # never touch the network in tests
    return cfg


class FakeLink:
    """A link whose health the test dictates (no socket, no OBD)."""

    def __init__(self, connected=None, reachable=None, state=lane_mod.STATE_IDLE,
                 error=None, age_s=0.5):
        self._health = {
            "state": state,
            "host_name": "fake",
            "last_ok_age_s": age_s,
            "consecutive_timeouts": 0,
            "queries": 0,
            "host": {"hudiy_connected": connected, "reachable": reachable,
                     "last_obd_age_s": age_s, "error": error,
                     "source": "fake"},
        }

    def health(self) -> dict:
        return dict(self._health)


class BlockingEngine:
    """An engine that stays in ``run()`` until the test releases it."""

    def __init__(self):
        self.report = None
        self.running = False
        self.entered = threading.Event()
        self.release = threading.Event()

    def run(self, discovered_note="", sections=None) -> dict:
        self.running = True
        self.entered.set()
        self.release.wait(10)
        self.running = False
        return {"scan": {"aborted": False, "finished_at": 1.0},
                "verdict": {"verdict": "unknown"}, "codes": {}}


class ServiceReplayTests(unittest.TestCase):
    """The service against the real reference-car fixture."""

    @classmethod
    def setUpClass(cls):
        cls.service = server_mod.DiagService(replay_config())

    def test_health_reports_replay_mode_and_online_car(self):
        payload = self.service.health()
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["mode"], config_mod.MODE_REPLAY)
        self.assertEqual(payload["obd"]["state"], "online")
        self.assertEqual(payload["replay"]["commands"], 27,
                         "round1_full_capture.json answers 27 commands")
        self.assertIn("uptime", payload, "V1_SPEC /health contract wants uptime")

    def test_scan_returns_the_recorded_car(self):
        payload = self.service.scan()
        self.assertTrue(payload["ok"], payload.get("reason"))
        self.assertEqual(payload["status"], server_mod.STATUS_OK)
        report = payload["report"]
        self.assertEqual(report["vehicle"]["vin"], VIN)
        self.assertGreaterEqual(report["scan"]["queries"], 20)
        self.assertFalse(report["scan"]["aborted"])
        live = report["live"]
        self.assertTrue(live, "a full scan reads live PIDs")
        self.assertTrue(all(e.get("pid") and e.get("name") for e in live),
                        "every live row keeps the PID it asked, even on no-data")

    def test_repeated_scans_do_not_accumulate_link_counters(self):
        first = self.service.scan()["report"]["scan"]
        second = self.service.scan()["report"]["scan"]
        self.assertEqual(first["queries"], second["queries"])
        self.assertEqual(first["steps"], second["steps"])

    def test_scan_section_filter_runs_only_that_phase(self):
        payload = self.service.scan(sections="dtc")
        self.assertEqual(payload["sections"], ["dtc"])
        report = payload["report"]
        self.assertTrue(report["codes"]["queries"], "dtc phase must query")
        self.assertEqual(report["live"], [], "live phase must be skipped")
        self.assertEqual(report["monitor_tests"], [], "mode06 must be skipped")

    def test_unknown_section_is_rejected(self):
        with self.assertRaises(server_mod.BadRequest):
            self.service.scan(sections="dtc,nonsense")

    def test_report_formats_render(self):
        text = self.service.report_response("text")
        self.assertEqual(text.status, 200)
        self.assertIn("HUDIY DIAGNOSTICS REPORT", text.body.decode("utf-8"))
        self.assertIn(VIN, text.body.decode("utf-8"), "the car must be in the report")
        for fmt, prefix in (("csv", "section,"), ("json", "{")):
            response = self.service.report_response(fmt)
            self.assertEqual(response.status, 200, fmt)
            body = response.body.decode("utf-8")
            self.assertTrue(body.startswith(prefix),
                            "%s rendered as %r" % (fmt, body[:40]))
        self.assertIn("text/", self.service.report_response("txt").content_type)
        self.assertIn("section,", self.service.report_response("csv")
                      .body.decode("utf-8"))

    def test_unknown_report_format_is_a_bad_request(self):
        with self.assertRaises(server_mod.BadRequest):
            self.service.report_response("pdf")

    def test_dtc_lookup_finds_text_and_demands_a_code(self):
        payload = self.service.dtc_lookup("P0401")
        self.assertTrue(payload["lookup"]["available"])
        self.assertIn("P0401", str(payload["lookup"]))
        with self.assertRaises(server_mod.BadRequest):
            self.service.dtc_lookup(None)
        with self.assertRaises(server_mod.BadRequest):
            self.service.dtc_lookup("   ")

    def test_vin_decode_offline_and_validation(self):
        payload = self.service.vin_response(VIN, online="0")
        self.assertTrue(payload["ok"])
        self.assertTrue(payload["vin"]["valid"])
        self.assertTrue(payload["vin"]["decoded_offline"])
        with self.assertRaises(server_mod.BadRequest):
            self.service.vin_response("")

    def test_routing_aliases_and_errors(self):
        ok = self.service.handle("GET", "/diag/status", {})
        self.assertEqual(ok.status, 200)
        self.assertIn(b"replay", ok.body)
        rendered = self.service.handle("GET", "/diag/report.csv", {})
        self.assertIn("text/csv", rendered.content_type)
        with self.assertRaises(server_mod.NotFound):
            self.service.handle("GET", "/definitely-not-an-endpoint", {})
        with self.assertRaises(server_mod.ServiceError):
            self.service.handle("POST", "/scan", {})


class DegradationTests(unittest.TestCase):
    """A broken car or a broken config is data, not a crash."""

    def test_asleep_car_is_offline_not_an_error(self):
        service = server_mod.DiagService(
            replay_config(), link=FakeLink(connected=False),
            engine=BlockingEngine())
        obd = service.obd_state()
        self.assertEqual(obd["state"], "offline")
        payload = service.scan()
        self.assertFalse(payload["ok"])
        self.assertEqual(payload["status"], server_mod.STATUS_OFFLINE)
        self.assertIsNone(payload["report"])
        self.assertTrue(payload["hint"])

    def test_missing_fixture_makes_the_lane_unavailable_and_sticky(self):
        cfg = replay_config(os.path.join(REPO, "fixtures", "does-not-exist.json"))
        service = server_mod.DiagService(cfg)
        health = service.health()
        self.assertEqual(health["obd"]["state"], lane_mod.STATE_UNAVAILABLE)
        self.assertIn("FixtureError", health["obd"]["reason"])
        payload = service.scan()
        self.assertEqual(payload["status"], server_mod.STATUS_UNAVAILABLE)
        self.assertIn("FixtureError", payload["reason"])
        # /report must not 500 either: it answers JSON with the reason.
        response = service.report_response("text")
        self.assertEqual(response.status, 200)
        self.assertIn("application/json", response.content_type)
        self.assertIn(b"unavailable", response.body)

    def test_replay_uses_the_bundled_fixture_when_none_is_named(self):
        cfg = replay_config("")
        cfg.replay_fixture = ""
        default = hosts_mod.default_fixture_path()
        self.assertTrue(os.path.isfile(default), "repo must ship a default capture")
        service = server_mod.DiagService(cfg)
        health = service.health()
        self.assertTrue(health["ok"])
        self.assertEqual(health["obd"]["state"], "online")
        self.assertEqual(health["replay"]["source"], default)

    def test_stale_obdmanager_is_surfaced_not_hidden(self):
        link = FakeLink(connected=True, state=lane_mod.STATE_STALE_HANDLE,
                        error="no OBD answer for 42s")
        service = server_mod.DiagService(replay_config(), link=link,
                                         engine=BlockingEngine())
        obd = service.obd_state()
        self.assertEqual(obd["state"], lane_mod.STATE_STALE_HANDLE)
        self.assertIn("42s", obd["reason"])

    def test_second_concurrent_scan_is_busy(self):
        engine = BlockingEngine()
        service = server_mod.DiagService(replay_config(),
                                         host_factory=lambda: hosts_mod.ReplayHost(
                                             fixtures_mod.load_fixture(ROUND1)),
                                         link=FakeLink(connected=True),
                                         engine=engine)
        thread = threading.Thread(target=service.scan)
        thread.start()
        self.assertTrue(engine.entered.wait(5))
        try:
            with self.assertRaises(server_mod.Busy):
                service.scan()
        finally:
            engine.release.set()
            thread.join(5)


class HttpSocketTests(unittest.TestCase):
    """One real round-trip per endpoint over loopback, then shut down."""

    @classmethod
    def setUpClass(cls):
        cls.server, cls.service = server_mod.create_server(replay_config())
        cls.port = cls.server.server_address[1]
        cls.thread = threading.Thread(target=cls.server.serve_forever,
                                      kwargs={"poll_interval": 0.05}, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join(5)

    def get(self, path):
        url = "http://127.0.0.1:%d%s" % (self.port, path)
        with urllib.request.urlopen(url, timeout=30) as handle:
            return handle.status, handle.headers, handle.read()

    def test_health(self):
        status, headers, body = self.get("/health")
        self.assertEqual(status, 200)
        self.assertEqual(headers["Content-Type"], "application/json; charset=utf-8")
        payload = json.loads(body)
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["obd"]["state"], "online")

    def test_scan_and_report(self):
        _, _, body = self.get("/scan")
        payload = json.loads(body)
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["report"]["vehicle"]["vin"], VIN)
        status, headers, body = self.get("/report?format=json")
        self.assertEqual(status, 200)
        self.assertIn("application/json", headers["Content-Type"])
        self.assertEqual(json.loads(body)["vehicle"]["vin"], VIN)

    def test_bad_request_and_not_found_status_codes(self):
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            self.get("/scan?sections=dtc,bogus")
        self.assertEqual(ctx.exception.code, 400)
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            self.get("/dtc")
        self.assertEqual(ctx.exception.code, 400)
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            self.get("/nope")
        self.assertEqual(ctx.exception.code, 404)

    def test_head_has_no_body(self):
        request = urllib.request.Request(
            "http://127.0.0.1:%d/health" % self.port, method="HEAD")
        with urllib.request.urlopen(request, timeout=30) as handle:
            self.assertEqual(handle.status, 200)
            self.assertEqual(handle.read(), b"")


class PathNormalizationTests(unittest.TestCase):
    def test_v1_spec_spellings(self):
        self.assertEqual(server_mod._normalize_path("/diag/status"),
                         ("/health", None))
        self.assertEqual(server_mod._normalize_path("/diag/report.txt"),
                         ("/report", "text"))
        self.assertEqual(server_mod._normalize_path("/diag/report.csv"),
                         ("/report", "csv"))
        self.assertEqual(server_mod._normalize_path("/scan/"), ("/scan", None))
        self.assertEqual(server_mod._normalize_path("/diag/scan"), ("/scan", None))
        self.assertEqual(server_mod._normalize_path("/"), ("/", None))

    def test_boolean_and_first_helpers(self):
        self.assertTrue(server_mod._as_bool("1"))
        self.assertFalse(server_mod._as_bool("off"))
        with self.assertRaises(server_mod.BadRequest):
            server_mod._as_bool("maybe")
        self.assertEqual(server_mod._first({"a": ["x", "y"]}, "a"), "x")
        self.assertIsNone(server_mod._first({"a": ["  "]}, "a"))
        self.assertIsNone(server_mod._first({}, "a"))


if __name__ == "__main__":
    unittest.main()
