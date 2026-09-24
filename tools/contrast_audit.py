#!/usr/bin/env python3
"""WCAG contrast audit for frontend/diag.css (M3 fidelity pass, gap #9).

Checks every foreground/background pair the CSS actually produces under:
  (a) the dark fallback scheme  (:root --m3-* literals, parsed from the CSS)
  (b) the light scheme           (:root + body.scheme-light overrides, parsed)
  (c) the no-host Okabe-Ito fallback (legacy severity hues on the dark
      neutral -- the only context those raw hues ever paint in)

Thresholds: 4.5:1 normal text, 3:1 large text (>=24px; our scale tops out at
weight 500, so the 14pt-bold clause never applies) and non-text indicators.

Severity tints (--ok-bg etc.) mirror applyScheme() in frontend/diag.js:
hexToRgba(base, alpha) painted over the card/surface behind the element.

Exit 0 when every pair passes, 1 otherwise. Stdlib only.
"""

import re
import sys
from pathlib import Path

CSS_PATH = Path(__file__).resolve().parent.parent / "frontend" / "diag.css"

# Severity tint alphas, mirroring the pairs table in applyScheme().
TINT_ALPHA = {"ok": 0.12, "warn": 0.12, "bad": 0.13, "info": 0.12}
# Which host token each severity tint is derived from (applyScheme logic).
TINT_BASE = {"ok": "tertiary", "warn": "tertiary-container",
             "bad": "error", "info": "primary"}


def parse_block(css, selector):
    """Return {--var: raw value} for the first `selector { ... }` block."""
    m = re.search(re.escape(selector) + r"\s*\{(.*?)\}", css, re.S)
    props = {}
    if not m:
        return props
    for name, val in re.findall(r"(--[\w-]+)\s*:\s*([^;]+);", m.group(1)):
        props[name.strip()] = val.strip()
    return props


def hex_to_rgb(s):
    s = s.strip().lstrip("#")
    if len(s) == 3:
        s = "".join(c * 2 for c in s)
    if len(s) == 8:
        s = s[:6]
    if len(s) != 6:
        raise ValueError("bad hex: %r" % s)
    return tuple(int(s[i:i + 2], 16) for i in (0, 2, 4))


def resolve(value, theme):
    """Resolve a CSS value to (r, g, b): follows var(--x) chains, hex."""
    seen = set()
    while value.startswith("var("):
        name = value[4:].split(",")[0].strip().rstrip(")")
        if name in seen:
            raise ValueError("var cycle: %s" % name)
        seen.add(name)
        if name not in theme:
            raise ValueError("unresolved token: %s" % name)
        value = theme[name].strip()
    if value.startswith("#"):
        return hex_to_rgb(value)
    if value.startswith("rgba("):
        parts = value[5:].rstrip(")").split(",")
        return tuple(int(p) for p in parts[:3]), float(parts[3])
    raise ValueError("cannot resolve: %r" % value)


def blend(fg, alpha, bg):
    return tuple(round(alpha * f + (1 - alpha) * b) for f, b in zip(fg, bg))


def rel_lum(rgb):
    def lin(c):
        c /= 255.0
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4
    r, g, b = (lin(c) for c in rgb)
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def ratio(a, b):
    la, lb = rel_lum(a), rel_lum(b)
    hi, lo = max(la, lb), min(la, lb)
    return (hi + 0.05) / (lo + 0.05)


def is_large(px, weight):
    return px >= 24 or (px >= 19 and weight >= 700)


