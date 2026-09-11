# Hudiy registration fragments (install note)

These two files are **fragments, not configuration files**. They are inserted
into the live Hudiy config; they must never replace it. Hudiy's own docs and the
Marketplace integration README say this explicitly, and a replacement would
delete every other app and overlay on the machine.

    overlays.json            one overlay entry  -> appended to config/overlays.json
    applications_menu.json   one menu item      -> appended to config/applications_menu.json

Live config directory (see `docs/HUDIY_UI_API_INVENTORY.md`):

    $HOME/.hudiy/share/config/overlays.json
    $HOME/.hudiy/share/config/applications_menu.json

## Registering

    python3 frontend/hudiy/merge_config.py                 # ~/.hudiy/share/config
    python3 frontend/hudiy/merge_config.py --port 44415     # non-default lane port
    python3 frontend/hudiy/merge_config.py --dry-run        # show, change nothing

* Idempotent: looks up the overlay by `identifier == "diag"` and the menu item by
  `action == "diag_show"`. Re-running updates the overlay `url` and reports
  "already present" for everything else.
* The overlay fragment deliberately leaves \`action\` EMPTY. Hudiy treats that
  field as one of ITS OWN native action ids; a custom string there (e.g.
  \`diag_show\`) makes Hudiy accept the dispatch and flip visibility but never
  create the overlay's webview - the menu taps log fine and nothing paints.
  The custom action lives ONLY on the menu item; the overlay is shown/hidden at
  runtime by the control lane (SetCustomOverlayVisibility), exactly like the
  working race-dash overlay.
* Non-destructive: each file it is about to change is first copied to
  `<name>.bak-<YYYYmmdd-HHMMSS>`. `applications.json` is never touched - this is
  an overlay, not a second instance of the app UI.
* Universal: if the config directory does not exist (a machine without a Hudiy
  layout) the script says so and exits 0.

`backend/deploy/install.sh` runs this step automatically, and only when the
config directory exists.

## Hudiy must be restarted (never live-patched)

Hudiy reads both files once, at start. After registering, restart Hudiy through
its normal launch path - on the reference unit that is the labwc autostart
script `~/.hudiy/share/hudiy_run.sh` - and do not edit config under a running
Hudiy: it rewrites its config from memory and loses the change. This is the same
"kill, take a backup, restart" discipline used for the audio config.

## Menu action and the open bench item

The menu entry dispatches the action `diag_show`, and the overlay entry lists it
in `visibleOnActions`. Hudiy shows a custom overlay through its protobuf API
(`SetCustomOverlayVisibility`, see the inventory doc): either it honours
`visibleOnActions` for a custom overlay, or something on the machine has to
register the action and toggle visibility when it is dispatched.

`visibleOnActions` with a non-empty list is documented but was not exercised in
the examples we have, so this is a **bench-trial item**, not a proven path:

1. Restart Hudiy and open *Diagnostics* from the menu, in the Hudiy category.
2. If the overlay does not appear, the fallback is a small daemon that registers
   `diag_show` and sends `SetCustomOverlayVisibility(identifier="diag",
   visibility=VISIBLE)` on dispatch. Nothing in the page changes for that - the
   overlay is just a URL (`http://127.0.0.1:44414/app/diag.html`).

While on the bench, note what the rotary knob reports for `SCROLL_LEFT` /
`SCROLL_RIGHT`: the page wires both the next/previous-control callbacks and the
left/right callbacks, so either mapping works, but only the trial can say which
one the knob actually sends.
