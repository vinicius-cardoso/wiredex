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
| `--accent-ink` | `#86680f` | Gold used as text | 5.3 on surface |

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

## Still open

- [ ] Logo and favicon (the picker used a placeholder chip glyph)
- [ ] Syntax-highlighting theme for CodeMirror derived from these tokens
- [ ] Spacing, radius and elevation scale
