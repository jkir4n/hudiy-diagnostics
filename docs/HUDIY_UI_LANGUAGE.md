# HUDIY UI DESIGN LANGUAGE — from official repo screenshots (14 Sep 2026)

Source: github.com/wiboma/hudiy README images (screenshots 1-5, 7-12, 14-16, 23, 32, 37-38, 48) + vision analysis.

## Core style (what makes Hudiy look like Hudiy)
1. PURE BLACK background (#000–#0A0A0A). Cards = dark charcoal #161A22–#1E222A, NOT #0E1113-blue-tinted glass w/ borders+glow.
2. NO borders, NO glass/blur, NO glow. Separation purely by fill contrast + spacing. Card radius LARGE (~16-24px, generous).
3. Accent color = WHATEVER THEME the user picked (brown/orange, mint green, icy blue, purple, per theme source color) — comes from hudiy.colorScheme, never hardcoded.
4. Typography: Roboto-class sans. Hierarchy via SIZE not decoration: BIG values, small muted labels beneath/beside. Values often colored (accent), labels white/mid-gray.
5. Widgets on dashboards = metric tiles: label top-left small, huge numeric value, tiny muted unit, sparkline/area chart with gradient fill to transparent, ONE accent hue per metric channel.
6. Menus (Hudiy's): back arrow top-left, grid of items w/ thin-stroke monochrome line icons + small white labels centered under each; selected item = full capsule/pill in accent color w/ accent text.
7. Iconography: Material Symbols outline, ~monoline uniform stroke, white; accent used sparingly.
8. Circular arc gauges: thin track (pale tint of accent) + bold accent arc + huge centered value + tiny min/max labels at arc ends.
9. Status elements: rounded pill/chip with few icons (e.g., green/brown chip bottom-right). Persistent bottom nav bar w/ outline icons.
10. Light themes exist: warm cream/peach bg, darker cream cards, dark-caramel text/accent. Same geometry.
11. Web applications (like ours) run full-bleed, NO Hudiy chrome except persistent bottom system bar; page owns everything else. Apps' own headers look native — flat, no shadows, same radius.

## What our dashboard gets WRONG today (vs this)
- bg #0E1113 (blue-tinted) vs pure black; cards with 1px borders + glass backdrop-blur — Hudiy uses borderless flat fills.
- Ad-hoc severity stripes (4px left borders) — Hudiy has no stripe language; state via icon+color+fill.
- Mixed 12-26px type; Hudiy goes BIG on values (24-34sp) with tiny labels.
- Buttons as glass chips; Hudiy buttons = capsule/pill shapes, icon+label, accent when selected.
- Our controls show rgba tints+lines; Hudiy shows colored arc gauges / colored sparklines.

## Redesign targets (diag.html/diag.css rewrite)
A. Tokens: the FALLBACK bg is NOT flat #000 — on IPS/LCD panels pure black renders dead
   grayish (backlights can't do true black). Use a lifted dark base (#0F1216-class) with
   cards #1C1F26-class so the background↔card tonal step is visible. #000 only suits OLED.
   (These paints still map to --m3-* surface roles; bridge wins over fallback always.)
B. Flat cards: remove borders/glows; radius 20px; fill = colorScheme surfaceContainer/surfaceContainerHigh.
C. Value-first metric tiles for gauges block (load/rpm/temp/speed/intake/throttle when live): label 12px gray, value 28px accent, unit 11px muted.
D. Capsule pill buttons: icon+label, transparent surface, accent bg on active.
E. Kill left severity stripes → status communicated by colored dot/icon + value color.
F. Bottom persistent-style row of state icons (health/obd/bt) styled like Hudiy chip.
G. Keep all M3 token plumbing (08a8616/da37385 work) — the redesign only changes WHICH roles and HOW surfaces are painted.
H. Wheel/knob nav unchanged. severity semantics preserved (ok/warn/bad roles already bound).
I. Universal: geometry/conventions only, zero vehicle-specific logic — constraints per AGENTS.md.