# (label, fg token, bg token, size px, weight, where)
# bg token may be ("tint", sev, base-token) for translucent carrier tints.
PAIRS = [
    ("body text", "--m3-on-surface", "--m3-background", 16, 400, "body"),
    ("card/row text", "--m3-on-surface", "--m3-surface-container", 14, 400, ".card .row"),
    ("button text", "--m3-on-surface", "--m3-surface-container-high", 14, 500, ".btn"),
    ("report/flat-row text", "--m3-on-surface", "--m3-surface-container-low", 14, 400, ".report .row.flat"),
    ("secondary on bg", "--m3-on-surface-variant", "--m3-background", 12, 400, ".settings .pill"),
    ("secondary on card", "--m3-on-surface-variant", "--m3-surface-container", 14, 400, ".verdict-sub .kv dd"),
    ("pill/chip text", "--m3-on-surface-variant", "--m3-surface-container-high", 12, 500, ".pill .chip"),
    ("ghost on bg", "--m3-outline", "--m3-background", 12, 400, ".hint .stamp .titles p"),
    ("ghost on card", "--m3-outline", "--m3-surface-container", 12, 400, ".verdict-rule .row-sub"),
    ("ghost on tile", "--m3-outline", "--m3-surface-container-high", 12, 400, ".tile-label"),
    ("tile value", "--m3-primary", "--m3-surface-container-high", 28, 400, ".tile-value"),
    ("scan timer", "--m3-primary", "--m3-surface-container", 28, 400, ".scan-timer"),
    ("detail code", "--m3-primary", "--m3-background", 36, 400, ".detail-code"),
    ("row code/value", "--m3-primary", "--m3-surface-container", 16, 500, ".row-code .row-value"),
    ("tab selected", "--m3-on-secondary-container", "--m3-secondary-container", 14, 500, ".tab[aria-selected]"),
    ("tab idle", "--m3-on-surface-variant", "--m3-surface", 14, 500, ".tab"),
    ("primary button", "--m3-on-primary", "--m3-primary", 14, 500, ".btn-primary"),
    ("replay tag", "--m3-on-tertiary-container", "--m3-tertiary-container", 11, 500, ".tag"),
    ("chip ok", "--m3-on-tertiary", "--m3-tertiary", 12, 500, ".chip-sev-ok .state-chip[ok]"),
    ("chip warn", "--m3-on-tertiary-container", "--m3-tertiary-container", 12, 500, ".chip-sev-warn .state-chip[warn]"),
    ("chip bad", "--m3-on-error-container", "--m3-error-container", 12, 500, ".chip-sev-bad .state-chip[bad]"),
    ("chip info", "--m3-on-primary-container", "--m3-primary-container", 12, 500, ".chip-sev-info .state-chip[info]"),
    ("step done", "--m3-on-primary-container", "--m3-primary-container", 12, 500, ".steps li[data-done]"),
    ("snackbar", "--m3-inverse-on-surface", "--m3-inverse-surface", 14, 400, ".toast"),
    ("snackbar bad", "--m3-on-error-container", "--m3-error-container", 14, 400, ".toast[data-sev=bad]"),
    ("snackbar warn", "--m3-on-tertiary-container", "--m3-tertiary-container", 14, 400, ".toast[data-sev=warn]"),
    ("count ok", "--ok", "--m3-surface-container", 28, 400, ".count[data-tone=ok]"),
    ("count warn", "--warn", "--m3-surface-container", 28, 400, ".count[data-tone=warn]"),
    ("count bad", "--bad", "--m3-surface-container", 28, 400, ".count[data-tone=bad]"),
    ("count info", "--info", "--m3-surface-container", 28, 400, ".count[data-tone=info]"),
    ("progress fill", "--m3-primary", "--m3-surface-container-high", 0, 0, ".track-fill (graphics, 3:1)"),
    ("focus ring", "--m3-primary", "--m3-background", 0, 0, ".focused (indicator, 3:1)"),
    ("clear confirm", "--m3-on-error-container", "--m3-error-container", 14, 500, ".btn-danger (S11 Clear now)"),
    ("clear confirm gated", "--m3-on-surface", "--m3-surface-container", 14, 500, ".btn-danger[disabled] (hollow on card)"),
    ("check row text", "--m3-on-surface", "--m3-surface-container-high", 14, 400, ".check-row (fix-first)"),
]


def build_themes(css):
    root = parse_block(css, ":root")
    light_over = parse_block(css, "body.scheme-light")
    dark = dict(root)
    light = dict(root)
    light.update(light_over)
    return dark, light


