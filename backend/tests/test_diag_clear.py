"""Mode 04 clear (POST /clear) tests - stdlib only, no car.

Run:  python3 -m unittest discover -s backend/tests -t .

Every Mode 04 reply here is synthetic (no live ECU answers Mode 04 in dev):
positive ``44``, ELM echo variants, ``NO DATA`` silence and ``7F 04 <NRC>``
refusals all travel through the real lane (``DiagLink``) and the real
``ReplayHost`` wiring, so the tests prove the interpretation, not a stub.
"""

from __future__ import annotations

import json
import threading
import unittest
import urllib.error
import urllib.request

from backend import server as server_mod
from backend.diag import clear as clear_mod
from backend.diag import config as config_mod
from backend.diag import hosts as hosts_mod
from backend.diag import lane as lane_mod
from backend.diag import protocol as protocol_mod

#: The frontend seam contract: a successful clear carries EXACTLY these keys.
SUCCESS_KEYS = frozenset({
    "ok", "status", "mode04_positive", "duration_s", "codes_seen_before",
    "followup", "permanent_codes_note",
})
#: A silent ECU (NO DATA) carries EXACTLY these keys.
UNSUPPORTED_KEYS = frozenset({
    "ok", "status", "mode04_positive", "duration_s", "codes_seen_before",
    "reason", "permanent_codes_note",
})
#: An ECU refusal (7F 04 NRC) carries EXACTLY these keys.
REFUSED_KEYS = UNSUPPORTED_KEYS | frozenset({"nrc", "nrc_name"})


def clear_config() -> config_mod.Config:
    """A config pointed at inline fixtures, with pacing off for speed."""
    cfg = config_mod.load_config()
    cfg.mode = config_mod.MODE_REPLAY
    cfg.query_spacing_s = 0.0
    cfg.query_timeout_s = 5.0
    cfg.query_retries = 0
    cfg.http_host = "127.0.0.1"
    cfg.http_port = 0
    cfg.vin_decode_enabled = False  # never touch the network in tests
    return cfg


def clear_service(fixture: dict,
                  cfg: config_mod.Config | None = None) -> server_mod.DiagService:
    """A service answering Mode 03/04 from an inline fixture map."""
    cfg = cfg or clear_config()
    host = hosts_mod.ReplayHost(dict(fixture))
    link = lane_mod.DiagLink(host, cfg)
    return server_mod.DiagService(cfg, host=host, link=link)


def sent_commands(service: server_mod.DiagService) -> list:
    """Commands the service's replay host has sent (gate tests)."""
    return list(getattr(service.host, "sent", None) or [])


class ScriptedHost:
    """A host with per-command scripted answers; unscripted means silence."""

    name = "scripted"

    def __init__(self, answers: dict) -> None:
        self.answers = dict(answers)
        self.sent: list = []
        self._pending: dict = {}

    def health(self) -> dict:
        return {"hudiy_connected": True, "last_obd_age_s": 0.5,
                "source": "scripted", "commands": len(self.answers)}

    def send(self, command: str, request_code: int) -> bool:
        self.sent.append(command)
        raw = self.answers.get(command)
        self._pending[request_code] = list(raw) if raw is not None else None
        return True

    def wait(self, request_code: int, timeout: float):
        return self._pending.pop(request_code, None)


class BlockingLink:
    """A link whose Mode 04 query blocks until the test releases it."""

    def __init__(self) -> None:
        self.entered_04 = threading.Event()
        self.release_04 = threading.Event()

    def health(self) -> dict:
        return {"state": lane_mod.STATE_IDLE, "host_name": "blocking",
                "last_ok_age_s": 0.5, "consecutive_timeouts": 0, "queries": 0,
                "host": {"hudiy_connected": True, "last_obd_age_s": 0.5,
                         "source": "blocking"}}

    def query(self, command: str, timeout=None, retries=None):
        if command == "04":
            self.entered_04.set()
            self.release_04.wait(10)
            decoded = protocol_mod.decode_raw_items("04", ["44"])
            return lane_mod.QueryResult(command=command, decoded=decoded,
                                        raw_items=["44"])
        decoded = protocol_mod.decode_raw_items("03", ["43 00"])
        return lane_mod.QueryResult(command=command, decoded=decoded,
                                    raw_items=["43 00"])


