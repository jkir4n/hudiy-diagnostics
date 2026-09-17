"""End-to-end install/uninstall tests: `install.sh` for REAL in a temp HOME.

Run:  python3 -m unittest discover -s backend -t .
(Also runs under pytest - the cases are plain `unittest.TestCase`.)

No car, no Pi, no root: a fake `systemctl` on PATH records its calls (the
user-bus probe answers 0), HOME/XDG point into a temp dir, the Hudiy config
layout is a temp dir (DIAG_HUDIY_CONFIG_DIR), and a stub HTTP server answers
the installer's closing /health poll. Desk-based by design (car off).
"""

from __future__ import annotations

import hashlib
import http.server
import json
import os
import shutil
import stat
import subprocess
import tempfile
import threading
import unittest

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
INSTALL_SH = os.path.join(REPO, "backend", "deploy", "install.sh")
MERGE_PY = os.path.join(REPO, "frontend", "hudiy", "merge_config.py")

FAKE_SYSTEMCTL = """#!/usr/bin/env bash
# Fake user-bus systemctl: record every call, probe always answers 0.
echo "$@" >> "$SYSTEMCTL_LOG"
exit 0
"""

RACE_OVERLAY = {"identifier": "race_dash", "url": "http://127.0.0.1:44411/"}
RACE_ITEM = {"categories": ["Hudiy"], "label": "Race Dash",
             "action": "race_dash_show"}
DECOY_OVERLAY = {"identifier": "diag-legacy",
                 "url": "http://127.0.0.1:44414/"}
DECOY_ITEM = {"categories": ["Hudiy"], "label": "Diagnostics verbose",
              "action": "diag_show_verbose"}


class HealthStub:
    """Minimal stub answering the installer's closing /health poll."""

    def __init__(self):
        outer = self

        class Handler(http.server.BaseHTTPRequestHandler):
            def do_GET(self):  # noqa: N802 (stdlib handler name)
                if self.path == "/health":
                    body = b'{"ok": true}'
                    self.send_response(200)
                    self.send_header("Content-Type", "application/json")
                    self.send_header("Content-Length", str(len(body)))
                    self.end_headers()
                    self.wfile.write(body)
                else:
                    self.send_response(404)
                    self.end_headers()

            def log_message(self, *args):
                pass

        self.server = http.server.ThreadingHTTPServer(("127.0.0.1", 0),
                                                      Handler)
        self.port = self.server.server_address[1]
        self.thread = threading.Thread(target=self.server.serve_forever,
                                       daemon=True)
        outer.thread = self.thread

    def __enter__(self):
        self.thread.start()
        return self

    def __exit__(self, *exc):
        self.server.shutdown()
        self.thread.join(timeout=10)
        self.server.server_close()


