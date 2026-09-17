"""Max-data pack tests (Phase 3a): bitmap-chain walks, all-PIDs read, capability.

Every payload here is either hand-built from the documented J1979 encodings
(bitmap_to_ids ground truth lives in test_diag_core.py) or the recorded
reference-car fixture - nothing is invented, and every unknown identifier
must surface raw rather than raise.
"""

from __future__ import annotations

import json
import os
import unittest

from backend import server as server_mod
from backend.diag import capability as capability_mod
from backend.diag import config as config_mod
from backend.diag import hosts as hosts_mod
from backend.diag import lane as lane_mod
from backend.diag import scan as scan_mod

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
ROUND1 = os.path.join(REPO, "fixtures", "round1_full_capture.json")
VIN = "WVWZZZ1KZAW555555"


def make_engine(fixture: dict):
    """A scan engine over an inline replay fixture, with pacing off."""
    cfg = config_mod.load_config()
    cfg.mode = config_mod.MODE_REPLAY
    cfg.query_spacing_s = 0.0
    cfg.vin_decode_enabled = False
    host = hosts_mod.ReplayHost(dict(fixture))
    link = lane_mod.DiagLink(host, cfg)
    return scan_mod.ScanEngine(link, cfg), host


class PidWalkTests(unittest.TestCase):
    # 0100 claims PIDs 01-08 + the 0x20 next-range bit; 0120 is empty.
    TWO_DEEP = {
        "0100": {"raw": ["4100FF000001"]},
        "0120": {"raw": ["412000000000"]},
    }
    # 0120 claims 0x40 as well, so the walk must continue to 0140 and stop
    # there (empty bitmap, next-range bit clear).
    THREE_DEEP = {
        "0100": {"raw": ["4100FF000001"]},
        "0120": {"raw": ["412000000001"]},
        "0140": {"raw": ["414000000000"]},
    }

    def test_walk_stops_where_the_chain_ends(self):
        engine, host = make_engine(self.TWO_DEEP)
        report = engine.run(sections="discovery")
        self.assertEqual(host.sent[:2], ["0100", "0120"])
        self.assertNotIn("0140", host.sent)
        self.assertNotIn("0160", host.sent)
        self.assertEqual(sorted(report["support"]["pids"]["0100"]),
                         [1, 2, 3, 4, 5, 6, 7, 8, 0x20])
        self.assertNotIn("0140", report["support"]["pids"])

    def test_walk_follows_every_claimed_range(self):
        engine, host = make_engine(self.THREE_DEEP)
        report = engine.run(sections="discovery")
        self.assertIn("0140", host.sent)
        self.assertNotIn("0160", host.sent)
        self.assertIn("0140", report["support"]["pids"])
        self.assertEqual(report["support"]["pids"]["0140"], [])

    def test_unanswered_range_stops_the_walk_without_an_abort(self):
        # 0120 is absent: ReplayHost answers "" (NO DATA), which ends the
        # chain as a negative result - not a timeout, not an abort.
        engine, host = make_engine({"0100": {"raw": ["4100FF000001"]}})
        report = engine.run(sections="discovery")
        self.assertIn("0120", host.sent)
        self.assertNotIn("0140", host.sent)
        self.assertFalse(report["scan"]["aborted"])
        # ... and the later discovery probes still ran.
        self.assertIn("0900", report["discovery"])
        self.assertIn("0200", report["discovery"])