class ConfirmGateTests(unittest.TestCase):
    def test_missing_confirm_is_rejected_before_the_lane(self):
        service = clear_service({"03": {"raw": ["43 00"]},
                                 "04": {"raw": ["44"]}})
        for bad in (None, "", "  ", "no", "true", "1"):
            with self.assertRaises(server_mod.BadRequest, msg=repr(bad)):
                service.clear(confirm=bad)
        self.assertEqual(sent_commands(service), [],
                         "a gated clear must never touch the lane")

    def test_rejection_names_the_consequence_list(self):
        service = clear_service({"04": {"raw": ["44"]}})
        with self.assertRaises(server_mod.BadRequest) as ctx:
            service.clear(confirm=None)
        message = str(ctx.exception)
        self.assertIn("confirm=yes", message)
        self.assertIn("consequence list", message)

    def test_yes_is_accepted_case_insensitively(self):
        service = clear_service({"03": {"raw": ["43 00"]},
                                 "04": {"raw": ["44"]}})
        payload = service.clear(confirm="YES")
        self.assertTrue(payload["ok"])


class PositiveClearTests(unittest.TestCase):
    def test_success_matches_the_seam_contract_exactly(self):
        service = clear_service({"03": {"raw": ["43 01 04 01"]},
                                 "04": {"raw": ["44"]}})
        payload = service.clear(confirm="yes")
        self.assertEqual(set(payload), SUCCESS_KEYS)
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["status"], "done")
        self.assertTrue(payload["mode04_positive"])
        self.assertIsInstance(payload["duration_s"], float)
        self.assertEqual(payload["codes_seen_before"], 1,
                         "43 01 04 01 holds one stored code (P0401)")
        self.assertEqual(payload["followup"],
                         {"readiness": "incomplete",
                          "message": "monitors reset; drive cycle needed"})
        self.assertIn("cannot be cleared by any tool",
                      payload["permanent_codes_note"])
        self.assertEqual(sent_commands(service), ["03", "04"],
                         "Mode 03 pre-read runs before the Mode 04 send")

    def test_zero_codes_is_still_a_legal_clear(self):
        service = clear_service({"03": {"raw": ["43 00"]},
                                 "04": {"raw": ["44"]}})
        payload = service.clear(confirm="yes")
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["codes_seen_before"], 0)

    def test_elm_echo_variant_is_positive(self):
        # With echo on (ATE1) the request bytes arrive glued in front.
        for raw in (["04 44"], ["04", "44"]):
            service = clear_service({"03": {"raw": ["43 00"]},
                                     "04": {"raw": raw}})
            payload = service.clear(confirm="yes")
            self.assertTrue(payload["ok"], raw)
            self.assertTrue(payload["mode04_positive"], raw)


class NegativeClearTests(unittest.TestCase):
    def test_silence_is_unsupported_not_an_error(self):
        service = clear_service({"03": {"raw": ["43 00"]},
                                 "04": {"raw": [""]}})
        payload = service.clear(confirm="yes")
        self.assertEqual(set(payload), UNSUPPORTED_KEYS)
        self.assertFalse(payload["ok"])
        self.assertEqual(payload["status"], "unsupported")
        self.assertFalse(payload["mode04_positive"])
        self.assertIn("NOT", payload["reason"].upper() + "confirmed".upper(),
                      "the reason must say nothing was confirmed cleared")

    def test_unrecorded_mode04_is_silence_too(self):
        # The shipped round-1 capture never probed Mode 04: ReplayHost
        # answers [""] for it, which must degrade, never hang or 500.
        service = clear_service({"03": {"raw": ["43 00"]}})
        payload = service.clear(confirm="yes")
        self.assertEqual(payload["status"], "unsupported")

    def test_refusal_carries_the_nrc(self):
        service = clear_service({"03": {"raw": ["43 00"]},
                                 "04": {"raw": ["7F 04 11"]}})
        payload = service.clear(confirm="yes")
        self.assertEqual(set(payload), REFUSED_KEYS)
        self.assertFalse(payload["ok"])
        self.assertEqual(payload["status"], "refused")
        self.assertEqual(payload["nrc"], "0x11")
        self.assertTrue(payload["nrc_name"])
        self.assertIn("nothing was confirmed cleared", payload["reason"])

    def test_garbage_reply_is_a_502_not_success(self):
        # A stale echo of another service must never read as a clear.
        service = clear_service({"03": {"raw": ["43 00"]},
                                 "04": {"raw": ["41 00 BE 3E A8 13"]}})
        with self.assertRaises(server_mod.ServiceError) as ctx:
            service.clear(confirm="yes")
        self.assertEqual(ctx.exception.status_code, 502)
        self.assertIn("NOT", str(ctx.exception))


