# Visual identity

- **Chosen:** 2026-09-22, from the [theme picker](theme-picker.html)
- **Direction:** *OSH Purple*: purple hobbyist PCBs with gold fingers
- **Change from the picked direction:** code uses **Roboto Mono** (from *ESD Bench*)
  instead of Martian Mono

## Typography

| Role | Family | Weights | Used for |
| --- | --- | --- | --- |
| Display | **Oxanium** | 600, 700 | Logo, page titles, section headings, big numbers |
| Body | **Manrope** | 400, 600 | Everything else: text, tables, forms, buttons |
| Mono | **Roboto Mono** | 400, 500 | Firmware source, diffs, and technical identifiers (MPNs, designators `R1–R4`, pins `GPIO21`, short codes `LOC-7K2Q`, versions) |

Fallback stacks:

```css
--font-display: "Oxanium", system-ui, sans-serif;
--font-body: "Manrope", system-ui, -apple-system, "Segoe UI", sans-serif;
--font-mono: "Roboto Mono", ui-monospace, "SFMono-Regular", Menlo, monospace;
```

Fonts are **self-hosted** (e.g. `@fontsource/*` packages), not loaded from
Google Fonts at runtime. That keeps the CSP strict and works offline in the
mobile app.

Rules:

- Oxanium is for headings only and is never used for running text.
- Numbers that line up in columns (quantities, stock, prices) use
  `font-variant-numeric: tabular-nums`.
- Only one mono face. Anything a user might copy exactly is set in mono.

## Color

All pairs below meet WCAG 2.1 AA: 4.5:1 for text, and 3:1 for input borders
and focus rings.

### Light

| Token | Hex | Role | Contrast |
| --- | --- | --- | --- |
| `--bg` | `#f6f4fa` | App background | — |
| `--surface` | `#ffffff` | Cards, tables, panels | — |
| `--surface-2` | `#efebf6` | Hover rows, raised areas, code blocks | — |
| `--text` | `#1e1629` | Primary text | 17.5 on surface |
| `--muted` | `#655c73` | Secondary text, labels | 6.3 on surface |
| `--border` | `#e0dbe9` | Dividers (decorative) | — |
| `--border-strong` | `#8e84a0` | Input borders | 3.5 on surface |
| `--primary` | `#6b3fa0` | Actions, links, active nav, focus ring | 7.4 on surface |
| `--on-primary` | `#ffffff` | Text on primary | 7.4 |
| `--accent` | `#b8901a` | Gold highlights (fills, badges, never text) | — |
| `--accent-ink` | `#86680f` | Gold used as text | 5.2 on surface |

### Dark

| Token | Hex | Role | Contrast |
| --- | --- | --- | --- |
| `--bg` | `#120e1a` | App background | — |
| `--surface` | `#1b1526` | Cards, tables, panels | — |
| `--surface-2` | `#231c31` | Hover rows, raised areas, code blocks | — |
| `--text` | `#ece6f5` | Primary text | 14.6 on surface |
| `--muted` | `#a69cb6` | Secondary text, labels | 6.8 on surface |
| `--border` | `#2d2440` | Dividers (decorative) | — |
| `--border-strong` | `#75698f` | Input borders | 3.5 on surface |
| `--primary` | `#a67cf0` | Actions, links, active nav, focus ring | 5.7 on surface |
| `--on-primary` | `#150a26` | Text on primary | 6.1 |
| `--accent` | `#e6c35c` | Gold highlights | — |
| `--accent-ink` | `#ecd07c` | Gold used as text | 11.7 on surface |

### Semantic (status, not brand)

| Meaning | Light | Dark | Used for |
| --- | --- | --- | --- |
| `--ok` | `#1e7f4f` | `#4cc38a` | In stock, built, validation passed |
| `--warn` | `#a15f00` | `#f0b34a` | Low stock, netlist warnings, version mismatch |
| `--crit` | `#c0362c` | `#ff6b61` | Short, errors, destructive actions |

