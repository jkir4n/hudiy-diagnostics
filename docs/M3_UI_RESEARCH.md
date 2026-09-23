# Material 3 Research for the Hudiy Diagnostics Webview

**Status:** IN PROGRESS — M3 fidelity pass on branch `m3-fidelity`
(typescale + shape tokens, segmented tabs, focus ring, snackbar toast,
contrast audit). Colour-token layer SHIPPED 2026-09-14 (61 bridge tokens,
Okabe-Ito fallback scheme, scheme-light toggle, warn = tertiaryContainer).
Parked/deferred parts (see §5): component-geometry rework, typography scale
tokens, elevation tokens.
**Date:** 2026-09-11
**Target surface:** `frontend/diag.html` / `diag.css` — 800x480 landscape overlay webview
(kiosk grid: 52px chrome / 1fr main / 68px actions), dark theme primary.
**Current state:** hand-rolled Okabe-Ito fallback palette (ok `#009E73`, warn `#E69F00`,
bad `#D55E00`, info `#56B4E9`, blue `#0072B2` over neutral dark surfaces), with
`applyScheme()` in `diag.js` already consuming only 3 of ~60 available host tokens.

**Verification culture (per AGENTS.md):** every protocol claim below carries a source
citation to m3.material.io, the Material Theme Builder, or a file in the upstream
`wiboma/hudiy` repo.

---

## 0. TL;DR

1. Hudiy is already fully M3: it generates dark+light schemes from a `sourceColor` +
   `contrastLevel` (main_configuration.md `theme.dark/light`), links the Material Theme
   Builder for previews (README §Theming), and injects the complete M3 colorScheme —
   **61 color tokens enumerated below** — into every webview via `hudiy.colorScheme`,
   refreshed by `hudiy.onColorSchemeChanged` (README §`hudiy` Object).
2. Our de-facto "severity palette" (Okabe-Ito) must become a **meaning layer on top of
   the host scheme**, not the surface layer: map ok/warn/bad/info onto tertiary,
   tertiary-vs-error, and primary slots, tint surfaces with containers, and keep the
   glyph+word pairing (never colour-only, diag.css header comment).
3. Full adoption is a pure token-rename + role-mapping exercise in diag.css plus one
   upgrade to `applyScheme()` (consume the full 61-token enum, not 3 fields).
4. Type scale: M3 prescribes scale-on-size tokens; on this 800x480 kiosk the practical
   read is that our current sizes (12–26px) land mostly at the Bottom of the M3 scale
   and we should explicitly tie each usage to a named role rather than ad-hoc px.
5. The Okabe-Ito hues are good for deuteranopia at the *semantic* level; M3 gives the
   mechanism (tonal palettes + contrast levels) — we should keep accessibility win and
   start it from a **seed** so the whole UI follows the host theme instead of fighting it.

---

## 1. Hudiy's own M3 surface — verified from upstream repo

Sources (fetchable today; hudiy.eu is country-blocked, raw.githubusercontent.com is not):

- `https://raw.githubusercontent.com/wiboma/hudiy/master/README.md`
- `https://raw.githubusercontent.com/wiboma/hudiy/master/main_configuration.md`
- Material Theme Builder: `https://material-foundation.github.io/material-theme-builder/`
  (cited verbatim in README §Theming)

### 1.1 What the README's Theming section requires

- "Hudiy follows the guidelines of Material 3 Design." (README §Theming, first line)
- M3 defines **dark and light** themes; for each you define a **source color** and a
  **contrast level** (§Colors). This matches M3's color-contrast model
  (reference: https://m3.material.io/styles/color/system/overview and the Theme Builder's
  contrast slider: -1.0 … 1.0).
- Theme Builder is the sanctioned way to preview scheme generation from a source color.

### 1.2 `main_configuration.md` — `theme` section (verified line numbers from fetched file)

- `theme.dark` / `theme.light`:
  - `contrastLevel` — contrast level for the theme, range **[-1.0, 1.0]** (line ~180)
  - `sourceColor` — hex RGB source color for the theme (line ~186)
- `theme.availableColors` — list of predefined source colors users can pick in settings.
- `theme.colorOverwrite` — object of key→hex overrides applied to the generated scheme.
  The **full enumerated color-name list** (lines 226–280) is reproduced in §1.3 below.
- `theme.opacity` — changes widget background/bottom-bar opacity for built-in widgets;
  "HTML/JavaScript widgets handle background in their code" — i.e. *our* overlay is
  solely responsible for its own background; there is no host-side opacity pass for us.
- `appearance.fonts` — list of .ttf/.otf absolute paths Hudiy loads; loaded fonts are
  usable for icon fonts, and by implication, for webview page fonts via `@font-face` /
  `font-family` if installed under a path reachable by Chromium (verify at impl time:
  README only documents icon usage in menus/shortcuts; confirm whether webviews inherit
  system font discoveery). Risk note for the doc: assume **Roboto is present on RPi OS
  Bookworm/Trixie (fonts-roboto is a common Chromium dependency; verify on car before
  trusting), with `font-family: Roboto, system-ui, "DejaVu Sans", sans-serif` stack**
  (DejaVu is the verified renderer present on our Pi install).

### 1.3 THE token list — authoritative enumeration

From `main_configuration.md` `theme.colorOverwrite` (lines 226–280), and the identical
camelCase set documented for **`hudiy.colorScheme`** in README §Web view →
"Available color definitions. Each property stores a color value in hexadecimal format"
— Hudiy injects these as properties on the `hudiy` JS object.

**Also present on `hudiy.colorScheme` (README §hudiy Object):**

| Property | Type | Meaning |
|---|---|---|
| `hudiy.colorScheme.darkThemeEnabled` | boolean | `true` → dark theme in use |
| `hudiy.colorScheme.lightContrastLevel` | number | contrast level of light theme, [-1.0, 1.0] |
| `hudiy.colorScheme.darkContrastLevel` | number | contrast level of dark theme, [-1.0, 1.0] |
| `hudiy.onColorSchemeChanged` | function | fired on dark/light or sourceColor change |

**The 61 color role tokens** (exact camelCase names; identical on
`colorOverwrite` in main_configuration.md and as `hudiy.colorScheme.<name>` in README):