class InstallUninstallTests(unittest.TestCase):
    maxDiff = 4096

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="diag-install-test-")
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.home = os.path.join(self.tmp, "home")
        os.makedirs(self.home)
        self.bindir = os.path.join(self.tmp, "bin")
        os.makedirs(self.bindir)
        self.systemctl_log = os.path.join(self.tmp, "systemctl.log")
        open(self.systemctl_log, "w").close()
        fake = os.path.join(self.bindir, "systemctl")
        with open(fake, "w", encoding="utf-8") as handle:
            handle.write(FAKE_SYSTEMCTL)
        os.chmod(fake, os.stat(fake).st_mode | stat.S_IXUSR | stat.S_IXGRP
                 | stat.S_IXOTH)
        self.hconfig = os.path.join(self.tmp, "hconfig")
        os.makedirs(self.hconfig)

        self.env = dict(os.environ)
        self.env["HOME"] = self.home
        self.env.pop("XDG_CONFIG_HOME", None)
        self.env.pop("XDG_RUNTIME_DIR", None)
        self.env.pop("DIAG_INSTALL_DIR", None)
        self.env["DIAG_HUDIY_CONFIG_DIR"] = self.hconfig
        self.env["DIAG_HTTP_PORT"] = "44419"
        self.env["SYSTEMCTL_LOG"] = self.systemctl_log
        self.env["PATH"] = self.bindir + os.pathsep + os.environ.get("PATH", "")
        if not self.env.get("USER"):
            import getpass
            self.env["USER"] = getpass.getuser()

        self.unit_dir = os.path.join(self.home, ".config", "systemd", "user")
        self.install_dir = os.path.join(self.home, ".local", "share",
                                        "hudiy-diagnostics")
        self.env_dir = os.path.join(self.home, ".config", "hudiy-diagnostics")

    # -- helpers ---------------------------------------------------------
    def run_install(self, *args):
        return subprocess.run(["bash", INSTALL_SH] + list(args),
                              env=self.env, capture_output=True, text=True,
                              timeout=120)

    def systemctl_calls(self):
        with open(self.systemctl_log, "r", encoding="utf-8") as handle:
            return [line.strip() for line in handle if line.strip()]

    def write_json(self, path, payload):
        with open(path, "w", encoding="utf-8") as handle:
            json.dump(payload, handle)

    def read_json(self, path):
        with open(path, "r", encoding="utf-8") as handle:
            return json.load(handle)

    def merge_ours(self):
        subprocess.run(["python3", MERGE_PY, self.hconfig, "--port", "44419"],
                       env=self.env, capture_output=True, text=True,
                       timeout=60, check=True)

    def seed_config(self, with_ours=True):
        overlays = [dict(RACE_OVERLAY), dict(DECOY_OVERLAY)]
        items = [dict(RACE_ITEM), dict(DECOY_ITEM)]
        self.write_json(os.path.join(self.hconfig, "overlays.json"),
                        {"overlays": overlays, "xStep": 20})
        self.write_json(os.path.join(self.hconfig, "applications_menu.json"),
                        {"items": items})
        if with_ours:
            self.merge_ours()

    def seed_installed_tree(self):
        os.makedirs(os.path.join(self.install_dir, "backend"), exist_ok=True)
        os.makedirs(os.path.join(self.install_dir, "frontend"), exist_ok=True)
        with open(os.path.join(self.install_dir, "backend", "server.py"),
                  "w", encoding="utf-8") as handle:
            handle.write("# seeded diagnostics tree\n")
        with open(os.path.join(self.install_dir, "frontend", "diag.html"),
                  "w", encoding="utf-8") as handle:
            handle.write("<!-- seeded diagnostics tree -->\n")

    def seed_units(self):
        os.makedirs(self.unit_dir, exist_ok=True)
        for name in ("hudiy-diagnostics.service", "hudiy-diag-keys.service"):
            with open(os.path.join(self.unit_dir, name), "w",
                      encoding="utf-8") as handle:
                handle.write("# seeded unit\n")

    def seed_env(self):
        os.makedirs(self.env_dir, exist_ok=True)
        with open(os.path.join(self.env_dir, "env"), "w",
                  encoding="utf-8") as handle:
            handle.write("DIAG_MODE=standalone\n")

    def seed_full_install(self, with_ours=True):
        self.seed_units()
        self.seed_installed_tree()
        self.seed_env()
        self.seed_config(with_ours=with_ours)

    def tree_hash(self):
        """Full before/after fingerprint of the sandbox (minus the call log)."""
        digest = hashlib.sha256()
        for root, dirs, files in os.walk(self.tmp):
            dirs.sort()
            if os.path.abspath(root) == os.path.abspath(self.bindir):
                dirs[:] = []
                continue
            for name in sorted(files):
                path = os.path.join(root, name)
                if os.path.abspath(path) == os.path.abspath(
                        self.systemctl_log):
                    continue
                digest.update(os.path.relpath(path, self.tmp).encode())
                with open(path, "rb") as handle:
                    digest.update(handle.read())
        return digest.hexdigest()

    def overlay_ids(self):
        return [item["identifier"] for item in
                self.read_json(os.path.join(self.hconfig,
                                            "overlays.json"))["overlays"]]

    def menu_actions(self):
        return [item["action"] for item in
                self.read_json(os.path.join(
                    self.hconfig, "applications_menu.json"))["items"]]

    # -- the uninstall contract ------------------------------------------
    def test_full_uninstall_removes_everything_but_decoys(self):
        self.seed_full_install()
        proc = self.run_install("--uninstall", "--no-reboot")
        self.assertEqual(proc.returncode, 0, proc.stderr + proc.stdout)
        self.assertFalse(os.path.exists(
            os.path.join(self.unit_dir, "hudiy-diagnostics.service")))
        self.assertFalse(os.path.exists(
            os.path.join(self.unit_dir, "hudiy-diag-keys.service")))
        self.assertFalse(os.path.exists(self.install_dir))
        self.assertFalse(os.path.exists(os.path.join(self.env_dir, "env")))
        self.assertFalse(os.path.exists(self.env_dir))
        self.assertNotIn("diag", self.overlay_ids())
        self.assertNotIn("diag_show", self.menu_actions())
        # Decoys and fellow travellers survive, deep-equal.
        self.assertEqual(self.overlay_ids(), ["race_dash", "diag-legacy"])
        self.assertEqual(self.menu_actions(),
                         ["race_dash_show", "diag_show_verbose"])
        self.assertEqual(
            self.read_json(os.path.join(self.hconfig, "overlays.json"))["xStep"],
            20)
        calls = self.systemctl_calls()
        self.assertIn("--user disable --now hudiy-diagnostics", calls)
        self.assertIn("--user disable --now hudiy-diag-keys", calls)
        self.assertIn("--user daemon-reload", calls)
        self.assertIn("left untouched", proc.stdout)

    def test_second_run_is_a_clean_noop(self):
        self.seed_full_install()
        first = self.run_install("--uninstall", "--no-reboot")
        self.assertEqual(first.returncode, 0)
        backups_first = sorted(
            f for f in os.listdir(self.hconfig) if ".bak-" in f)
        second = self.run_install("--uninstall", "--no-reboot")
        self.assertEqual(second.returncode, 0, second.stderr + second.stdout)
        self.assertIn("skipped", second.stdout)
        self.assertEqual(sorted(f for f in os.listdir(self.hconfig)
                                if ".bak-" in f), backups_first,
                         "second run must take no new backup")

    def test_dry_run_changes_nothing(self):
        self.seed_full_install()
        before = self.tree_hash()
        backups_before = sorted(
            f for f in os.listdir(self.hconfig) if ".bak-" in f)
        proc = self.run_install("--uninstall", "--dry-run", "--no-reboot")
        self.assertEqual(proc.returncode, 0, proc.stderr + proc.stdout)
        self.assertIn("[dry-run]", proc.stdout)
        self.assertEqual(self.tree_hash(), before,
                         "dry-run must leave the whole tree untouched")
        self.assertEqual(sorted(f for f in os.listdir(self.hconfig)
                                if ".bak-" in f), backups_before)
        # Only the read-only bus probe may reach systemctl in a dry run.
        for call in self.systemctl_calls():
            self.assertEqual(call, "--user status",
                             "dry-run must not drive systemctl: %r" % (call,))

    def test_install_then_uninstall_round_trip(self):
        self.seed_config(with_ours=False)
        with HealthStub() as stub:
            self.env["DIAG_HTTP_PORT"] = str(stub.port)
            installed = self.run_install("--no-reboot")
            self.assertEqual(installed.returncode, 0,
                             installed.stderr + installed.stdout)
            self.assertIn("diag", self.overlay_ids())
            self.assertIn("diag_show", self.menu_actions())
            self.assertTrue(os.path.isfile(
                os.path.join(self.unit_dir, "hudiy-diagnostics.service")))
            self.assertTrue(os.path.isfile(
                os.path.join(self.install_dir, "backend", "server.py")))
            self.assertTrue(os.path.isfile(
                os.path.join(self.env_dir, "env")))
            removed = self.run_install("--uninstall", "--no-reboot")
            self.assertEqual(removed.returncode, 0,
                             removed.stderr + removed.stdout)
            self.assertNotIn("diag", self.overlay_ids())
            self.assertNotIn("diag_show", self.menu_actions())
            self.assertEqual(self.overlay_ids(), ["race_dash", "diag-legacy"])
            self.assertFalse(os.path.exists(self.install_dir))
            self.assertFalse(os.path.exists(
                os.path.join(self.env_dir, "env")))

    def test_foreign_install_dir_is_left_alone(self):
        shared = os.path.join(self.tmp, "shared")
        os.makedirs(shared)
        sentinel = os.path.join(shared, "precious.txt")
        with open(sentinel, "w", encoding="utf-8") as handle:
            handle.write("not ours\n")
        self.env["DIAG_INSTALL_DIR"] = shared
        self.seed_units()
        self.seed_env()
        self.seed_config()
        proc = self.run_install("--uninstall", "--no-reboot")
        self.assertEqual(proc.returncode, 0, proc.stderr + proc.stdout)
        self.assertTrue(os.path.isfile(sentinel),
                        "a dir that is not ours must never be rm -rf'd")
        self.assertIn("WARNING", proc.stdout)

    def test_partial_install_uninstalls_cleanly(self):
        # Only an env file exists: no units, no tree, no Hudiy layout.
        self.seed_env()
        os.rmdir(self.hconfig)
        proc = self.run_install("--uninstall", "--no-reboot")
        self.assertEqual(proc.returncode, 0, proc.stderr + proc.stdout)
        self.assertFalse(os.path.exists(os.path.join(self.env_dir, "env")))
        self.assertIn("nothing to unregister", proc.stdout)

    def test_nothing_installed_is_a_clean_noop(self):
        os.rmdir(self.hconfig)
        proc = self.run_install("--uninstall", "--no-reboot")
        self.assertEqual(proc.returncode, 0, proc.stderr + proc.stdout)
        self.assertIn("skipped", proc.stdout)

    def test_malformed_config_warns_but_units_and_files_still_go(self):
        self.seed_units()
        self.seed_installed_tree()
        self.seed_env()
        bad = os.path.join(self.hconfig, "overlays.json")
        with open(bad, "w", encoding="utf-8") as handle:
            handle.write("{ not json {{{")
        self.write_json(os.path.join(self.hconfig, "applications_menu.json"),
                        {"items": [dict(RACE_ITEM)]})
        with open(bad, "rb") as handle:
            before = handle.read()
        proc = self.run_install("--uninstall", "--no-reboot")
        self.assertEqual(proc.returncode, 0, proc.stderr + proc.stdout)
        self.assertIn("WARNING", proc.stdout)
        with open(bad, "rb") as handle:
            self.assertEqual(handle.read(), before,
                             "refused file must be left exactly as it was")
        self.assertFalse(os.path.exists(
            os.path.join(self.unit_dir, "hudiy-diagnostics.service")))
        self.assertFalse(os.path.exists(self.install_dir))
        self.assertFalse(os.path.exists(os.path.join(self.env_dir, "env")))


if __name__ == "__main__":
    unittest.main()