def paint(pair, theme):
    """Return (fg_rgb, bg_rgb) for a pair under a token theme."""
    _, fg, bg, _, _, _ = pair
    ref = lambda t: t if not t.startswith("--") else "var(%s)" % t
    fg_rgb = resolve(ref(fg), theme)
    if isinstance(bg, tuple):
        _, sev, base_token = bg
        base = resolve(ref("--m3-" + TINT_BASE[sev]), theme)
        under = resolve(ref(base_token), theme)
        bg_rgb = blend(base, TINT_ALPHA[sev], under)
    else:
        bg_rgb = resolve(ref(bg), theme)
    if isinstance(fg_rgb, tuple) and len(fg_rgb) == 2:
        fg_rgb, _ = fg_rgb  # not expected for text roles
    return fg_rgb, bg_rgb


def check(label, fg_rgb, bg_rgb, px, weight):
    need = 3.0 if (px == 0 or is_large(px, weight)) else 4.5
    got = ratio(fg_rgb, bg_rgb)
    kind = "large/graphics" if (px == 0 or is_large(px, weight)) else "normal"
    return got, need, kind, got >= need


def fmt(rgb):
    return "#%02X%02X%02X" % tuple(int(c) for c in rgb)


def main():
    css = CSS_PATH.read_text()
    dark, light = build_themes(css)
    failures = []
    print("contrast audit: %s" % CSS_PATH.name)
    for scenario, theme in (("dark", dark), ("light", light)):
        print("\n== %s scheme ==" % scenario)
        for pair in PAIRS:
            label = pair[0]
            try:
                fg_rgb, bg_rgb = paint(pair, theme)
            except ValueError as e:
                print("  %-16s ERROR %s" % (label, e))
                failures.append((scenario, label, "unresolved"))
                continue
            got, need, kind, ok = check(label, fg_rgb, bg_rgb, pair[3], pair[4])
            flag = "pass" if ok else "FAIL"
            print("  %-16s %s on %s  %4.2f:1 (need %.1f, %s) %s  [%s]"
                  % (label, fmt(fg_rgb), fmt(bg_rgb), got, need, kind, flag, pair[5]))
            if not ok:
                failures.append((scenario, label, "%.2f < %.1f" % (got, need)))
    print("\n== no-host Okabe-Ito fallback (shipped fallback severity hues) ==")
    print("   (hues as solid text on the dark neutral + on their own tints.")
    print("   Normal-size text on tints was eliminated in the M3 pass (chips,")
    print("   tag, toast and state now use container/on-container pairs), so")
    print("   these rows guard the remaining hue users — status dots (always")
    print("   paired with a word, never colour-only) and large numerics — at")
    print("   the 3:1 large/graphics threshold.)")
    neutral = hex_to_rgb("#0F1216")
    for sev in ("ok", "warn", "bad", "info"):
        hue = resolve("var(--%s)" % sev, dark)
        base = resolve("var(--m3-%s)" % TINT_BASE[sev], dark)
        for blabel, bg in (("solid", neutral),
                           ("tint", blend(base, TINT_ALPHA[sev], neutral))):
            got, need, kind, ok = check(sev, hue, bg, 28, 400)
            flag = "pass" if ok else "FAIL"
            print("  %-4s %-5s %s on %s  %4.2f:1 (need %.1f) %s"
                  % (sev, blabel, fmt(hue), fmt(bg), got, need, flag))
            if not ok:
                failures.append(("fallback", "%s %s" % (sev, blabel),
                                 "%.2f < %.1f" % (got, need)))
    print()
    if failures:
        print("RESULT: FAIL (%d pair%s)" % (len(failures),
                                            "" if len(failures) == 1 else "s"))
        for sc, label, why in failures:
            print("  [%s] %s: %s" % (sc, label, why))
        return 1
    print("RESULT: all pass")
    return 0


if __name__ == "__main__":
    sys.exit(main())