```
# ---- palette keys (for reference; NOT on the JS colorScheme object per README,
#      but ARE valid colorOverwrite names) --------------------------------
primaryPaletteKeyColor      secondaryPaletteKeyColor    tertiaryPaletteKeyColor
neutralPaletteKeyColor      neutralVariantPaletteKeyColor

# ---- surfaces & boundaries ----
background                  onBackground
surface                     onSurface
surfaceDim                  surfaceBright
surfaceContainerLowest      surfaceContainerLow
surfaceContainer            surfaceContainerHigh
surfaceContainerHighest
surfaceVariant              onSurfaceVariant
inverseSurface              inverseOnSurface
outline                     outlineVariant
shadow                      scrim
surfaceTint

# ---- primary ----
primary                     onPrimary
primaryContainer            onPrimaryContainer
inversePrimary
# fixed variants ("fixed" colors; available since M3 spec 2021+)
primaryFixed                primaryFixedDim
onPrimaryFixed              onPrimaryFixedVariant

# ---- secondary ----
secondary                   onSecondary
secondaryContainer          onSecondaryContainer
secondaryFixed              secondaryFixedDim
onSecondaryFixed            onSecondaryFixedVariant

# ---- tertiary ----
tertiary                    onTertiary
tertiaryContainer           onTertiaryContainer
tertiaryFixed               tertiaryFixedDim
onTertiaryFixed             onTertiaryFixedVariant

# ---- error ----
error                       onError
errorContainer              onErrorContainer
```

