"""Diagnostics lane tests - stdlib only (no pytest on this host).

Every payload here is copied verbatim from ``fixtures/``; nothing is invented.
Expected values are the ones recorded in ``docs/DECODED_FIXTURES.md`` and
``fixtures/*_decoded.json`` during Phase 1 probing of the reference car.

Run:  python3 -m unittest discover -s backend -t .
"""

from __future__ import annotations

import unittest

from backend.diag import decoders, framing, protocol

# --- verbatim wire captures (glued "<n>:" counters) -----------------------
RAW_VIN = "0:4902015756571:5A5A5A314B5A412:57353535353535"
RAW_CALID = "0:490A0145434D1:002D456E67696E2:65436F6E74726F3:6C0000AAAAAAAA"
RAW_CVN = "0:49040130305A1:3030303030305A2:202030303030AA"
RAW_M0601 = "0:4601C530814A1:5C29D5C3AAAAAA"
RAW_M0631 = "0:4631C082FFF31:FFA600A0AAAAAA"
RAW_M0685 = "0:4685C1FC018C1:80000FA085C2FC2:FA4DF4487FFFAA"
RAW_MID_MAP_MISLEADING = "0:460080000001"  # claims only OBDMID 0x21
RAW_SUPPORT_0100 = "0:4100BE3FA813"
RAW_SUPPORT_0140 = "4140CCD20000"  # docs: 41,42,45,46,49,4A,4C,4F
RAW_NO_DATA = ""
RAW_UNABLE = "UNABLE TO CONNECT"


class FramingTests(unittest.TestCase):
    def test_glued_counter_frames_split_without_losing_nibbles(self):
        payload = framing.parse_payload([RAW_VIN])
        self.assertEqual(payload.style, framing.STYLE_COUNTER)
        self.assertEqual(payload.problems, [])
        self.assertEqual(payload.frames,
                         ["490201575657", "5A5A5A314B5A41", "57353535353535"])
        # 3 frames of 6/7/7 bytes; reassembled length is 20 bytes.
        self.assertEqual(len(payload.data), 20)

    def test_multi_digit_counters_do_not_collide(self):
        # Counter 1 must not be found inside the "11:" separator.
        chunks = ["41" * 6] * 11
        text = "".join("%d:%s" % (i, c) for i, c in enumerate(chunks))
        payload = framing.parse_payload([text])
        self.assertEqual(payload.frames, chunks)
        self.assertEqual(payload.problems, [])

    def test_single_frame_payload(self):
        payload = framing.parse_payload(["0:4100BE3FA813"])
        self.assertEqual(payload.frames, ["4100BE3FA813"])
        self.assertEqual(payload.data.hex().upper(), "4100BE3FA813")

    def test_no_data_is_empty_not_error(self):
        payload = framing.parse_payload([RAW_NO_DATA])
        self.assertEqual(payload.style, framing.STYLE_EMPTY)
        self.assertEqual(payload.frames, [])
        self.assertEqual(payload.problems, [])

    def test_unparsable_text_is_flagged_never_guessed(self):
        payload = framing.parse_payload([RAW_UNABLE])
        self.assertNotEqual(payload.style, framing.STYLE_COUNTER)
        self.assertEqual(payload.frames, [])
        self.assertTrue(payload.problems or payload.non_data)

    def test_odd_length_hex_is_rejected(self):
        payload = framing.parse_payload(["4100BE3FA81"])
        self.assertEqual(payload.frames, [])
        self.assertTrue(payload.problems)


class ProtocolTests(unittest.TestCase):
    def test_vin_correlation(self):
        decoded = protocol.decode_raw_items("0902", [RAW_VIN])
        self.assertEqual(decoded.status, "ok")
        self.assertEqual(decoded.sid, 0x49)
        self.assertEqual(decoded.pid, 0x02)

    def test_no_data_status(self):
        decoded = protocol.decode_raw_items("0A", [RAW_NO_DATA])
        self.assertEqual(decoded.status, "no_data")
        self.assertFalse(decoded.ok)

    def test_command_normalisation_ignores_case_and_space(self):
        self.assertEqual(protocol.normalize_command(" 0100 "), "0100")


