"""Unit tests for the wheel/key input adapter (tools/keyboard_shim.py).

Pure-logic tests: the translation table and the discovery scoring decide the
adapter's behavior; reading real devices and the CDP dispatch need hardware
and are covered by `--scan` output plus field verification on the head unit.
"""
import importlib.util
import os
import unittest

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
spec = importlib.util.spec_from_file_location(
    "keyboard_shim", os.path.join(REPO, "tools", "keyboard_shim.py"))
shim = importlib.util.module_from_spec(spec)
spec.loader.exec_module(shim)

EV_KEY, EV_REL = 0x01, 0x02


class ClassifyTests(unittest.TestCase):
    """Kernel events -> page steps, following Hudiy's key scheme."""

    def test_rotary_pair_is_hudiy_scroll_left_right(self):
        # Hudiy's README binds keyboard `1`/`2` to scroll left/right; the
        # reference knob emits the same two keys as kernel KEY_1/KEY_2.
        self.assertEqual(shim.classify(EV_KEY, 2, 1), "prev")
        self.assertEqual(shim.classify(EV_KEY, 3, 1), "next")

    def test_trigger_and_back(self):
        self.assertEqual(shim.classify(EV_KEY, 28, 1), "activate")   # ENTER
        self.assertEqual(shim.classify(EV_KEY, 96, 1), "activate")   # KPENTER
        self.assertEqual(shim.classify(EV_KEY, 1, 1), "back")        # ESC
        self.assertEqual(shim.classify(EV_KEY, 158, 1), "back")      # BACK

    def test_arrows_walk_the_same_list(self):
        for code, step in ((103, "prev"), (105, "prev"), (108, "next"), (106, "next")):
            self.assertEqual(shim.classify(EV_KEY, code, 1), step)

    def test_scroll_codes_and_wheel_ticks(self):
        self.assertEqual(shim.classify(EV_KEY, 177, 1), "prev")      # SCROLLUP
        self.assertEqual(shim.classify(EV_KEY, 178, 1), "next")      # SCROLLDOWN
        self.assertEqual(shim.classify(EV_REL, 8, 1), "next")        # REL_WHEEL
        self.assertEqual(shim.classify(EV_REL, 8, -1), "prev")
        self.assertEqual(shim.classify(EV_REL, 10, 1), "next")       # REL_HWHEEL

    def test_releases_repeats_and_others_are_ignored(self):
        self.assertIsNone(shim.classify(EV_KEY, 2, 0))     # release edge
        self.assertIsNone(shim.classify(EV_KEY, 2, 2))     # autorepeat
        self.assertIsNone(shim.classify(EV_KEY, 30, 1))    # KEY_A
        self.assertIsNone(shim.classify(0x03, 0, 5))       # EV_ABS

    def test_reference_knob_subset_is_covered(self):
        for code in (1, 2, 3, 28):  # KEY_ESC, KEY_1, KEY_2, KEY_ENTER
            self.assertIn(code, shim.KEY_STEPS)


class DeviceScoreTests(unittest.TestCase):
    """Discovery heuristics: pick a knob, never a pointer."""

    def test_touchscreen_and_dead_devices_are_not_usable(self):
        self.assertEqual(shim.device_score("Goodix Capacitive TouchScreen", [], False), 0)
        self.assertEqual(shim.device_score("Whatever", [], False), 0)

    def test_knob_beats_keyboard_beats_nothing(self):
        knob = shim.device_score("USB Composite Device", [1, 2, 3, 28], False)
        kbd = shim.device_score("USB keyboard", [1, 28, 103, 108], False)
        self.assertGreater(knob, kbd)
        self.assertGreater(kbd, 0)

    def test_name_hint_wins(self):
        hinted = shim.device_score("Rotary Encoder v2", [2, 3], False)
        plain = shim.device_score("USB Composite Device", [2, 3], False)
        self.assertGreater(hinted, plain)

    def test_mice_are_downranked_to_zero(self):
        self.assertEqual(shim.device_score("Logitech USB Mouse", [], True), 0)
        self.assertGreater(shim.device_score("Desk Wheel", [], True), 0)

    def test_match_env_override(self):
        before = shim.device_score("Bizarre Widget", [2, 3], False)
        os.environ["DIAG_SHIM_MATCH"] = "bizarre"
        try:
            after = shim.device_score("Bizarre Widget", [2, 3], False)
        finally:
            os.environ.pop("DIAG_SHIM_MATCH", None)
        self.assertEqual(after - before, 100)


class DrainTests(unittest.TestCase):
    """Hidden-time knob events must be discarded, never replayed.

    Live regression (16 Sep 2026): the fd accumulated Hudiy-menu navigation
    while the overlay was hidden and replayed it into the page on the next
    show (focus cycled, scans self-started, the page exited). _drain_ready is
    the discard path; these tests pin its behavior using a plain pipe.
    """

    @staticmethod
    def _frame(ev_type, code, val):
        import struct
        return struct.pack(shim.FRAME_FMT, 0, 0, ev_type, code, val)

    def test_drain_discards_queued_nav_presses(self):
        fd_r, fd_w = os.pipe()
        try:
            os.write(fd_w, self._frame(EV_KEY, 2, 1))    # KEY_1 press
            os.write(fd_w, self._frame(EV_KEY, 2, 0))    # release - not a step
            os.write(fd_w, self._frame(EV_KEY, 3, 1))    # KEY_2 press
            os.write(fd_w, self._frame(EV_KEY, 28, 1))   # ENTER press
            self.assertEqual(shim._drain_ready(fd_r), 3)
            self.assertEqual(shim._drain_ready(fd_r), 0)  # queue now empty
        finally:
            os.close(fd_r)
            os.close(fd_w)

    def test_drain_on_empty_queue_is_a_noop(self):
        fd_r, fd_w = os.pipe()
        try:
            self.assertEqual(shim._drain_ready(fd_r), 0)
        finally:
            os.close(fd_r)
            os.close(fd_w)


if __name__ == "__main__":
    unittest.main()