Status is never shown by color alone. It always comes with a label or icon
(`● 5 available · short`).

## Themes

Light, dark and **system** (the default). The token contract for the web app:

```css
:root {
  color-scheme: light;
  --bg: #f6f4fa; --surface: #ffffff; --surface-2: #efebf6;
  --text: #1e1629; --muted: #655c73;
  --border: #e0dbe9; --border-strong: #8e84a0;
  --primary: #6b3fa0; --on-primary: #ffffff;
  --accent: #b8901a; --accent-ink: #86680f;
  --ok: #1e7f4f; --warn: #a15f00; --crit: #c0362c;
}

/* System: follow the OS unless the user explicitly picked light */
@media (prefers-color-scheme: dark) {
  :root:not([data-theme="light"]) { /* dark tokens */ }
}

/* Explicit choice wins over the OS in both directions */
:root[data-theme="dark"] { /* dark tokens */ }
```

`data-theme` is set on `<html>` from the user's saved preference before first
paint (a tiny inline script), so the page never flashes the wrong theme.

## Syntax highlighting

Firmware source and diffs take their colours from the tokens above and add
none of their own, so dark mode follows them. `@lezer/highlight`'s
`classHighlighter` names each token with a class, and
[`syntax.css`](../../apps/web/src/features/firmware/source/syntax.css) styles
those classes from the site's own stylesheet, so the CSP's `style-src 'self'`
holds. Code boxes sit on `--surface`, framed by `--border`, not on
`--surface-2`, where `--ok` would fall to 4.3 in the light theme. Contrasts are
on `--surface`, measured from
[`tokens.css`](../../apps/web/src/shared/theme/tokens.css):

| Classes | Token | Style | For example | Light | Dark |
| --- | --- | --- | --- | --- | --- |
| `tok-keyword` | `--primary` | | `if`, `const`, `nullptr`; Python's `def` and `None`; JSON's `null` | 7.4 | 5.7 |
| `tok-string`, `tok-string2` | `--ok` | | `"ready"`, `'a'`, `<Wire.h>`, the `\n` in a string | 5.0 | 8.0 |
| `tok-number`, `tok-atom`, `tok-bool`, `tok-literal`, `tok-meta`, `tok-macroName` | `--accent-ink` | | `0x1F`, `true`, `#include`, `#define` and its value | 5.2 | 11.7 |
| `tok-comment` | `--muted` | italic | `// …`, `/* … */`, `# …` | 6.3 | 6.8 |
| `tok-typeName`, `tok-className`, `tok-namespace` | `--text` | weight 500 | `void`, `int`, `String`, a class's name | 17.5 | 14.6 |
| Every other class, and unstyled text | `--text` | | `LED` in `#define LED 13`, JSON keys, operators, punctuation | 17.5 | 14.6 |

Built-in types such as `void`, `int`, `bool` and `char` read as type names, as
the C++ grammar parses them: the type names' weight, not the keywords' colour.

A changed line in a diff keeps its text on `--surface`. Only its gutter, the
line numbers and the `+` or `−`, is tinted: `diff-gutter-added` with
`color-mix(in srgb, var(--ok) 16%, var(--surface))`, `diff-gutter-removed` with
the same mix of `--crit`. The marker and the word *added* or *removed* for
screen readers carry the change, so colour is never alone.

| Gutter | Numbers (`--muted`), light | Dark | Marker (`--text`), light | Dark |
| --- | --- | --- | --- | --- |
| `diff-gutter-added` | 5.1 | 5.1 | 14.1 | 11.0 |
| `diff-gutter-removed` | 4.9 | 5.4 | 13.7 | 11.5 |

## Still open

- [ ] Logo and favicon (the picker used a placeholder chip glyph)
- [x] Syntax-highlighting theme for CodeMirror derived from these tokens, in
  [Syntax highlighting](#syntax-highlighting)
- [ ] Spacing, radius and elevation scale