class TimeoutClearTests(unittest.TestCase):
    def test_silent_mode04_is_a_502(self):
        cfg = clear_config()
        host = ScriptedHost({"03": ["43 00"]})  # 04 unscripted -> silence
        link = lane_mod.DiagLink(host, cfg)
        service = server_mod.DiagService(cfg, host=host, link=link)
        with self.assertRaises(server_mod.ServiceError) as ctx:
            service.clear(confirm="yes")
        self.assertEqual(ctx.exception.status_code, 502)
        self.assertIn("NOT", str(ctx.exception))
        self.assertIn("04", host.sent)

    def test_dead_lane_aborts_before_sending_mode04(self):
        cfg = clear_config()
        host = ScriptedHost({})  # everything silent, incl. the pre-read
        link = lane_mod.DiagLink(host, cfg)
        service = server_mod.DiagService(cfg, host=host, link=link)
        with self.assertRaises(server_mod.ServiceError) as ctx:
            service.clear(confirm="yes")
        self.assertEqual(ctx.exception.status_code, 502)
        self.assertIn("nothing was sent", str(ctx.exception))
        self.assertEqual(host.sent, ["03"],
                         "never clear blind on a dead lane")


class SingleFlightTests(unittest.TestCase):
    def test_second_concurrent_clear_is_busy(self):
        service = clear_service({"03": {"raw": ["43 00"]},
                                 "04": {"raw": ["44"]}})
        link = BlockingLink()
        service.link = link
        thread = threading.Thread(
            target=service.clear, kwargs={"confirm": "yes"}, daemon=True)
        thread.start()
        self.assertTrue(link.entered_04.wait(5))
        try:
            with self.assertRaises(server_mod.Busy):
                service.clear(confirm="yes")
        finally:
            link.release_04.set()
            thread.join(5)

    def test_held_lock_is_busy_without_a_thread(self):
        service = clear_service({"04": {"raw": ["44"]}})
        service._clear_lock.acquire()
        try:
            with self.assertRaises(server_mod.Busy):
                service.clear(confirm="yes")
        finally:
            service._clear_lock.release()

    def test_clear_while_scanning_is_busy(self):
        service = clear_service({"04": {"raw": ["44"]}})

        class ScanningEngine:
            running = True

        service.engine = ScanningEngine()
        with self.assertRaises(server_mod.Busy):
            service.clear(confirm="yes")

    def test_scan_while_clearing_is_busy(self):
        service = clear_service({"04": {"raw": ["44"]}})
        service._clear_lock.acquire()
        try:
            with self.assertRaises(server_mod.Busy):
                service.scan()
        finally:
            service._clear_lock.release()


class RoutingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.service = clear_service({"03": {"raw": ["43 00"]},
                                     "04": {"raw": ["44"]}})

    def test_post_clear_without_confirm_is_a_400(self):
        with self.assertRaises(server_mod.BadRequest):
            self.service.handle("POST", "/clear", {})

    def test_post_clear_with_query_confirm(self):
        response = self.service.handle("POST", "/clear",
                                       {"confirm": ["yes"]})
        self.assertEqual(response.status, 200)
        self.assertTrue(json.loads(response.body)["ok"])

    def test_post_clear_with_body_confirm(self):
        response = self.service.handle("POST", "/clear", {},
                                       {"confirm": ["yes"]})
        self.assertEqual(response.status, 200)
        self.assertTrue(json.loads(response.body)["ok"])

    def test_diag_alias_routes_too(self):
        response = self.service.handle("POST", "/diag/clear",
                                       {"confirm": ["yes"]})
        self.assertEqual(response.status, 200)

    def test_get_clear_is_refused(self):
        with self.assertRaises(server_mod.ServiceError) as ctx:
            self.service.handle("GET", "/clear", {"confirm": ["yes"]})
        self.assertEqual(ctx.exception.status_code, 405)

    def test_post_scan_stays_forbidden(self):
        with self.assertRaises(server_mod.ServiceError):
            self.service.handle("POST", "/scan", {})

    def test_body_parsing_json_and_form(self):
        self.assertEqual(
            server_mod.parse_post_body(b'{"confirm": "yes"}',
                                       "application/json"),
            {"confirm": ["yes"]})
        self.assertEqual(
            server_mod.parse_post_body(b"confirm=yes",
                                       "application/x-www-form-urlencoded"),
            {"confirm": ["yes"]})
        self.assertEqual(server_mod.parse_post_body(b"", ""), {})
        # Junk parses to junk keys (or {}), never raises: an unreadable body
        # still fails at the confirm gate (400), never with a 500.
        self.assertNotIn("confirm",
                         server_mod.parse_post_body(b"\x00\x01", ""))


