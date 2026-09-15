"""HTTP lane tests - stdlib only, no car, no network beyond loopback.

Run:  python3 -m unittest discover -s backend -t .

The point of these tests is the *degradation contract*: a car that is asleep, a
link that cannot be built and a fixture that is missing must all come back as
readable JSON with a status the UI can branch on - never a 500, never a hang.
"""

from __future__ import annotations

import glob
import importlib.util
import json
import os
import shutil
import tempfile
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
FRONTEND = os.path.join(REPO, "frontend")

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

    # -- the overlay page (phase 2): /app/* -> frontend/* -----------------

    def test_overlay_page_is_served_by_the_lane(self):
        status, headers, body = self.get("/app/diag.html")
        self.assertEqual(status, 200)
        self.assertEqual(headers["Content-Type"], "text/html; charset=utf-8")
        text = body.decode("utf-8")
        self.assertIn("<title>Diagnostics</title>", text)
        self.assertIn("/app/diag.css", text)
        self.assertIn("/app/diag.js", text)

    def test_bare_app_path_lands_on_the_page(self):
        status, headers, body = self.get("/app")
        self.assertEqual(status, 200)
        self.assertIn(b"<title>Diagnostics</title>", body)
        self.assertEqual(headers["Content-Type"], "text/html; charset=utf-8")

    def test_overlay_assets_and_hudiy_fragments_are_served(self):
        expected = (
            ("/app/diag.css", "text/css; charset=utf-8", b"--bg"),
            ("/app/diag.js", "application/javascript; charset=utf-8",
             b"window.hudiy"),
            ("/app/hudiy/overlays.json", "application/json; charset=utf-8",
             b'"identifier": "diag"'),
            ("/app/hudiy/applications_menu.json",
             "application/json; charset=utf-8", b'"action": "diag_show"'),
        )
        for path, ctype, needle in expected:
            status, headers, body = self.get(path)
            self.assertEqual(status, 200, path)
            self.assertEqual(headers["Content-Type"], ctype, path)
            self.assertIn(needle, body, path)

    def test_static_404s_and_traversal(self):
        for path in ("/app/nope.html", "/app/hudiy/../overlays.json",
                     "/app/%2e%2e%2fbackend%2fserver.py"):
            with self.assertRaises(urllib.error.HTTPError, msg=path) as ctx:
                self.get(path)
            self.assertEqual(ctx.exception.code, 404, path)

    def test_head_on_static_asset_has_no_body(self):
        request = urllib.request.Request(
            "http://127.0.0.1:%d/app/diag.js" % self.port, method="HEAD")
        with urllib.request.urlopen(request, timeout=30) as handle:
            self.assertEqual(handle.status, 200)
            self.assertGreater(int(handle.headers["Content-Length"]), 0)
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


class StaticAssetTests(unittest.TestCase):
    """`_static_response` is the only file-serving code path - pin its edges."""

    def test_refuses_to_leave_the_frontend_tree(self):
        for bad in ("../backend/server.py", "..%2f..%2fetc%2fpasswd",
                    "/etc/passwd", "../../.git/config"):
            with self.assertRaises(server_mod.NotFound, msg=bad):
                server_mod._static_response(bad)

    def test_defaults_to_the_overlay_page(self):
        response = server_mod._static_response("")
        self.assertEqual(response.status, 200)
        self.assertEqual(response.content_type, "text/html; charset=utf-8")
        self.assertIn(b"<title>Diagnostics</title>", response.body)

    def test_unknown_extension_is_not_guessed(self):
        response = server_mod._static_response("hudiy/README.md")
        self.assertEqual(response.content_type, "text/markdown; charset=utf-8")


class HudiyRegistrationTests(unittest.TestCase):
    """The page and its Hudiy fragments must match the documented schema."""

    def load(self, *parts):
        with open(os.path.join(FRONTEND, *parts), "r", encoding="utf-8") as handle:
            return handle.read()

    def test_overlay_fragment_matches_the_documented_schema(self):
        entry = json.loads(self.load("hudiy", "overlays.json"))
        for key in ("identifier", "action", "url", "width", "height",
                    "visibility", "visibleOnActions", "staticPosition"):
            self.assertIn(key, entry)
        self.assertEqual(entry["identifier"], "diag")
        # The overlay's action field must be EMPTY: Hudiy treats it as one of its
        # own native action ids, and a custom string there (e.g. "diag_show")
        # made Hudiy accept dispatches + set visibility but never create the
        # overlay webview - the menu tap logged fine and nothing ever painted
        # (proven by the red-bench A/B test, 11 Sep). The custom action lives
        # only on the menu item; visibility is runtime-driven by the lane.
        self.assertEqual(entry["action"], "")
        # visibleOnActions must stay EMPTY as well - bench-proven 16 Sep 2026:
        # a non-empty list (["diag_show"]) made the entire chain *succeed*
        # silently (dispatch logged, SetCustomOverlayVisibility accepted,
        # webview created and loaded) yet the overlay NEVER painted; reverting
        # to [] restored it. Runtime visibility is the only show path.
        self.assertEqual(entry["visibleOnActions"], [])
        self.assertEqual((entry["width"], entry["height"]), (800, 480),
                         "the overlay is the head unit's screen size")
        self.assertTrue(entry["url"].endswith("/app/diag.html"))
        diag_show = json.loads(self.load("hudiy", "applications_menu.json"))
        self.assertEqual(diag_show["action"], "diag_show",
                         "the MENU item carries the custom action")

    def test_menu_fragment_is_a_material_icon_in_the_hudiy_category(self):
        item = json.loads(self.load("hudiy", "applications_menu.json"))
        self.assertEqual(item["action"], "diag_show")
        self.assertEqual(item["categories"], ["Hudiy"])
        self.assertIn("Material", item["iconFontFamily"])
        self.assertEqual(item["iconName"], "troubleshoot")
        self.assertEqual(item["label"], "Diagnostics")

    def test_page_reaches_nothing_off_box(self):
        """A car with no internet must still get the whole UI from the lane."""
        for name in ("diag.html", "diag.css", "diag.js"):
            text = self.load(name)
            for needle in ("http://", "https://", "//cdn", "fonts.googleapis",
                           "googleapis"):
                self.assertNotIn(needle, text, "%s must not reach off-box" % name)

    def test_html_links_the_sibling_assets(self):
        html = self.load("diag.html")
        self.assertIn('href="/app/diag.css"', html)
        self.assertIn('src="/app/diag.js"', html)

    def test_every_screen_shell_exists(self):
        html = self.load("diag.html")
        for index in range(9):
            self.assertIn('id="S%d"' % index, html,
                          "V1_SPEC wants screens S0..S8")

    def test_bridge_callbacks_and_the_key_fallback_are_wired(self):
        js = self.load("diag.js")
        for callback in ("onMoveToNextControl", "onMoveToPreviousControl",
                         "onTriggered", "onGoBack"):
            self.assertIn("%s = function" % callback, js)
        self.assertIn("keydown", js, "rule 6 wants a non-Hudiy input path")
        self.assertIn("touchstart", js, "rule 6 wants a touch path")