class DecoderTests(unittest.TestCase):
    def test_vin(self):
        decoded = protocol.decode_raw_items("0902", [RAW_VIN])
        info = decoders.vehicle_info(decoded)
        self.assertTrue(info["ok"])
        self.assertEqual(info["value"], "WVWZZZ1KZAW555555")
        self.assertTrue(info["detail"]["valid_length"])

    def test_calibration_id(self):
        decoded = protocol.decode_raw_items("090A", [RAW_CALID])
        info = decoders.vehicle_info(decoded)
        self.assertEqual(info["value"], "ECM-EngineControl")

    def test_cvn(self):
        decoded = protocol.decode_raw_items("0904", [RAW_CVN])
        info = decoders.vehicle_info(decoded)
        self.assertEqual(info["value"], "00Z000000Z  0000")

    def test_supported_pids_0100_matches_recorded_ground_truth(self):
        # 0xBE3FA813 -> first bit set is the 0x01 slot, never 0x00.
        decoded = protocol.decode_raw_items("0100", [RAW_SUPPORT_0100])
        result = decoders.supported_pids(decoded)
        self.assertTrue(result["ok"])
        self.assertNotIn(0, result["pids"])
        self.assertIn(1, result["pids"])
        self.assertIn(0x0C, result["pids"])       # engine RPM
        self.assertEqual(result["next_range"], 0x20)

    def test_supported_pids_0140_matches_documented_set(self):
        decoded = protocol.decode_raw_items("0140", [RAW_SUPPORT_0140])
        result = decoders.supported_pids(decoded)
        self.assertEqual(result["pids"],
                         [0x41, 0x42, 0x45, 0x46, 0x49, 0x4A, 0x4C, 0x4F])

    def test_mode06_monitor_tests(self):
        # Record layout: TID | UAS | value | min | max, so C5 30 814A 5C29 D5C3.
        decoded = protocol.decode_raw_items("0601", [RAW_M0601])
        result = decoders.monitor_tests(decoded, obdmid=0x01)
        self.assertTrue(result["ok"])
        self.assertEqual(result["obdmid"], 0x01)
        test = result["tests"][0]
        self.assertEqual(test["tid"], 0xC5)
        self.assertEqual(test["uas"], 0x30)
        self.assertEqual(test["value_raw"], 0x814A)
        self.assertEqual(test["min_raw"], 0x5C29)
        self.assertEqual(test["max_raw"], 0xD5C3)

    def test_mode06_multi_frame_mid_685(self):
        # 0685 reassembles to 20 bytes; after the SID+OBDMID header 18 bytes of
        # data remain:
        #   C1 FC 018C 8000 0FA0 | 85 C2 FCFA 4DF4 487F | FF AA (tail padding)
        # Two complete 8-byte groups under the documented layout (research doc
        # 1.7), so the TIDs are 0xC1 and 0x85. The ECU's FF AA tail is surfaced
        # as residual rather than silently dropped.
        decoded = protocol.decode_raw_items("0685", [RAW_M0685])
        result = decoders.monitor_tests(decoded, obdmid=0x85)
        self.assertTrue(result["ok"])
        self.assertEqual([t["tid"] for t in result["tests"]], [0xC1, 0x85])
        second = result["tests"][1]
        self.assertEqual(second["uas"], 0xC2)
        self.assertEqual(second["value_raw"], 0xFCFA)
        self.assertEqual(second["min_raw"], 0x4DF4)
        self.assertEqual(second["max_raw"], 0x487F)
        self.assertEqual(result["residual_hex"], "FFAA")

    def test_mode06_ambiguous_layout_is_reported_not_judged(self):
        # The reference car gives min > max on 0x85 (Phase-1 ambiguity). The
        # decoder must flag it and keep the raw bytes instead of inventing a
        # pass/fail verdict or a different byte alignment.
        decoded = protocol.decode_raw_items("0685", [RAW_M0685])
        result = decoders.monitor_tests(decoded, obdmid=0x85)
        self.assertTrue(result["layout_ambiguous"])
        self.assertTrue(result["parse_note"])
        for test in result["tests"]:
            self.assertIsNone(test["within_limits"])
            self.assertTrue(test["raw_hex"])
        # ...and the same data is still reported as *present* (supported), so the
        # UI greys it out rather than calling it a fault.
        self.assertTrue(result["supported"])

    def test_empty_dtc_response_is_good_news(self):
        decoded = protocol.decode_raw_items("07", ["0:4700"])
        result = decoders.dtc_list(decoded, mode=7)
        self.assertTrue(result["ok"])
        self.assertEqual(result["codes"], [])
        self.assertEqual(result["count_hex"], "00")

    def test_unsupported_mode_0a_is_a_support_fact(self):
        decoded = protocol.decode_raw_items("0A", [RAW_NO_DATA])
        result = decoders.dtc_list(decoded, mode=10)
        self.assertFalse(result["ok"])
        self.assertEqual(result["status"], "no_data")
        self.assertEqual(result["codes"], [])

    def test_unknown_identifier_never_raises(self):
        from backend.diag import names
        self.assertIn("unknown", names.pid_name(0xFE))
        self.assertIn("unknown", names.obdmid_name(0xFE))


if __name__ == "__main__":
    unittest.main()