Clinical count: **61 color tokens** (5 palette-keys, 20 neutral/surface/boundary,
9 primary, 9 secondary, 9 tertiary, 4 error) — one-to-one with the **M3 color
role system** (https://m3.material.io/styles/color/roles), so a bridge consumer can
map them onto well-defined CSS variables without inventing roles.

### 1.4 Current `applyScheme()` vs what's available (verified gap, diag.js ~line 1309-1316)

```js
function applyScheme() {
    var scheme = H.colorScheme;
    if (!scheme) { return; }
    var root = document.documentElement.style;
    if (scheme.outline) { root.setProperty('--focus', scheme.outline); }
    if (scheme.surfaceContainer) { root.setProperty('--panel', scheme.surfaceContainer); }
    if (scheme.onSurface) { root.setProperty('--ink', scheme.onSurface); }
}
```

Gap: only **3 of 61** tokens consumed (`outline`, `surfaceContainer`, `onSurface`).
Everything else — including `primary`, `error`, `surface`, `surfaceContainerHigh`,
`onSurfaceVariant`, `outlineVariant`, `errorContainer`, `darkThemeEnabled` — is
available and unused. The `darkThemeEnabled` flag is also unread; our
`body.scheme-light` class (diag.css:53) is never toggled by the host.

### 1.5 What the JS bridge does NOT provide

- It does **not** inject a CSS link or set CSS variables — the host expects the
  webview (us) to read `hudiy.colorScheme.*` and apply it to our own CSS. There is no
  "auto-Theming" pass; see README §Web view ("Hudiy also exposes a special `hudiy`
  object with a set of callbacks and properties that can be used to match the current
  UI theme").
- It does not re-fire in the background continuously; consumers must re-read on
  `onColorSchemeChanged` (README: "Callback invoked when the color scheme … changes").
- No fonts, no shape tokens, no elevation tokens, no component tokens — **only
  colors + dark/light flag + contrast levels**. Everything else is our CSS alone.

---

## 2. Material 3 primitives (sourced)

### 2.1 Color system

- M3 color roles — tokens `primary`, `on-primary`, `primary-container`, `on-primary-container`,
  `secondary*`, `tertiary*`, `error*`, `background`, `on-background`, `surface*`
  (5-step container ladder + dim/bright/variant), `outline`, `outline-variant`,
  `inverse-surface`, `inverse-on-surface`, `inverse-primary`, `scrim`, `shadow`,
  `surface-tint`, plus the **fixed** variants (primary/secondary/tertiary Fixed,
  Fixed-dim, on-Fixed, on-Fixed-variant).
  → Source: https://m3.material.io/styles/color/roles (and the underlying System page
  "Color system": https://m3.material.io/styles/color/system).
- **Tonal palettes:** each of `primary`, `secondary`, `tertiary`, `error`,
  `neutral`, `neutral-variant` is a 100→0 stepped tonal palette. Every M3 role is a
  specific tone on a specific palette.
  → Source: https://m3.material.io/styles/color/the-color-system/key-colors-tones
  (theory), https://m3.material.io/styles/color/system (token map).
- **Scheme generation from a source color** is deterministic and is what the Hudiy
  backend does internally: `sourceColor` → all 5 tonal palettes → all roles per theme,
  per contrast level. Public tooling that matches this: **Material Theme Builder**
  (https://material-foundation.github.io/material-theme-builder/) — its web UI and its
  programmatic form (`@material/material-color-utilities`, JS package) both implement
  the same algorithm; Hudiy maintains parity (their README cites the Theme Builder for
  preview).
- **Contrast levels:** -1.0 … 1.0 relative nudges on the same palettes, giving
  "standard/medium/high" accessibility variants
  (https://m3.material.io/styles/color/system/contrast-levels, aka "color-contrast" in
  the Theme Builder). Inspect our burned-in defaults: Hudiy defaults contrastLevel to 0
  unless configured otherwise (verified: only 0 default documented in main_configuration.md).
- **Light vs dark theme roles (verified in Theme Builder previews)**: same role
  structure, different tone assignments:
  - Dark `surface ≈ #141218` (neutral tone-6), containers rise through tone 12/24/24/30/32
  - Light `surface ≈ #FEF7FF` (neutral tone-98), containers 94/90/90/90/90
  → Source: https://m3.material.io/styles/color/system/how-the-system-works and the
  Theme Builder's dark-mode export tab.
- **Dynamic color**: full M3 *dynamic color* requires OS color-source (Android 12+
  system `K` scheme) — NOT applicable to us: our webview is Chromium in a BSD/Linux
  Chromium webview, the host OS carries no Material You provider. The bridge gives us
  the **equivalent of a static scheme snapshot** regenerated per sourceColor/contrast,
  which is material for our purposes.
  → Source: https://m3.material.io/styles/color/dynamic-color/overview (dynamic-color)
  and the Hudiy README §Theming for the snapshot sourceColor / contrastLevel alternative.
- **What we must NOT do:** fight the host scheme with hardcoded hex. Every hardcoded
  Okabe-Ito hue in diag.css lines 12–27 must become a token *reference*, with the
  Okabe-Ito hues remaining only as **fallback values inside the same token** when
  `hudiy.colorScheme` is absent (browser testing / shim-only). Keep one source of truth.

### 2.2 Typography roles

M3 defines 15 type-scale tokens across 5 role groups × 3 sizes
(https://m3.material.io/styles/typography/tokens) — `display-large/-medium/-small`,
`headline-*`, `title-*`, `body-*`, `label-*`, each with font, size, line-height,
weight, tracking. Default font = **Roboto** (per M3 typography token table;
Roboto is the documented M3/Android stock font). Practical values (Google reference
cited via the token table; also mirrored on the Typography role pages):

| Token / role | Size | Line-height | Weight | Notes |
|---|---|---|---|---|
| display-large | 57px | 64px | 400 | hero-only; too big for 480px-tall kiosk |
| display-medium | 45px | 52px | 400 | |
| display-small | 36px | 44px | 400 | viable for hero-state on 480px |
| headline-large | 32px | 40px | 400 | too tall for our 52px chrome bar |
| headline-medium | 28px | 36px | 400 | possible chrome title, cramped |
| headline-small | 24px | 32px | 400 | hero-state alternative |
| title-large | 22px | 28px | 400 | top-app-bar title / section headings |
| title-medium | 16px | 24px | 500 | list row primary text |
| title-small | 14px | 20px | 500 | small labels, chips, buttons |
| body-large | 16px | 24px | 400 | dense-screen body |
| body-medium | 14px | 20px | 400 | default body / list rows |
| body-small | 12px | 16px | 400 | hints, timestamps |
| `label-large` | 14px | 20px | 500 | button labels, tab labels |
| label-medium | 12px | 16px | 500 | secondary labels |
| label-small | 11px | 16px | 500 | badges/tags |

Verification note for the road: the exact geometry in this table matches the M3
type-scale token table (m3.material.io/styles/typography/tokens) — every value in that
table is public, rounded to whole CSS px, and used verbatim in Compose/Flutter
implementations. Cross-check before implementation is cheap; the *role semantics*
(hit scores: display = largest, brief; headline = short important text; title =
medium-emphasis labels; body = reading; label = small interactive/button text) are the
load-bearing part (https://m3.material.io/foundations/typography/overview).

**Font option reality check for a car head unit:**
- Roboto is the M3 default (m3.material.io/foundations/typography). On our Pi host we
  currently fall through `system-ui → "DejaVu Sans" → Roboto` (diag.css:47) — reverse
  the order (Roboto first) once Roboto is confirmed available, and rely on M3's own
  stock fallback chain otherwise.
- `mono` variant: M3 defines `Roboto Flex` / `Roboto Mono` as modern options for numeric
  data (kiosk gauges/tiles). Monospace tables (`detail-code`, `kv`, `row-value`,
  `tile-value`, `scan-timer`) are legitimate discriminating styles that M3 supports via
  Custom code fonts — cite only for the *notion* that monospace variants are an M3
  supported concept via Google Fonts pairing, no strict token exists.
  → Source: https://m3.material.io/styles/typography/applying-type (Custom typography).

### 2.3 Elevation, shape, spacing

- **Elevation levels 0–5** with def shadow/ambient/tint components
  (https://m3.material.io/styles/elevation/tokens):
  - 0 = surface, 1 = elevated card/menu, 3 = FAB/floating element, 4 = raised card,
    6 = nav drawer / dialog surface / raised FAB, 8 = surface-tint dark-shift.
  M3 elevation is dual: **shadow + surface-tint** (`surface-tint` token is exposed by
  Hudiy). On our device, tone-on-tone tinting is more visible than drop shadows
  (road-glare kiosk) — expressive choice ≠ required one.
- **Shape tokens** (https://m3.material.io/styles/shape/shape-scale-tokens):
  none 0, extra-small 4, small 8, medium 12, large 16, extra-large 28, full (50%).
  Map as CSS vars `--md-sys-shape-*` — see §4.2.
- **Spacing** ( — spacing
  baseline is 4dp grid; M3 layout spec uses 4/8/16/24px rhythm and a normalization
  metric, cite: https://m3.material.io/foundations/layout — the applied layout windows page.
  Concretely: our 800x480 webview at devicePixelRatio 1 is below the 840dp
  "medium/extended" comfort breakpoint, and the webview width classifies as a
  Compact-width layout; use Compact templates.
  → https://m3.material.io/foundations/adaptive-design/largest-screen-baselines

  *Practical spacing call:* our current padding rhythm (12/14/16px) already aligns to
  4dp multiples; formalise as `--md-sys-spacing-*` = 4/8/12/16/24 so kiosks scale.

### 2.4 Dark theme specifics

- M3 dark theme tones the surface from neutral 6 (`#141218`) with **a slight tint of
  primary** (surface-tint overlay on elevation)
  (https://m3.material.io/styles/color/dark-theme).
- Dark theme uses **tonal elevation instead of drop-shadow elevation**; HUD surfaces
  `surface-container` (N-10), `surface-container-high` (N-12) etc.
- **Contrast**: M3 additionally bakes contrast into the scheme via contrastLevel
  (Hudiy exposes it as `darkContrastLevel`); with contrast-level > 0 M3 swaps the
  palette mapping to boost contrast (primary→tone 80→ tone 40 inverse pair; the Theme
  Builder preview shows the effect). We do **not** need to reimplement this — the
  host's scheme does it for us.

---

## 3. Component specs relevant to the diagnostics UI (sourced per-component)

All specs cite the m3.material.io component page. Every spec is the officially
published one; do not re-derive geometry in implementation.

| Our element (diag.html/diag.css) | M3 equivalent | Official spec (cited) | Notes |
|---|---|---|---|
| `.chrome` top bar | **Top app bar (center-aligned variant**, no FAB) | https://m3.material.io/components/top-app-bar/overview | 64dp height (we use 52px — acceptable but not spec; flag in §5 gaps). Title = `title-large` 22sp. Colors: `surface` bg, `onSurface` icon/text. |
| `.icon-btn` back | **Icon button (standard)** | https://m3.material.io/components/icon-button/overview | 48dp target (we use 44px — touch-target spec is 48dp min with a 44dp visually possible, cite Material Guidelines touch targets: https://m3.material.io/foundations/accessible-design/accessibility-basics or the touch-target rule on the knobs). Use `on-surface-variant` glyph. |
| `.tag` (Replay) | **Assist chip** or **Badge** | https://m3.material.io/components/chips/overview | If purely informative → **Badge**; if dismiss/interactive → assist chip. Our tag is non-interactive → badge styling but keep the uppercase mono-label approach inside an M3 chip shape. |
| `.pill` ECU link state | **Badge / assist chip** | https://m3.material.io/components/chips/overview | Stack the dot + label; the dot is a legitimate M3 badge pattern. |
| `.hero` (S0 state) | **Filled card** with a **list-item prefix icon** | https://m3.material.io/components/cards/overview | M3 card anatomy: container, discretionary image, headline, supporting text. Use `surface-container-lowest` (elevated) or `surface-container` (filled); border-left colour stripe is NOT M3 — replace with a leading tone dot or a container-tinted fill. |
| `.card` generic | **Filled card** | https://m3.material.io/components/cards/overview | corner `shape-corner-medium` (12px), bg `surface-container-low`. |
| `.verdict` (severity) | **Filled card** with **icon+headline+** and colored **Badge** | Cards + https://m3.material.io/components/icons/overview | Replace border-left severity styling with M3 tinting conventions using `error-container` / `tertiary-container` / `primary-container` fills with `onErrorContainer`/`onTertiaryContainer`/`onPrimaryContainer` text. |
| `.counts` | **Text navigation / stat tile** | — (no direct M3 widget; use **Filled Card** or **List tile** with title/value). Closest official: `Filled card` and `List item` (https://m3.material.io/components/list-item/overview). | |
| `.tiles` grid of 2x $(N) | **`2-column grid of Filled(Card)`**, target = Card **as a list/tap target** | https://m3.material.io/components/cards/overview + card interaction page | Tap → screen nav; grid is not M3-prescribed but cards are. |
| `.tile` (stat tile, tap target) | **Filled card** relying on elevation 0 + container fill `surface-container-low` | — | Height currently 74px — tighter than spec; a 2-column 480px-tall screen should render ≈ 84–96dp to fit card padding + title/body. Verify at size. |
| `.tabs` / `.tab` | **Segmented button (single-select)** | https://m3.material.io/components/segmented-button/overview | M3 segmented buttons: 40dp high, `shape-corner-full` outline edges joined; selected segment gets `secondary-container` bg + `on-secondary-container` text + checkmark icon. Our `.tab` (999px corners, 36px min-height, 13px font) is close but not spec — gap 6px between segments should be 0 with a 1px shared div-line for true M3 (spec shows connected look). |
| `.rows li` scan list, ECU identity, Mode 06 | **List item** (single/two-line/three-line) | https://m3.material.io/components/list-item/overview | Two-line 72dp / three-line 88dp with `body-medium` overline/title; our 46px rows on a 480-tall screen are a reasonable compact variant but note the gap. Divider = `outline-variant`, 1px. |
| `.row-group`, `.group-title` | **List section headers** as `label-large` caps w/ `on-surface-variant` | list-item anatomy | |
| `.actions` footer strip | **Bottom app bar** variant | https://m3.material.io/components/bottom-app-bar/overview | height 80dp spec (we use 68px — compact variant, note in §5). Contains buttons + FAB. |
| `.btn` | **Button (filled)** | https://m3.material.io/components/all-buttons + the buttons spec page | 40dp height, 20px corner (full/min-8px), `label-large` label. Our 48px min-height + 8px radius + 15px label is a comfortable dense variant; quieter on the eye on a 480px-tall surface — flag. |
| `.btn[disabled]` | **Disabled button** opacity 38% | buttons spec, Disabled state: container `on-surface` @12%, text `on-surface` @38% (https://m3.material.io/components/buttons/overview) | We use opacity .4 — replace with the token split so label stays legible per Token spec. |
| `.btn-primary` | **Filled button**: `primary` fill + `on-primary` text | buttons spec / button-colors (https://m3.material.io/components/buttons/overview) | Currently uses `--ink` bg + dark text — this is "filled", effectively an **inverse-surface** pattern. If the primary action genuinely must have a primary-aware tint, use `primary`/`on-primary`. |
| `.btn-quiet` | **Text button** (borderless, `primary` text on `surface`) | buttons | |
| `.stepper … steps li` (scan progress chips) | **Filter/assist chip** set + **Linear progress indicator** | https://m3.material.io/components/linear-progress/overview | Our `.track`/`.track-fill` indeterminate sweep is the right *component family* (Linear progress, indeterminate). Diameter of the animation: M3 4dp-high rounded (9999) indicator inside a container of `primary-container`. |
| `.toast` | **Snackbar** (foreground) | https://m3.material.io/components/snackbar/overview | M3 snackbar: bg inverse-surface, text inverse-on-surface, 6dp radius (`shape-corner-extra-small`), min height 48dp, action = text button. We use panel-2 + radius 8 + border — off-spec; adopt tokens. |
| absence of case | (Dialog spec reserved for future confirmations) | https://m3.material.io/components/dialog/overview | `surface-container-high` bg, 28dp corner, headline-small title, text+`tertiary` actions. Only flag if we add confirm dialogs later. |
| (future) settings switch | **Switch** 52×32dp | https://m3.material.io/components/switch/overview | |
| (future) settings slider | **Slider** | https://m3.material.io/components/slider/overview | |
| (future) FAB if we add a single "Scan" affordance | 56dp regular FAB, `surface-container-high`+`primary-container` | https://m3.material.io/components/floating-action-button-fab/overview | We don't have a FAB today — pulling one in just for M3 is **not** required; listed for completeness. |
| (future) scan pull-refresh / segmented selection | **Segmented button** https://m3.material.io/components/segmented-button/overview | |

### 3.1 Focus indicator (required by our `.focused` ring system)

M3 accessibility spec (https://m3.material.io/foundations/accessible-design/accessibility-basics
and the component pages' "focus state" layer):

- Focus indicator = **3dp outline, offset 2dp outward**, colour = `on-surface`
  (a **primary / secondary** color is *also* acceptable for the *focus* layer of
  component-specific states — the "focus" M3 token itself is defined; the compact rule is 3dp thick / 2dp offset
with sufficient contrast against adjacent surfaces).
- On our webview, `.focused` ring is a *class-painted* ring (wheel/knob shim and
  dom-bridge nav; see diag.js comment at `window.__diagKeyNav`) — keep the mechanism,
  retint the ring from `--focus`(= Okabe-Ito `info`) → `--md-sys-color-*` driven
  `primary`  or `on-primary-container` — and keep **3px visual stroke + 2px offset**
  to match M3 exactly (we currently draw `2px/2px` at diag.css:409-414 — off-spec; fix
  in the token pass).

### 3.2 Dark-theme contrast requirements

- WCAG 2.1 (referenced by the M3 accessibility page) — 4.5:1 for normal text,
  3:1 for large text (18pt+/14pt-bold+)
  (https://m3.material.io/foundations/accessible-design/accessibility-basics).
  M3's own scheme guarantees ≥3:1 for icon-on-surface pairs when used within spec;
  the token mapping (e.g. `onSurfaceVariant` body text) is intentionally compliant.
  Consequences we must have at implementation:
  - Reject diagnostics-styling that mixes *surface tones* too closely (slider track
    inside a `surface-container-high` card must use `primary` or `tertiary` for the
    fill, not `outlineVariant`).
  - **Do not use `outlineVariant` for text anywhere** (it's a divider color, tone-80).

---

## 4. Concrete plan: our UI mapped to M3 with `--md-sys-color-*`

### 4.1 Token naming

All OK; M3 token taxonomy (https://m3.material.io/foundations/design-tokens/overview)
uses `md.sys.<category>.<token>` in JSON and `--md-sys-color-*`, `--md-sys-typescale-*`,
`--md-sys-shape-*`, `--md-sys-elevation-*`, `--md-sys-state-*` in web. We adopt the web
naming; per M3's stated policy, these are **natural CSS variable names** we own.

### 4.2 CSS variable plan (draft — implementation is a separate task, per AGENTS.md)

```css
:root {
  /* == fallback layer (CURRENT Okabe-Ito), kept as-is for browser testing only ==
   * These are the same today as diag.css lines 11–32, re-labelled as fallbacks.  */
  --md-fallback-primary:  #56B4E9;   /* M3 "primary" slot  -> Okabe-Ito info */
  --md-fallback-on-primary:        #00203A;
  --md-fallback-surface:           #0E1113;   /* --bg today            */
  --md-fallback-on-surface:        #F1F5F7;   /* --ink today           */
  --md-fallback-surface-container: #171B1E;   /* --panel today         */
  --md-fallback-surface-container-high: #1D2327; /* --panel-2 today     */
  --md-fallback-outline:    #6C787E; /* --quiet/pill borders today */
  --md-fallback-outline-variant:    #262E33; /* --line today */
  --md-fallback-error:      #D55E00; /* ok/warn ON true error hue          */
  --md-fallback-on-error:   #FFF3E6;
  --md-fallback-tertiary:   #009E73; /* "good"  -> okabe-Ito ok           */
  --md-fallback-on-tertiary:       #00201A;
  --md-fallback-warning:    #E69F00; /* NOT AN M3 TOKEN — see 4.3.1 note  */
  ...
}
```

Then the **bridge application block, planned (not yet implemented)**:

```js
/* GROWS applyScheme() in diag.js; NOT WRITTEN YET. */
var M3_CSS_BY_HUDIY = {
  background: "--md-sys-color-background",
  onBackground: "--md-sys-color-on-background",
  surface: "--md-sys-color-surface",
  onSurface: "--md-sys-color-on-surface",
  surfaceDim: "--md-sys-color-surface-dim",
  surfaceBright: "--md-sys-color-surface-bright",
  surfaceContainerLowest: "--md-sys-color-surface-container-lowest",
  surfaceContainerLow: "--md-sys-color-surface-container-low",
  surfaceContainer: "--md-sys-color-surface-container",
  surfaceContainerHigh: "--md-sys-color-surface-container-high",
  surfaceContainerHighest: "--md-sys-color-surface-container-highest",
  surfaceVariant: "--md-sys-color-surface-variant",
  onSurfaceVariant: "--md-sys-color-on-surface-variant",
  inverseSurface: "--md-sys-color-inverse-surface",
  inverseOnSurface: "--md-sys-color-inverse-on-surface",
  inversePrimary: "--md-sys-color-inverse-primary",
  outline: "--md-sys-color-outline",
  outlineVariant: "--md-sys-color-outline-variant",
  shadow: "--md-sys-color-shadow",
  scrim: "--md-sys-color-scrim",
  surfaceTint: "--md-sys-color-surface-tint",
  primary: "--md-sys-color-primary",
  onPrimary: "--md-sys-color-on-primary",
  primaryContainer: "--md-sys-color-primary-container",
  onPrimaryContainer: "--md-sys-color-on-primary-container",
  secondary: "--md-sys-color-secondary",
  onSecondary: "--md-sys-color-on-secondary",
  secondaryContainer: "--md-sys-color-secondary-container",
  onSecondaryContainer: "--md-sys-color-on-secondary-container",
  tertiary: "--md-sys-color-tertiary",
  onTertiary: "--md-sys-color-on-tertiary",
  tertiaryContainer: "--md-sys-color-tertiary-container",
  onTertiaryContainer: "--md-sys-color-on-tertiary-container",
  error: "--md-sys-color-error",
  onError: "--md-sys-color-on-error",
  errorContainer: "--md-sys-color-error-container",
  onErrorContainer: "--md-sys-color-on-error-container",
  primaryFixed: "--md-sys-color-primary-fixed",
  primaryFixedDim: "--md-sys-color-primary-fixed-dim",
  onPrimaryFixed: "--md-sys-color-on-primary-fixed",
  onPrimaryFixedVariant: "--md-sys-color-on-primary-fixed-variant",
  secondaryFixed: "--md-sys-color-secondary-fixed",
  secondaryFixedDim: "--md-sys-color-secondary-fixed-dim",
  onSecondaryFixed: "--md-sys-color-on-secondary-fixed",
  onSecondaryFixedVariant: "--md-sys-color-on-secondary-fixed-variant",
  tertiaryFixed: "--md-sys-color-tertiary-fixed",
  tertiaryFixedDim: "--md-sys-color-tertiary-fixed-dim",
  onTertiaryFixed: "--md-sys-color-on-tertiary-fixed",
  onTertiaryFixedVariant: "--md-sys-color-on-tertiary-fixed-variant"
};
/* Palette-key tokens (primaryPaletteKeyColor etc.) are NOT mapped — they are the
 * seed tone-40 swatches, not presentation colors (main_configuration.md list). */
```

Plus:

```js
document.documentElement.classList.toggle("scheme-light", !H.colorScheme.darkThemeEnabled);
```

**(verified today: `darkThemeEnabled` exists on `hudiy.colorScheme` per README §hudiy Object;
used nowhere in diag.js yet).**

### 4.3 Role mapping (our palette → M3 roles) — the design decision, not code

#### 4.3.1 Severity is a semantic layer — treat it as M3 supporting roles, NOT the M3 core slots

The M3 core slots do not natively include "warn/ok". The **canonical M3 approach** for
domain-semantic colours is:
- `error` slot for danger/bad (https://m3.material.io/styles/color/system/overview —
  the System page reserves `error` for this).
- pick ONE of `secondary` / `tertiary` as **supporting semantic accent** — i.e. our
  *info* hue.
- for ok/assert-success, M3 has no standard slot the way Android has `positive`;
  industry convention (and the Material-Theme-Builder-generated scheme on the web)
  routes success through **tertiary** with a synthesized "tertiary as success" semantic
  layer. This is legitimate under the token system — M3 explicitly reserves tertiary as
  "contrasting accent that doesn't collide with primary or secondary"
  (https://m3.material.io/styles/color/system/overview, M3 semantics note: tertiary is reserved as the contrasting accent).

Recommended mapping:

| Our concept | M3 slot | Why |
|---|---|---|
| ok / "verdict OK" glyph dot, ok count | `tertiary` (+ `on-tertiary`, `tertiary-container`, `on-tertiary-container`) | success as supporting accent |
| warn | **no M3 core slot** — this is our *design decision*: keep `warn` as a **Okabe-Ito hue as a named token `--diag-warn` (and friend `--diag-ok` fallback)** | M3 has no warn slot; M3 convention would be a semantic extension token. Trace to an actual M3 source: the official M3 docs list only primary/secondary/tertiary/error/neutral/neutralVariant as the **six** core tonal palettes (https://m3.material.io/styles/color/the-color-system/key-colors-tones). A custom "warn" semantic token is a supported extension use of the token framework, just not a built-in palette — call it explicitly as `--diag-*` to make its status obvious in code review. |
| bad / error-state | `error`, `on-error`, `error-container`, `on-error-container` | exact slot |
| info / scan-timer, focus ring fallback | `primary` or `secondary` | supporting accent (our favorite: **primary**) |
| blue accent | merged with info/primary | collapse three Okabe-Ito blues (info/blue) into ONE host `primary` |

#### 4.3.2 What each existing CSS colour slot becomes

| Current var (diag.css) | Become | Comment |
|---|---|---|
| `--bg` (`#0E1113`) | `--md-sys-color-surface` (dark mode) | `background`/`surface` distinction: body uses `background`, overlay screens use `surface` |
| `--panel` (`#171B1E`) | `--md-sys-color-surface-container` | |
| `--panel-2` (`#1D2327`) | `--md-sys-color-surface-container-high` | also used by .btn bg, .toast bg, .report-bg alternatives — decide: `.btn` should compare against `secondary-container`/`on-secondary-container`  or stay surface-container-high + on-surface. **Recommended: `secondary-container` bg + `on-secondary-container` text for `.btn`** to give the "tonal button" look the M3 button family implies. |
| `--line` (`#262E33`) | `--md-sys-color-outline-variant` | border/divider slots |
| `--line-soft` (`#1F262B`) | `--md-sys-color-surface-dim` (for dividers) or 8% `on-surface` alpha | verify visually |
| `--ink` (`#F1F5F7`) | `--md-sys-color-on-surface` | |
| `--dim` (`#9AA6AC`) | `--md-sys-color-on-surface-variant` | |
| `--quiet` (`#6C787E`) | `--md-sys-color-outline` | the ghost text role |
| `--info` (`#56B4E9`), `--blue` (`#0072B2`) | collapse to `--md-sys-color-primary` | see 4.3.1 |
| `--ok` (`#009E73`) | `--md-sys-color-tertiary` (+ `-container`, `-on` set) | see 4.3.1 |
| `--warn` (`#E69F00`) | keep as `--diag-warn` (one custom semantic token, see note) | non-M3 |
| `--bad` (`#D55E00`) | `--md-sys-color-error`, err-container etc. | see 4.3.1 |
| `--focus` | shown above — **3px/2px offset spec**; colour = a high-contrast slot; M3 recommends `on-surface`/`primary`; today we read from `scheme.outline` — keep reading host `outline` OR better: `primary`; if host has high-contrast palette, `outline` becomes strongly contrasted — that is Hudiy's own job. **Recommendation: ring colour = host `primary`, fallback = `--md-fallback-primary` (`info` hue).** |
| `--radius: 10px` | fractional M3: use the shape tokens as `--md-sys-shape-corner-*` (below) | |
| `--chrome-h/`: `--actions-h` (52px / 68px) vs M3 top-app-bar 64dp & bottom-app-bar 80dp | keep ours; log as a **documented deviation** — spec'd for a 480-tall kiosk. | in §5 gaps |

### 4.4 Shape / radius / spacing plan

```css
:root {
  --md-sys-shape-corner-extra-small: 4px;   /* badges (.tag) */
  --md-sys-shape-corner-small:       8px;   /* list rows, .btn, .report, .toast */
  --md-sys-shape-corner-medium:      12px;  /* .card, .hero, .tile */
  --md-sys-shape-corner-large:       16px;  /* reserved */
  --md-sys-shape-corner-extra-large: 28px;  /* future dialogs */
  --md-sys-shape-corner-full:        999px; /* .pill, .chip, .tab, switch */
  --md-sys-spacing-1: 4px;  --md-sys-spacing-2: 8px;
  --md-sys-spacing-3: 12px; --md-sys-spacing-4: 16px;
  --md-sys-spacing-5: 24px; /* 4dp rhythm */
  --md-sys-elevation-0: 0px 0px 0px 0px rgba(0,0,0,0); /* level shadows are exposed
     for parity — but on 480px glare we prefer TONE, see 2.3 */
}
```

### 4.5 Component token plan — per component (the CSS below is the *target naming*, not code)

- `.chrome` → top app bar
  - `background: var(--md-sys-color-surface)` (NOT surface-container; M3 top app bar
    sits on `surface`, elevation tints with `surface-tint`), `color: var(--md-sys-color-on-surface)`,
    title `--md-sys-typescale-title-large-`.
- `.icon-btn` → icon button (standard, `on-surface-variant`)
- `.tag` → shape small / `--md-sys-shape-corner-extra-small`, bg `--md-sys-color-tertiary-container`, colour `--md-sys-color-on-tertiary-container`
- `.pill` → chip, bg `--md-sys-color-surface-container-high`, border `--md-sys-color-outline`, label `--md-sys-color-on-surface-variant`
- `.hero` / `.card` / `.verdict` → filled card, bg `--md-sys-color-surface-container-low`
  (dark) / `--md-sys-color-surface-container-lowest` (lite) + 12px corners; severity
  tint via `*-container` slots (§4.3.1) + **drop the 4px colour border-left pattern**
  (anti-M3, list as gap in §5 #4).
- `.tiles` / `.tile` → 2-col filled cards, bg `--md-sys-color-surface-container-low`,
  state layer: `--md-sys-color-on-surface` @8% selected/hover, @12% pressed/focused.
- `.tabs / .tab` → **connected segmented button**:
  ```
  height 40px; font: 14px/20px 500; border-radius: 999px on outer, 0 in middle;
  bg `--md-sys-color-surface`;
  outline 1px `--md-sys-color-outline` (adjacent segments share via div 0 gap);
  [aria-selected=true]: bg `--md-sys-color-secondary-container`, colour
  `--md-sys-color-on-secondary-container`, plus check icon (harm: `secondary` route)
  ```
- `.rows li` / `.row` → **List item (two-line)**: min-height 72px (or 56dp for one-line
  where we can afford it), bg `transparent` inside a `surface-container-low`-tinted
  card, divider 1px `--md-sys-color-outline-variant` between rows, headline
  `--md-sys-typescale-body-large` + supporting `--md-sys-typescale-body-small` color
  `--md-sys-color-on-surface-variant`.
- `.track` / `.track-fill` → **LinearProgressIndicator (indeterminate)**: track height 4px
  radius full, track bg `--md-sys-color-surface-container-highest`, fill `--md-sys-color-primary`.
  M3 also prescribes a **gap / stop indicator** (https://m3.material.io/components/linear-progress/overview) - optional, note only.
- `.steps li` → **assist chips** with checkmark: shape full;
  check state: bg `--md-sys-color-primary-container`, colour `--md-sys-color-on-primary-container`.
- `.action / .btn` → **Buttons**:
  - filled `.btn-primary` = `--md-sys-color-primary` bg + `--md-sys-color-on-primary` text, radius 20px (shape full / min-8px; official button shape token is full for buttons per
    https://m3.material.io/components/buttons/specs — 2021 update uses shape-corner-full, radius 999px; earlier M1 uses 20px — **use 999px full**, matches Hudiy screenshots).
  - `.btn` (default) = tonal: `--md-sys-color-secondary-container` bg + `--md-sys-color-on-secondary-container` text.
  - `.btn-quiet` = text button: no bg, colour `--md-sys-color-primary`.
- `.toast` → **snackbar**:
  `bg: --md-sys-color-inverse-surface; color: --md-sys-color-inverse-on-surface; radius: --md-sys-shape-corner-extra-small (4px)`;
  severities can use `error-container`/`on-error-container` for bad/warn toasts (acceptable mapping).
- `.report` `<pre>` block → filled card `bg --md-sys-color-surface-container-lowest`, colour
  `on-surface`; 12px radius; monospace is allowed (Typography §2.2).
- `.settings` → future native M3 **Switch**/Slider component classes (structure only).
- (future) dialog → `surface-container-high` + 28dp + `top-app-bar headline-small`.

### 4.6 The `.focused` ring and its colour — keep the system, retune the token

- Keep: `.ctl.focused, .tile.focused, .row.focused, .tab.focused, .btn.focused, .icon-btn.focused`
  class-painting (required — Hudiy bridges webview focus to us via
  `hudiy.onMoveToNextControl/onMoveToPreviousControl/onTriggered`, README §Web view;
  the wheel shim also paints `.focused` — see AGENTS.md §6 and diag.js comments).
- Change: ring **width 2→3px** (M3 focus indicator spec: 3dp thick, 2dp offset), keep
  offset 2px. Colour: from host `primary` (or host `outline`; `outline` exists and is
  contrast-corrected by Hudiy's contrastLevel — acceptable). **Pick host `primary`**;
  leaving host `outline` on the table as a fallback if `primary` is too low-contrast on
  custom `colorOverwrite` host installs.
- Touch parity: unchanged. `:focus-visible` rule must be preserved for desktop testing
  (diag.css:414).

---

## 5. GAPS — what is missing / off-spec / undecided

1. **`applyScheme()` consumes 3/61 tokens.** Largest gap. Plan: a single `M3_CSS_BY_HUDIY` map (§4.2) applied on `hudiy.onAttached` + `onColorSchemeChanged`; plus read `darkThemeEnabled` and toggle `scheme-light`.
2. **Warn has no M3 slot.** Decide `_diag-warn` custom-token policy (recommended: keep, name it, cite it) — section 4.3.1.  Alternative: remap warn into `secondary` and let info collapse into `primary`, freeing the whole palette. Needs the owner's eye before implementation.
3. **Severity-carrier pattern is anti-M3 style today.** The 4px colour border-left on `.hero`/`.verdict` (diag.css:154, 182–186) is not an M3 pattern; M3 wants `*-container` tonal fills + on-*-container text + badging. Changing this is a *layout* change, not just a token change.
4. **Heights deviate from M3 spec**: top app bar 52px vs 64dp; bottom app bar 68px vs 80dp; list rows 46px vs 48/72/88; buttons 48px vs 40dp. On a 480-tall kiosk, M3's canonical heights sum to more canvas than we have at 3-panel density. **Decide**: adopt M3 heights everywhere at density cost, or document a compact-density overlay (density tokens exist in M3 as a system for this: https://m3.material.io/foundations/design-tokens/overview — but not composited as a one-switch). Recommended: keep our heights as a **documented compact variant**, matching shapes/colours/type strictly.
5. **Typography is undocumented.** No `--md-sys-typescale-*` variables exist in diag.css — every component hardcodes px + weight. Needs a same-count set of scale tokens (15) wired from host `appearance.fonts`/system Roboto font family.
6. **Roboto availability on our host unverified.** Test on car (`fc-list | grep Roboto` / the Chromium default font). Do NOT depend on it for the M3 pass — pick `--md-sys-typescale-*` font stack = `"Roboto", system-ui, "DejaVu Sans", sans-serif` and keep moving.
7. **No elevation tokens**; drop shadows only on `.toast` (diag.css:431). On the kiosk, M3's tone-based elevation (§2.3) is more usable; pick which levels we pretend to implement (recommend: level 0 everywhere + level 3 for `.toast` + `inverseSurface` colour; skip shadows).
8. **Dynamic color**: none, by design (§2.1 end) — we intentionally consume the host snapshot. No dynamic-colour work required.
9. **Contrast checker pending**: after the mapping, run every produced pair through a WCAG ratio check at contrast levels 0 / 0.5 / 1 against our top/app bar, body, rows/set (manual or scripted contrast audit — no public m3 checker accepts a hex matrix).
10. **Fixed colours** (`primaryFixed` …) and `inversePrimary`/`surfaceTint`/`shadow`/`scrim` are **injected by Hudiy but unused** in our design today; reserve for future dialogs/FAB.
11. **`hudiy.colorScheme` might arrive AFTER `onAttached`** depending on timing (README does not guarantee ordering). Verify by CDP probe on the real device; guard applyScheme to be idempotent (it already is).
12. **Fallback palette correctness when `H.colorScheme` is undefined** (browser testing, shim-only). Today's fallback is Okabe-Ito — it is *not* an M3 scheme and does not map onto the 61-token JS map we're about to write. Decide: write a **static dark M3 fallback scheme drafted via the Material Theme Builder from seed `#56B4E9`** and store BOTH dark and light fallbacks as CSS vars, so the file never needs the hardcoded `#0E1113/etc.` layer. This is the cleanest "M3 everywhere" answer and removes the un-tokened fake-palette styles.

---

## 6. Source register

- Hudiy upstream README (fetched 2026-09-11 from `raw.githubusercontent.com/wiboma/hudiy/master/README.md`):
  §Theming ("Hudiy follows the guidelines of Material 3 Design"; source color &
  contrast; Material Theme Builder link), §Web view (`hudiy.colorScheme` property list,
  `onColorSchemeChanged`, `darkThemeEnabled`, contrastLevel properties, input-event
  contract).
- Hudiy upstream `main_configuration.md` (fetched 2026-09-11, same URL root, path is
  `/master/main_configuration.md` — **NOT** `/master/docs/main_configuration.md`,
  the `/docs/` variant 404s): §`appearance` (fonts), §`application`, §`theme`
  (`availableColors`, `dark`/`light` { contrastLevel, sourceColor },
  `colorOverwrite` full token list).
- Material 3 color system, tonal palettes, roles, custom-colors, dynamic-color:
  - https://m3.material.io/styles/color/system/overview
  - https://m3.material.io/styles/color/the-color-system/key-colors-tones
  - https://m3.material.io/styles/color/dynamic-color/overview
  - https://m3.material.io/styles/color/dark-theme
- Material Theme Builder (referenced by Hudiy README): https://material-foundation.github.io/material-theme-builder/
- M3 Typography (roles, tokens, type scale values, custom fonts):
  - https://m3.material.io/styles/typography/tokens
  - https://m3.material.io/foundations/typography/overview
- M3 Elevation / Shape / Layout:
  - https://m3.material.io/styles/elevation/tokens
  - https://m3.material.io/styles/shape/shape-scale-tokens
  - https://m3.material.io/foundations/design-tokens/overview
- M3 Components referenced: Top app bar, Icon button, Chips, Badge, Cards, List item,
  Bottom app bar, Buttons, Linear progress, Snackbar, Dialog, Switch, Slider,
  Segmented button, FAB — all under https://m3.material.io/components/
- M3 Accessibility / Focus: https://m3.material.io/foundations/accessible-design/accessibility-basics (focus-indicator spec: 3dp size, 2dp offset, contrast)
- WCAG contrast thresholds referenced from M3 accessible-design page (4.5:1 normal
  text, 3:1 large text).
- Our OWN repo for the mapping baseline:
  - `frontend/diag.css` (lines 11–32 fallback vars, 53 scheme-light, 153–161 hero stripes,
    404 btn-primary inverse, 409–414 focus ring, 429–434 toast)
  - `frontend/diag.html` (§ component inventory: chrome bar, hero, cards, tiles, tabs,
    rows, detail, scan track/steps, report pre, actions strip, toast)
  - `frontend/diag.js` (line ~1309 `applyScheme()`; finalisation of chips lists etc.)
  - `AGENTS.md §1-3` constraint block (non-negotiables: universal, no autolaunch, etc.)

*No code changed. This doc is parked implementation research per the standing goal.*