class MergeConfigTests(unittest.TestCase):
    """`merge_config.py` inserts into a live Hudiy config, never over it."""

    @classmethod
    def setUpClass(cls):
        path = os.path.join(FRONTEND, "hudiy", "merge_config.py")
        spec = importlib.util.spec_from_file_location("diag_merge_config", path)
        cls.mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cls.mod)

    def setUp(self):
        self.cfg = tempfile.mkdtemp(prefix="diag-hudiy-config-")
        self.addCleanup(shutil.rmtree, self.cfg, True)
        # A machine that already runs something else on Hudiy.
        self.write("overlays.json", {
            "overlays": [{"identifier": "race_dash", "url": "http://127.0.0.1:44411/"}],
            "xStep": 20,
        })
        self.write("applications_menu.json", {
            "items": [{"categories": ["Hudiy"], "label": "Race Dash",
                       "action": "race_dash_show"}],
        })

    def write(self, name, payload):
        with open(os.path.join(self.cfg, name), "w", encoding="utf-8") as handle:
            json.dump(payload, handle)

    def read(self, name):
        with open(os.path.join(self.cfg, name), "r", encoding="utf-8") as handle:
            return json.load(handle)

    def test_merges_instead_of_replacing(self):
        self.assertEqual(self.mod.main([self.cfg, "--port", "44414"]), 0)
        doc = self.read("overlays.json")
        ids = [item["identifier"] for item in doc["overlays"]]
        self.assertEqual(sorted(ids), ["diag", "race_dash"])
        self.assertEqual(doc["xStep"], 20, "unrelated keys must survive")
        actions = [item["action"] for item in self.read("applications_menu.json")["items"]]
        self.assertEqual(sorted(actions), ["diag_show", "race_dash_show"])

    def test_re_run_is_idempotent_and_follows_a_port_change(self):
        self.mod.main([self.cfg, "--port", "44414"])
        self.mod.main([self.cfg, "--port", "44414"])
        doc = self.read("overlays.json")
        self.assertEqual(len(doc["overlays"]), 2, "no duplicate overlay entry")
        self.assertEqual(len(self.read("applications_menu.json")["items"]), 2)
        self.mod.main([self.cfg, "--port", "44415"])
        entry = [item for item in self.read("overlays.json")["overlays"]
                 if item["identifier"] == "diag"][0]
        self.assertTrue(entry["url"].endswith(":44415/app/diag.html"))

    def test_it_backs_up_exactly_the_files_it_changes(self):
        self.assertEqual(glob.glob(os.path.join(self.cfg, "*.bak-*")), [],
                         "nothing to back up before the first merge")
        self.mod.main([self.cfg, "--port", "44414"])
        backups = sorted(os.path.basename(path)
                         for path in glob.glob(os.path.join(self.cfg, "*.bak-*")))
        self.assertEqual([name.split(".bak-")[0] for name in backups],
                         ["applications_menu.json", "overlays.json"])
        # ... and the backup still holds the file as it was before the merge.
        with open(os.path.join(self.cfg, backups[0]), "r", encoding="utf-8") as handle:
            self.assertEqual(json.load(handle)["items"][0]["action"], "race_dash_show")

    def test_dry_run_writes_nothing(self):
        self.assertEqual(self.mod.main([self.cfg, "--dry-run"]), 0)
        ids = [item["identifier"] for item in self.read("overlays.json")["overlays"]]
        self.assertEqual(ids, ["race_dash"])
        self.assertEqual(glob.glob(os.path.join(self.cfg, "*.bak-*")), [])

    def test_missing_config_dir_is_not_an_error(self):
        missing = os.path.join(self.cfg, "nope")
        self.assertEqual(self.mod.main([missing]), 0)
        self.assertFalse(os.path.exists(missing), "must not create the layout")

    def test_it_refuses_a_config_file_it_does_not_understand(self):
        self.write("overlays.json", {"overlays": "not-a-list"})
        with self.assertRaises(SystemExit):
            self.mod.main([self.cfg, "--port", "44414"])
        self.assertEqual(self.read("overlays.json"), {"overlays": "not-a-list"},
                         "the original file must be left exactly as it was")


if __name__ == "__main__":
    unittest.main()