class Mode06WalkTests(unittest.TestCase):
    # A five-page chain: each page advertises only the next page marker,
    # until 0680 advertises the (unknown) monitor 0x9A and stops.
    CHAIN = {
        "0600": {"raw": ["460000000001"]},
        "0620": {"raw": ["462000000001"]},
        "0640": {"raw": ["464000000001"]},
        "0660": {"raw": ["466000000001"]},
        "0680": {"raw": ["468000000040"]},
        "069A": {"raw": ["469AC530814A5C29D5C3"]},
    }

    def test_page_walk_reads_every_advertised_page_then_stops(self):
        engine, host = make_engine(self.CHAIN)
        report = engine.run(sections="discovery")
        for page in ("0600", "0620", "0640", "0660", "0680"):
            self.assertIn(page, report["discovery"], page)
        self.assertNotIn("06A0", host.sent)
        self.assertEqual(report["support"]["obdmid"]["0680"], [0x9A])

    def test_walk_can_be_pinned_to_the_first_page(self):
        engine, host = make_engine(self.CHAIN)
        engine.cfg.mode06_walk_ranges = False
        report = engine.run(sections="discovery")
        self.assertIn("0600", report["discovery"])
        self.assertNotIn("0620", report["discovery"])
        self.assertNotIn("0620", host.sent)

    def test_unlisted_but_answering_monitor_is_enumerated_raw(self):
        engine, _ = make_engine(self.CHAIN)
        report = engine.run(sections="discovery,mode06")
        block = next((b for b in report["monitor_tests"]
                      if b.get("obdmid") == 0x9A), None)
        assert block is not None, "advertised MID 0x9A must be queried"
        self.assertTrue(block["ok"])
        self.assertTrue(block["advertised"])
        self.assertIn("unknown", block["obdmid_name"])
        self.assertEqual([t["tid"] for t in block["tests"]], [0xC5])
        self.assertTrue(block["tests"][0]["raw_hex"])


class AllPidsTests(unittest.TestCase):
    FIXTURE = {
        "0100": {"raw": ["4100FF000001"]},
        "0120": {"raw": ["412000000000"]},
        "0104": {"raw": ["410480"]},   # engine load answers; the rest is NO DATA
    }

    def test_reads_every_advertised_pid_once_and_skips_bitmaps(self):
        engine, host = make_engine(self.FIXTURE)
        report = engine.run(sections="discovery,allpids")
        rows = report["allpids"]
        self.assertEqual([r["pid"] for r in rows],
                         [1, 2, 3, 4, 5, 6, 7, 8])
        data_queries = [c for c in host.sent if c.startswith("01")
                        and c not in ("0100", "0120")]
        self.assertEqual(sorted(data_queries),
                         ["010%d" % pid for pid in range(1, 9)])
        self.assertEqual(report["scan"]["allpids_rows"], 8)

    def test_rows_are_decoded_or_raw_but_never_invented(self):
        engine, _ = make_engine(self.FIXTURE)
        report = engine.run(sections="discovery,allpids")
        by_pid = {r["pid"]: r for r in report["allpids"]}
        load = by_pid[0x04]
        self.assertTrue(load["ok"])
        self.assertEqual(load["unit"], "%")
        self.assertAlmostEqual(load["value"], 0x80 * 100.0 / 255.0)
        unnamed = by_pid[0x08]
        self.assertIn("unknown", unnamed["name"])
        self.assertIn("0x08", unnamed["name"])
        missing = by_pid[0x01]
        self.assertFalse(missing["ok"])
        self.assertIsNone(missing["value"])

    def test_without_discovery_nothing_is_read_and_it_says_so(self):
        engine, host = make_engine(self.FIXTURE)
        report = engine.run(sections="allpids")
        self.assertEqual(report["allpids"], [])
        self.assertTrue(any("allpids" in note for note in report["notes"]))
        self.assertNotIn("0104", host.sent)


class CapabilityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        engine, _ = make_engine(_load_round1())
        cls.report = engine.run()

    def test_sheet_shape(self):
        cap = capability_mod.build_capability(
            self.report, app_version="0.1.0-test",
            data_source="replay", lane_mode="replay")
        self.assertEqual(cap["sheet"], "hudiy-diagnostics/capability")
        self.assertEqual(cap["app_version"], "0.1.0-test")
        self.assertEqual(cap["data_source"], "replay")
        self.assertTrue(cap["generated_at"])
        banks = {b["bank"]: b for b in cap["pid_support"]["banks"]}
        self.assertIn("0100", banks)
        self.assertGreater(cap["pid_support"]["total"], 0)
        for bank in cap["pid_support"]["banks"]:
            self.assertTrue(bank["bitmap_hex"])
            self.assertEqual(bank["count"], len(bank["pids"]))

    def test_mode06_and_mode_support_are_observed_not_assumed(self):
        cap = capability_mod.build_capability(self.report, data_source="replay")
        answered = [r["obdmid"] for r in cap["mode06"]["answered"]]
        self.assertIn(0x01, answered)
        self.assertIn(0x20, cap["mode06"]["advertised_mids"])
        self.assertEqual(cap["modes"]["02"]["state"], "not-supported")
        self.assertEqual(cap["modes"]["0A"]["state"], "not-supported")
        self.assertEqual(cap["modes"]["05"]["state"], "not-probed")
        self.assertEqual(cap["modes"]["09"]["state"], "answered")
        self.assertTrue(cap["readiness_seen"])

    def test_identity_only_carries_what_was_captured(self):
        cap = capability_mod.build_capability(self.report, data_source="replay")
        self.assertEqual(cap["identity"]["vin"], VIN)
        self.assertTrue(cap["identity"]["ecu_name"])

    def test_text_render_is_pasteable(self):
        cap = capability_mod.build_capability(
            self.report, app_version="0.1.0-test", data_source="replay",
            lane_mode="replay")
        text = capability_mod.render_text(cap)
        self.assertIn("COMPATIBILITY SHEET", text)
        self.assertIn(VIN, text)
        self.assertIn("0.1.0-test", text)
        self.assertIn("replay", text)

    def test_partial_scan_is_flagged_as_partial(self):
        engine, _ = make_engine(_load_round1())
        partial = engine.run(sections="dtc")
        cap = capability_mod.build_capability(partial, data_source="replay")
        self.assertFalse(cap["coverage"]["full"])
        self.assertEqual(cap["coverage"]["sections"], ["dtc"])
        self.assertEqual(cap["modes"]["01"]["state"], "not-probed")


def _load_round1() -> dict:
    with open(ROUND1, "r", encoding="utf-8") as handle:
        obj = json.load(handle)
    return {k: v for k, v in obj.items() if not k.startswith("probe")}


class CapabilityServerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from backend.diag import fixtures as fixtures_mod
        cfg = config_mod.load_config()
        cfg.mode = config_mod.MODE_REPLAY
        cfg.replay_fixture = ROUND1
        cfg.query_spacing_s = 0.0
        cfg.http_host = "127.0.0.1"
        cfg.http_port = 0
        cfg.vin_decode_enabled = False
        cls.service = server_mod.DiagService(cfg)
        cls.capture = fixtures_mod.load_fixture(ROUND1)

    def test_capability_json_route(self):
        response = self.service.handle("GET", "/capability", {})
        self.assertEqual(response.status, 200)
        payload = json.loads(response.body.decode("utf-8"))
        self.assertEqual(payload["sheet"], "hudiy-diagnostics/capability")
        self.assertEqual(payload["data_source"], "replay")
        self.assertGreater(payload["pid_support"]["total"], 0)
        self.assertEqual(payload["identity"]["vin"], VIN)

    def test_capability_text_route(self):
        response = self.service.handle(
            "GET", "/capability", {"format": ["text"]})
        self.assertEqual(response.status, 200)
        self.assertIn("text/plain", response.content_type)
        body = response.body.decode("utf-8")
        self.assertIn("COMPATIBILITY SHEET", body)
        self.assertIn(VIN, body)

    def test_diag_alias_and_bad_format(self):
        response = self.service.handle("GET", "/diag/capability", {})
        self.assertEqual(response.status, 200)
        with self.assertRaises(server_mod.BadRequest):
            self.service.handle("GET", "/capability", {"format": ["pdf"]})

    def test_index_lists_the_new_surface(self):
        endpoints = self.service.index()["endpoints"]
        self.assertIn("/capability", endpoints)
        self.assertIn("allpids", endpoints["/scan"])


if __name__ == "__main__":
    unittest.main()
