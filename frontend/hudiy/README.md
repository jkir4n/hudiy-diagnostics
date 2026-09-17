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

## Removing

    python3 frontend/hudiy/merge_config.py --remove             # drop our entries
    python3 frontend/hudiy/merge_config.py --remove --dry-run   # show, change nothing

* Reverse-merge: removes exactly the overlay whose `identifier == "diag"` and
  the menu item whose `action` matches our fragment (`diag_show`). Every other
  entry is left deep-equal; a merge -> remove round-trip restores the files'
  other content semantically identical to pre-merge.
* No-op when there is nothing to do (absent file, absent entry, missing config
  directory): prints "already absent", writes nothing, takes no backup — so a
  second run is always clean.
* Refuses files it does not understand (malformed JSON, wrong top-level
  shape): clear message, non-zero exit, nothing written.
* `backend/deploy/install.sh --uninstall` runs this step first, before any
  file deletion.

## Hudiy must be restarted (never live-patched)

Hudiy reads both files once, at start. After registering, restart Hudiy through
its normal launch path - on the reference unit that is the labwc autostart
script `~/.hudiy/share/hudiy_run.sh` - and do not edit config under a running
Hudiy: it rewrites its config from memory and loses the change. This is the same
"kill, take a backup, restart" discipline used for the audio config.

## Menu action and overlay visibility (bench-RESOLVED, 16 Sep 2026)

The menu entry dispatches the action `diag_show`; the overlay is shown/hidden
at runtime by the control lane (`SetCustomOverlayVisibility`), exactly like the
working race-dash overlay.

**Keep the overlay entry's `visibleOnActions` list EMPTY.** Bench finding
(16 Sep 2026, reference car): with `visibleOnActions: ["diag_show"]` the whole
chain still *succeeds* - Hudiy dispatches, the lane logs the dispatch,
`SetCustomOverlayVisibility(ALWAYS)` is accepted and logged, and the overlay's
webview is created and fully loads - but nothing ever PAINTS. Reverting the
list to `[]` (plus a Hudiy restart) restores the overlay immediately.
Non-empty `visibleOnActions` on a custom overlay is a silent no-show; do not
use it as a show mechanism.

Knob mapping (bench-captured): detents report 2=left/prev, 3=right/next,
28=center/enter, 1=back; the page wires both callback families, so either
mapping works.
