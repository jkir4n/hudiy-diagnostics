"""Tests for `merge_config.py --remove` (uninstall reverse-merge).

Run:  python3 -m unittest discover -s backend -t .

The remove mode must drop exactly our entries (overlay `identifier == "diag"`,
the menu fragment's `action`) and leave every other entry deep-equal: absent
file/entry is a no-op (no write, no backup), malformed or wrong-shaped files
are refused (SystemExit, nothing written), dry-run writes nothing, and
merge -> remove round-trips the other content back to identical.
"""

from __future__ import annotations

import glob
import importlib.util
import json
import os
import shutil
import tempfile
import unittest

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
FRONTEND = os.path.join(REPO, "frontend")


def load_merge_config():
    path = os.path.join(FRONTEND, "hudiy", "merge_config.py")
    spec = importlib.util.spec_from_file_location("diag_merge_config_remove", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


RACE_OVERLAY = {"identifier": "race_dash", "url": "http://127.0.0.1:44411/",
                "action": "", "visibleOnActions": []}
#: A decoy whose name starts like ours - exact match must spare it.
DECOY_OVERLAY = {"identifier": "diag-legacy", "url": "http://127.0.0.1:44414/",
                 "action": "", "visibleOnActions": []}
RACE_ITEM = {"categories": ["Hudiy"], "label": "Race Dash",
             "action": "race_dash_show"}
#: A decoy whose action starts like ours - exact match must spare it.
DECOY_ITEM = {"categories": ["Hudiy"], "label": "Diagnostics verbose",
              "action": "diag_show_verbose"}


class RemoveTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.mod = load_merge_config()
        with open(os.path.join(FRONTEND, "hudiy", "overlays.json"),
                  "r", encoding="utf-8") as handle:
            cls.diag_overlay = json.load(handle)
        with open(os.path.join(FRONTEND, "hudiy", "applications_menu.json"),
                  "r", encoding="utf-8") as handle:
            cls.diag_item = json.load(handle)

    def setUp(self):
        self.cfg = tempfile.mkdtemp(prefix="diag-merge-remove-")
        self.addCleanup(shutil.rmtree, self.cfg, True)
        self.overlays_path = os.path.join(self.cfg, "overlays.json")
        self.menu_path = os.path.join(self.cfg, "applications_menu.json")

    # -- helpers ---------------------------------------------------------
    def write(self, name, payload, encoding="utf-8"):
        with open(os.path.join(self.cfg, name), "w",
                  encoding=encoding) as handle:
            json.dump(payload, handle)

    def write_raw(self, name, text, encoding="utf-8"):
        with open(os.path.join(self.cfg, name), "w",
                  encoding=encoding) as handle:
            handle.write(text)

    def read(self, name):
        with open(os.path.join(self.cfg, name), "r",
                  encoding="utf-8-sig") as handle:
            return json.load(handle)

    def raw_bytes(self, name):
        with open(os.path.join(self.cfg, name), "rb") as handle:
            return handle.read()

    def backups(self):
        return glob.glob(os.path.join(self.cfg, "*.bak-*"))

    def tmps(self):
        return glob.glob(os.path.join(self.cfg, "*.tmp"))

    def seed_full(self):
        """A live config with ours + race-dash + similar-name decoys."""
        self.write("overlays.json", {
            "overlays": [RACE_OVERLAY, self.diag_overlay, DECOY_OVERLAY],
            "xStep": 20,
        })
        self.write("applications_menu.json", {
            "items": [RACE_ITEM, self.diag_item, DECOY_ITEM],
        })

    # -- the point of the card -------------------------------------------
    def test_removes_only_ours_among_multiple_entries(self):
        self.seed_full()
        self.assertEqual(self.mod.main([self.cfg, "--remove"]), 0)
        ids = [item["identifier"]
               for item in self.read("overlays.json")["overlays"]]
        self.assertEqual(ids, ["race_dash", "diag-legacy"])
        actions = [item["action"]
                   for item in self.read("applications_menu.json")["items"]]
        self.assertEqual(actions, ["race_dash_show", "diag_show_verbose"])

    def test_other_entries_preserved_deep_equal(self):
        self.seed_full()
        self.mod.main([self.cfg, "--remove"])
        doc = self.read("overlays.json")
        self.assertEqual(doc["overlays"], [RACE_OVERLAY, DECOY_OVERLAY])
        self.assertEqual(doc["xStep"], 20, "unrelated keys must survive")
        menu = self.read("applications_menu.json")
        self.assertEqual(menu["items"], [RACE_ITEM, DECOY_ITEM])

    def test_absent_entry_is_noop_without_write_or_backup(self):
        self.write("overlays.json", {"overlays": [RACE_OVERLAY], "xStep": 20})
        self.write("applications_menu.json", {"items": [RACE_ITEM]})
        before_overlays = self.raw_bytes("overlays.json")
        before_menu = self.raw_bytes("applications_menu.json")
        self.assertEqual(self.mod.main([self.cfg, "--remove"]), 0)
        self.assertEqual(self.raw_bytes("overlays.json"), before_overlays)
        self.assertEqual(self.raw_bytes("applications_menu.json"), before_menu)
        self.assertEqual(self.backups(), [])

    def test_absent_files_are_noop_and_create_nothing(self):
        self.assertEqual(self.mod.main([self.cfg, "--remove"]), 0)
        self.assertEqual(os.listdir(self.cfg), [])

    def test_missing_config_dir_is_not_an_error(self):
        missing = os.path.join(self.cfg, "nope")
        self.assertEqual(self.mod.main([missing, "--remove"]), 0)
        self.assertFalse(os.path.exists(missing), "must not create the layout")

    def test_malformed_json_refuses_without_writing(self):
        self.write_raw("overlays.json", "{ not json {{{")
        self.write("applications_menu.json", {"items": [RACE_ITEM]})
        before = self.raw_bytes("overlays.json")
        with self.assertRaises(SystemExit):
            self.mod.main([self.cfg, "--remove"])
        self.assertEqual(self.raw_bytes("overlays.json"), before)
        self.assertEqual(self.backups(), [])
        self.assertEqual(self.tmps(), [])

    def test_malformed_menu_refuses_without_writing(self):
        self.write("overlays.json", {"overlays": [RACE_OVERLAY]})
        self.write_raw("applications_menu.json", "[1, 2,")
        before = self.raw_bytes("applications_menu.json")
        with self.assertRaises(SystemExit):
            self.mod.main([self.cfg, "--remove"])
        self.assertEqual(self.raw_bytes("applications_menu.json"), before)

    def test_wrong_shape_refuses_without_writing(self):
        for name, payload in (("overlays.json", {"overlays": "not-a-list"}),
                              ("overlays.json", ["a-list-not-an-object"]),
                              ("overlays.json", "just-a-string")):
            with self.subTest(name=name, payload=payload):
                self.write(name, payload)
                before = self.raw_bytes(name)
                with self.assertRaises(SystemExit):
                    self.mod.main([self.cfg, "--remove"])
                self.assertEqual(self.raw_bytes(name), before)
                self.assertEqual(self.backups(), [])
                os.remove(os.path.join(self.cfg, name))
        for payload in ({"items": "not-a-list"}, "just-a-string", 42):
            with self.subTest(payload=payload):
                self.write("applications_menu.json", payload)
                before = self.raw_bytes("applications_menu.json")
                with self.assertRaises(SystemExit):
                    self.mod.main([self.cfg, "--remove"])
                self.assertEqual(self.raw_bytes("applications_menu.json"),
                                 before)
                os.remove(self.menu_path)

    def test_bom_tolerated(self):
        self.write_raw(
            "overlays.json",
            "\ufeff" + json.dumps({"overlays": [RACE_OVERLAY,
                                                self.diag_overlay]}),
            encoding="utf-8")
        self.write("applications_menu.json",
                   {"items": [RACE_ITEM, self.diag_item]})
        self.assertEqual(self.mod.main([self.cfg, "--remove"]), 0)
        self.assertEqual([item["identifier"]
                          for item in self.read("overlays.json")["overlays"]],
                         ["race_dash"])

    def test_dry_run_writes_nothing(self):
        self.seed_full()
        before_overlays = self.raw_bytes("overlays.json")
        before_menu = self.raw_bytes("applications_menu.json")
        self.assertEqual(self.mod.main([self.cfg, "--remove", "--dry-run"]), 0)
        self.assertEqual(self.raw_bytes("overlays.json"), before_overlays)
        self.assertEqual(self.raw_bytes("applications_menu.json"), before_menu)
        self.assertEqual(self.backups(), [])
        self.assertEqual(self.tmps(), [])

    def test_no_tmp_left_behind_after_real_remove(self):
        self.seed_full()
        self.mod.main([self.cfg, "--remove"])
        self.assertEqual(self.tmps(), [])

    def test_idempotent_double_run(self):
        self.seed_full()
        self.mod.main([self.cfg, "--remove"])
        backups_first = sorted(self.backups())
        self.assertEqual(len(backups_first), 2)
        after_first = (self.raw_bytes("overlays.json"),
                       self.raw_bytes("applications_menu.json"))
        self.assertEqual(self.mod.main([self.cfg, "--remove"]), 0)
        self.assertEqual(sorted(self.backups()), backups_first,
                         "second run must take no new backup")
        self.assertEqual((self.raw_bytes("overlays.json"),
                          self.raw_bytes("applications_menu.json")),
                         after_first)

    def test_merge_remove_round_trip_preserves_other_content(self):
        self.write("overlays.json", {
            "overlays": [RACE_OVERLAY, DECOY_OVERLAY],
            "xStep": 20,
            "navigationOverlayVisibility": "NONE",
        })
        self.write("applications_menu.json", {"items": [RACE_ITEM, DECOY_ITEM]})
        with open(self.overlays_path, "r", encoding="utf-8") as handle:
            pre_overlays = json.load(handle)
        with open(self.menu_path, "r", encoding="utf-8") as handle:
            pre_menu = json.load(handle)
        self.mod.main([self.cfg, "--port", "44414"])
        self.mod.main([self.cfg, "--remove"])
        self.assertEqual(self.read("overlays.json"), pre_overlays)
        self.assertEqual(self.read("applications_menu.json"), pre_menu)

    def test_list_form_menu_is_handled(self):
        # merge() normalises a top-level list into {"items": [...]}; remove
        # must accept the same shape instead of refusing it.
        self.write_raw("applications_menu.json",
                       json.dumps([RACE_ITEM, self.diag_item]))
        self.write("overlays.json", {"overlays": [RACE_OVERLAY]})
        self.assertEqual(self.mod.main([self.cfg, "--remove"]), 0)
        self.assertEqual(self.read("applications_menu.json")["items"],
                         [RACE_ITEM])


if __name__ == "__main__":
    unittest.main()
