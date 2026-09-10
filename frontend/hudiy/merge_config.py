#!/usr/bin/env python3
"""Merge the Diagnostics fragments into a Hudiy config directory.

    python3 merge_config.py [CONFIG_DIR] [--port 44414] [--dry-run]

* CONFIG_DIR defaults to ``$HOME/.hudiy/share/config`` (the layout documented in
  docs/HUDIY_UI_API_INVENTORY.md). If it does not exist the script says so and
  exits 0 - a machine without a Hudiy config layout simply has nothing to patch.
* Non-destructive: ``overlays.json`` and ``applications_menu.json`` are copied
  to ``<name>.bak-<YYYYmmdd-HHMMSS>`` before the first write of a run, and the
  fragments are INSERTED INTO the existing arrays. Nothing else is touched and
  ``applications.json`` is never modified (this is an overlay, not an app URL).
* Idempotent: re-running after a port change updates the overlay's url, and
  re-running otherwise reports "already present" and writes nothing.

Only the standard library is used, so this works on a bare Hudiy install.
"""

import argparse
import datetime
import json
import os
import shutil
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
OVERLAY_FRAGMENT = os.path.join(HERE, "overlays.json")
MENU_FRAGMENT = os.path.join(HERE, "applications_menu.json")

#: Canonical empty shape of overlays.json, from Hudiy's own examples.
OVERLAYS_SKELETON = {
    "overlays": [],
    "navigationOverlayPosition": {"x": 0, "y": 0},
    "volumeOverlayPosition": {"x": 0, "y": 0},
    "navigationOverlayVisibility": "NONE",
    "volumeOverlayVisibility": "NONE",
    "navigationOverlayOpacity": 100,
    "xStep": 20,
    "yStep": 10,
}

#: Keys the installer keeps in sync with the live config when re-run.
SYNCED_OVERLAY_KEYS = ("url", "action", "visibleOnActions", "controlAudioFocus")


def load_json(path, default):
    if not os.path.isfile(path):
        return default, False
    with open(path, "r", encoding="utf-8") as handle:
        text = handle.read().strip()
    if not text:
        return default, False
    return json.loads(text), True


def backup(path, stamp):
    if not os.path.isfile(path):
        return None
    target = "%s.bak-%s" % (path, stamp)
    shutil.copy2(path, target)
    return target


def dump(path, payload):
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=4)
        handle.write("\n")


def merge_overlays(config_dir, url, dry_run, stamp):
    path = os.path.join(config_dir, "overlays.json")
    with open(OVERLAY_FRAGMENT, "r", encoding="utf-8") as handle:
        entry = json.load(handle)
    entry["url"] = url

    doc, existed = load_json(path, dict(OVERLAYS_SKELETON))
    if not isinstance(doc, dict):
        raise SystemExit("%s is not an object - refusing to touch it" % path)
    overlays = doc.get("overlays")
    if overlays is None:
        overlays = []
        doc["overlays"] = overlays
    if not isinstance(overlays, list):
        raise SystemExit("%s: 'overlays' is not an array - refusing to touch it"
                         % path)

    current = None
    for item in overlays:
        if isinstance(item, dict) and item.get("identifier") == entry["identifier"]:
            current = item
            break

    if current is None:
        overlays.append(entry)
        action = "inserted"
    else:
        changed = [k for k in SYNCED_OVERLAY_KEYS if current.get(k) != entry[k]]
        for key in changed:
            current[key] = entry[key]
        action = ("updated %s" % ", ".join(changed)) if changed else "already present"

    if action != "already present":
        if dry_run:
            print("    [dry-run] %s: %s (backup + write)" % (path, action))
        else:
            saved = backup(path, stamp)
            # A brand new file has nothing worth backing up; only note real ones.
            dump(path, doc)
            print("    %s: %s%s" % (path, action,
                                    "" if saved is None else " (backup %s)"
                                    % os.path.basename(saved)))
    else:
        print("    %s: %s" % (path, action))
    return action


def merge_menu(config_dir, dry_run, stamp):
    path = os.path.join(config_dir, "applications_menu.json")
    with open(MENU_FRAGMENT, "r", encoding="utf-8") as handle:
        entry = json.load(handle)

    doc, existed = load_json(path, {"items": []})
    if isinstance(doc, list):
        doc = {"items": doc}
    if not isinstance(doc, dict):
        raise SystemExit("%s is not an object - refusing to touch it" % path)
    items = doc.get("items")
    if items is None:
        items = []
        doc["items"] = items
    if not isinstance(items, list):
        raise SystemExit("%s: 'items' is not an array - refusing to touch it"
                         % path)

    for item in items:
        if isinstance(item, dict) and item.get("action") == entry["action"]:
            print("    %s: already present" % path)
            return "already present"

    items.append(entry)
    if dry_run:
        print("    [dry-run] %s: inserted (backup + write)" % path)
        return "inserted"
    saved = backup(path, stamp)
    dump(path, doc)
    print("    %s: inserted%s" % (path, " (backup %s)" % os.path.basename(saved)
                                  if saved else ""))
    return "inserted"


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("config_dir", nargs="?",
                        default=os.path.join(os.path.expanduser("~"),
                                             ".hudiy", "share", "config"),
                        help="Hudiy config directory (default ~/.hudiy/share/config)")
    parser.add_argument("--port", type=int, default=44414,
                        help="port the diagnostics lane listens on (default 44414)")
    parser.add_argument("--url", default=None,
                        help="full overlay url (overrides --port)")
    parser.add_argument("--dry-run", action="store_true",
                        help="report what would change, write nothing")
    args = parser.parse_args(argv)

    url = args.url or "http://127.0.0.1:%d/app/diag.html" % args.port
    if not os.path.isdir(args.config_dir):
        print("    no Hudiy config layout at %s - nothing to register "
              "(menu/overlay entry skipped)" % args.config_dir)
        return 0

    stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
    print("    registering overlay 'diag' -> %s" % url)
    merge_overlays(args.config_dir, url, args.dry_run, stamp)
    merge_menu(args.config_dir, args.dry_run, stamp)
    if not args.dry_run:
        print("    Hudiy must be restarted to read the new config (it loads "
              "these files once at start)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