class InterpretTests(unittest.TestCase):
    """The Mode 04 classifier, straight on synthetic wire text."""

    def outcome(self, raw):
        return clear_mod.interpret_mode04(raw)["outcome"]

    def test_outcomes(self):
        self.assertEqual(self.outcome(["44"]), "positive")
        self.assertEqual(self.outcome([""]), "no_data")
        self.assertEqual(self.outcome(["NO DATA"]), "no_data")
        self.assertEqual(self.outcome(["7F 04 22"]), "negative")
        self.assertEqual(self.outcome(["04 44"]), "positive")
        self.assertEqual(self.outcome(["41 00 BE 3E A8 13"]), "unrecognised")

    def test_copy_rules(self):
        self.assertIn("cannot be cleared by any tool",
                      clear_mod.PERMANENT_CODES_NOTE)
        self.assertNotIn("disconnect the battery",
                         clear_mod.CONFIRM_REQUIRED_MESSAGE.lower(),
                         "the gate must never suggest the battery shortcut")
        self.assertIn("consequence list", clear_mod.CONFIRM_REQUIRED_MESSAGE)
        self.assertIn("fix", clear_mod.CONFIRM_REQUIRED_MESSAGE)

    def test_stored_code_count(self):
        one = protocol_mod.decode_raw_items("03", ["43 01 04 01"])
        self.assertEqual(clear_mod.count_stored_codes(one), 1)
        clean = protocol_mod.decode_raw_items("03", ["43 00"])
        self.assertEqual(clear_mod.count_stored_codes(clean), 0)
        silent = protocol_mod.decode_raw_items("03", [""])
        self.assertEqual(clear_mod.count_stored_codes(silent), 0)


class HttpClearTests(unittest.TestCase):
    """POST /clear over a real loopback socket, then shut down."""

    @classmethod
    def setUpClass(cls):
        cfg = clear_config()
        service = clear_service({"03": {"raw": ["43 00"]},
                                 "04": {"raw": ["44"]}}, cfg)
        cls.server, cls.service = server_mod.create_server(cfg,
                                                           service=service)
        cls.port = cls.server.server_address[1]
        cls.thread = threading.Thread(
            target=cls.server.serve_forever,
            kwargs={"poll_interval": 0.05}, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join(5)

    def post(self, path, body=None, content_type=None):
        url = "http://127.0.0.1:%d%s" % (self.port, path)
        headers = {}
        if content_type:
            headers["Content-Type"] = content_type
        request = urllib.request.Request(url, data=body, headers=headers,
                                         method="POST")
        try:
            with urllib.request.urlopen(request, timeout=30) as handle:
                return handle.status, handle.read()
        except urllib.error.HTTPError as exc:
            return exc.code, exc.read()

    def test_post_without_confirm_is_400(self):
        status, body = self.post("/clear")
        self.assertEqual(status, 400)
        self.assertIn("confirm=yes", body.decode("utf-8"))

    def test_post_with_json_confirm(self):
        status, body = self.post("/clear", b'{"confirm": "yes"}',
                                 "application/json")
        self.assertEqual(status, 200)
        payload = json.loads(body)
        self.assertEqual(set(payload), SUCCESS_KEYS)
        self.assertTrue(payload["mode04_positive"])

    def test_post_with_form_confirm(self):
        status, body = self.post(
            "/clear", b"confirm=yes",
            "application/x-www-form-urlencoded")
        self.assertEqual(status, 200)
        self.assertTrue(json.loads(body)["ok"])

    def test_post_with_query_confirm(self):
        status, body = self.post("/clear?confirm=yes")
        self.assertEqual(status, 200)
        self.assertTrue(json.loads(body)["ok"])


if __name__ == "__main__":
    unittest.main()
