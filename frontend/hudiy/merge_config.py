#!/usr/bin/env python3
"""Merge the Diagnostics fragments into a Hudiy config directory.

    python3 merge_config.py [CONFIG_DIR] [--port 44414] [--dry-run]
    python3 merge_config.py [CONFIG_DIR] --remove [--dry-run]

* CONFIG_DIR defaults to ``$HOME/.hudiy/share/config`` (the layout documented in
  docs/HUDIY_UI_API_INVENTORY.md). If it does not exist the script says so and
  exits 0 - a machine without a Hudiy config layout simply has nothing to patch.
* Non-destructive: ``overlays.json`` and ``applications_menu.json`` are copied
  to ``<name>.bak-<YYYYmmdd-HHMMSS>`` before the first write of a run, and the
  fragments are INSERTED INTO the existing arrays. Nothing else is touched and
  ``applications.json`` is never modified (this is an overlay, not an app URL).
  Writes are atomic (temp file + rename) and reads tolerate a UTF-8 BOM, so a
  crash or odd encoding can never leave a half-written config behind.
* Idempotent: re-running after a port change updates the overlay's url, and
  re-running otherwise reports "already present" and writes nothing.
* ``--remove`` reverses the merge: it drops exactly our overlay entry
  (``identifier == "diag"``) and our menu item (the fragment's ``action``) and
  leaves every other entry byte-for-byte alone. Absent file or absent entry is
  a no-op ("already absent": no write, no backup); a second run is therefore
  also a no-op. A file that is malformed or has the wrong top-level shape is
  refused (clear message, non-zero exit, nothing written).

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

#: Canonical empty shape of overlays.json (matches Hudiy's documented shape).
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
    # utf-8-sig: tolerate a BOM (some editors save JSON that way on Windows).
    if not os.path.isfile(path):
        return default, False
    with open(path, "r", encoding="utf-8-sig") as handle:
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
    # Write-then-rename: a crash or power loss mid-write can never leave a
    # half-written config; the .bak-* taken by backup() is the fallback.
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=4)
        handle.write("\n")
    os.replace(tmp, path)


def merge_overlays(config_dir, url, dry_run, stamp):
    path = os.path.join(config_dir, "overlays.json")
    with open(OVERLAY_FRAGMENT, "r", encoding="utf-8") as handle:
        entry = json.load(handle)
    entry["url"] = url
    # Bench-proven 16 Sep 2026 (reference car): a NON-EMPTY visibleOnActions
    # on a custom overlay silently suppresses the paint - every API call still
    # succeeds (dispatch logged, SetCustomOverlayVisibility accepted, webview
    # created and loaded) but nothing ever shows. Keep it empty: runtime
    # SetCustomOverlayVisibility is the only show path. Pinning here also
    # self-heals configs written before this fix.
    entry["visibleOnActions"] = []

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


def _load_or_refuse(path, what, allow_list=False):
    """Read a live config file, or refuse it loudly (never half-handle it)."""
    try:
        doc, _existed = load_json(path, None)
    except json.JSONDecodeError as exc:
        raise SystemExit("%s is not valid JSON (%s) - refusing to touch it"
                         % (path, exc))
    if doc is None:  # absent file (or blank): nothing of ours can be in it.
        return None
    if allow_list and isinstance(doc, list):
        return doc
    if not isinstance(doc, dict):
        raise SystemExit("%s is not an object - refusing to touch it" % path)
    return doc


def remove_overlays(config_dir, dry_run, stamp):
    """Drop our overlay entry; every other entry is left exactly as it was."""
    path = os.path.join(config_dir, "overlays.json")
    with open(OVERLAY_FRAGMENT, "r", encoding="utf-8") as handle:
        identifier = json.load(handle)["identifier"]
    doc = _load_or_refuse(path, "overlays")
    if doc is None:
        print("    %s: already absent (no file)" % path)
        return "already absent"
    overlays = doc.get("overlays")
    if overlays is None:
        print("    %s: already absent (no 'diag' overlay)" % path)
        return "already absent"
    if not isinstance(overlays, list):
        raise SystemExit("%s: 'overlays' is not an array - refusing to touch it"
                         % path)
    kept = [item for item in overlays
            if not (isinstance(item, dict)
                    and item.get("identifier") == identifier)]
    if len(kept) == len(overlays):
        print("    %s: already absent (no 'diag' overlay)" % path)
        return "already absent"
    if dry_run:
        print("    [dry-run] %s: would remove overlay %r (backup + write)"
              % (path, identifier))
        return "removed"
    saved = backup(path, stamp)
    doc["overlays"] = kept
    dump(path, doc)
    print("    %s: removed overlay %r%s"
          % (path, identifier, "" if saved is None else " (backup %s)"
             % os.path.basename(saved)))
    return "removed"


def remove_menu(config_dir, dry_run, stamp):
    """Drop our menu item; every other item is left exactly as it was."""
    path = os.path.join(config_dir, "applications_menu.json")
    with open(MENU_FRAGMENT, "r", encoding="utf-8") as handle:
        action = json.load(handle)["action"]
    doc = _load_or_refuse(path, "menu", allow_list=True)
    if doc is None:
        print("    %s: already absent (no file)" % path)
        return "already absent"
    if isinstance(doc, list):
        wrapped = {"items": doc}
    else:
        wrapped = doc
    items = wrapped.get("items")
    if items is None:
        print("    %s: already absent (no %r item)" % (path, action))
        return "already absent"
    if not isinstance(items, list):
        raise SystemExit("%s: 'items' is not an array - refusing to touch it"
                         % path)
    kept = [item for item in items
            if not (isinstance(item, dict) and item.get("action") == action)]
    if len(kept) == len(items):
        print("    %s: already absent (no %r item)" % (path, action))
        return "already absent"
    if dry_run:
        print("    [dry-run] %s: would remove item %r (backup + write)"
              % (path, action))
        return "removed"
    saved = backup(path, stamp)
    wrapped["items"] = kept
    dump(path, wrapped)
    print("    %s: removed item %r%s"
          % (path, action, "" if saved is None else " (backup %s)"
             % os.path.basename(saved)))
    return "removed"


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
    parser.add_argument("--remove", action="store_true",
                        help="reverse the merge: drop our overlay entry and "
                             "menu item, leave everything else alone")
    args = parser.parse_args(argv)

    if not os.path.isdir(args.config_dir):
        if args.remove:
            print("    no Hudiy config layout at %s - nothing to remove "
                  "(already absent)" % args.config_dir)
        else:
            print("    no Hudiy config layout at %s - nothing to register "
                  "(menu/overlay entry skipped)" % args.config_dir)
        return 0

    stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
    if args.remove:
        print("    removing overlay 'diag' + its menu item")
        overlay_action = remove_overlays(args.config_dir, args.dry_run, stamp)
        menu_action = remove_menu(args.config_dir, args.dry_run, stamp)
        changed = [a for a in (overlay_action, menu_action)
                   if a != "already absent"]
        if changed and not args.dry_run:
            print("    Hudiy must be restarted to read the change (it loads "
                  "these files once at start)")
        return 0

    url = args.url or "http://127.0.0.1:%d/app/diag.html" % args.port
    print("    registering overlay 'diag' -> %s" % url)
    overlay_action = merge_overlays(args.config_dir, url, args.dry_run, stamp)
    menu_action = merge_menu(args.config_dir, args.dry_run, stamp)
    changed = [a for a in (overlay_action, menu_action) if a != "already present"]
    if changed and not args.dry_run:
        print("    Hudiy must be restarted to read the new config (it loads "
              "these files once at start)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
