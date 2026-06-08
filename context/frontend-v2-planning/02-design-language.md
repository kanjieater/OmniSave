# 02 — Design Language

## Product Identity

OmniSave is infrastructure software for a specific, technical audience: people who run their own gaming infrastructure, value data ownership, and understand that saves are irreplaceable. It is not a consumer app. It is not a SaaS dashboard.

The closest analogues in feel and philosophy are: **Tailscale**, **Proxmox**, **Warp terminal**, **Linear**, and **GitHub**.

---

## Visual Principles

### 1. Materiality over flatness
Surfaces have weight. Depth comes from layered surface tones and fine border treatments, not heavy drop shadows. The UI should feel like it has substance — like hardware or a well-machined instrument.

### 2. Typography carries the hierarchy
Font weight, size, and spacing communicate what matters. Color is used sparingly for state (status, error, success), never for decoration.

### 3. Data density is respect
Operators value dense information. Whitespace serves readability, not aesthetic padding. Every pixel of viewport should earn its place.

### 4. Calm precision
Animations are purposeful and brief. Nothing bounces or swoops. Motion communicates state change, not delight.

### 5. Technical honesty
IDs, hashes, and timestamps are real data. They are formatted for readability (truncated, monospaced, copyable) — not hidden in shame. The UI respects users who want to see raw data.

---

## Emotional Goals

| Feeling | Achieved by |
|---------|-------------|
| Trustworthy | Consistent visual language, stable layouts, no surprises |
| In control | Dense information, clear actions, no ambiguous states |
| Competent | Terminology that matches domain knowledge, not dumbed down |
| Safe | Error states are visible and actionable, not buried |
| Fast | Interactions respond instantly; loading states are minimal |

---

## Aesthetic References

| Reference | What we borrow |
|-----------|---------------|
| Tailscale dashboard | Dark surface hierarchy, restrained color, network topology visualization |
| Linear | Typography-first density, keyboard-first interactions, status chips |
| Warp terminal | Monospace code regions, dark materiality, technical confidence |
| Proxmox | Information density, no-nonsense layout, operational clarity |
| GitHub Actions | Timeline / log visualization, status semantics (green/red/amber/grey) |
| Obsidian | Multi-layer dark surfaces, subtle texture, focused workspace |
| Vercel dashboard | Clean metric rows, deployment status indicators, restrained type |

---

## Typography System

### Typefaces

**UI Text:** Inter (variable, 100–900 weight)
- Used for all UI chrome, labels, body text, and navigation.
- Variable font allows fine-grained weight control without loading multiple files.

**Code / IDs / Hashes:** JetBrains Mono (or system monospace fallback: `ui-monospace, 'Cascadia Code', 'Source Code Pro', Menlo, Consolas, monospace`)
- Used for: transaction_id, device_id, SHA256, sequence numbers, timestamps in detail views.
- Never used for UI labels.

### Scale (rem-based, 16px root)

```
--text-xs:   0.6875rem   (11px) — metadata labels, timestamps in dense rows
--text-sm:   0.8125rem   (13px) — secondary body, table cells, helper text
--text-base: 0.9375rem   (15px) — primary body, navigation labels
--text-md:   1.0625rem   (17px) — section headers, card titles
--text-lg:   1.25rem     (20px) — page titles, modal headers
--text-xl:   1.5rem      (24px) — dashboard hero numbers
--text-2xl:  2rem        (32px) — reserved for empty state callouts
```

### Weight usage

```
400 — body text, table cells, secondary labels
500 — primary labels, navigation items
600 — section headers, status badges, card titles
700 — page titles, hero numbers, emphasized data
```

### Line height

UI text: 1.4 (dense but readable)
Long-form descriptions: 1.6
Single-line labels: 1.0 (tight)

### Letter spacing

Uppercase labels and status badges: `0.06em`
Normal text: `0` or `-0.01em` for large sizes

---

## Color System

### Philosophy
Dark-first. The interface lives in a controlled environment (home server admin dashboard, often accessed at night or in a dim room). A warm-tinted dark palette reduces eye strain and reads as intentional, not default.

Accent color is a single blue-green (teal) hue. All other color usage is semantic (error, warning, success, info) or surface-hierarchy.

### Base Palette

```
-- Backgrounds (dark surfaces, warm undertone) --
--color-bg-base:       #0C0D10   /* page background, absolute floor */
--color-bg-subtle:     #111318   /* primary surface (cards, panels) */
--color-bg-elevated:   #191C23   /* raised surface (dropdowns, popovers) */
--color-bg-overlay:    #1F2330   /* modal overlays, tooltips */
--color-bg-hover:      #242838   /* hover state for interactive rows */
--color-bg-selected:   #1E2540   /* selected row, active nav item */

-- Borders --
--color-border-subtle: #1E2028   /* barely-there dividers, surface separation */
--color-border-base:   #2A2D38   /* standard borders, inputs */
--color-border-strong: #3D4255   /* focus rings, active borders */

-- Text --
--color-text-primary:  #E8EAF0   /* primary content */
--color-text-secondary:#9198AC   /* secondary labels, metadata */
--color-text-muted:    #585E72   /* disabled, placeholder */
--color-text-inverse:  #0C0D10   /* text on accent/colored backgrounds */

-- Accent (single hue: blue-teal) --
--color-accent:        #3B82F6   /* primary interactive elements */
--color-accent-subtle: #1E3A5F   /* accent background tint */
--color-accent-muted:  #2563EB   /* hover state of accent elements */
```

### Semantic Colors

```
-- Success (green, restrained) --
--color-success:        #22C55E
--color-success-subtle: #0F2A1A
--color-success-border: #166534

-- Warning (amber, not orange) --
--color-warning:        #EAB308
--color-warning-subtle: #2A1F06
--color-warning-border: #854D0E

-- Error (red, high contrast) --
--color-error:          #EF4444
--color-error-subtle:   #2A0A0A
--color-error-border:   #991B1B

-- Info (blue, distinct from accent) --
--color-info:           #60A5FA
--color-info-subtle:    #0F1F35
--color-info-border:    #1D4ED8

-- Neutral (for SUPERSEDED, UNKNOWN, disabled states) --
--color-neutral:        #6B7280
--color-neutral-subtle: #1A1C22
--color-neutral-border: #374151
```

### Status → Color mapping (OmniSave domain)

| Status | Color token | Usage |
|--------|-------------|-------|
| SYNCED / COMPLETED | `--color-success` | All devices converged |
| CONFLICT | `--color-warning` | Divergent branches exist |
| ERROR / FAILED | `--color-error` | Transaction failed |
| UPLOADING / PROCESSING | `--color-accent` | In-flight operation |
| NO_DATA / SUPERSEDED | `--color-neutral` | Inactive / historical |
| READY_FOR_RESTORE | `--color-info` | Pending delivery |
| DOWNLOADING | `--color-accent` | Active inbound |

---

## Elevation Strategy

No heavy drop shadows. Elevation is expressed through surface tone and border treatment.

```
Level 0 — page background:     --color-bg-base        (no border)
Level 1 — primary surface:     --color-bg-subtle       + 1px border --color-border-subtle
Level 2 — elevated surface:    --color-bg-elevated     + 1px border --color-border-base
Level 3 — overlay / popover:   --color-bg-overlay      + 1px border --color-border-strong
Level 4 — modal:               --color-bg-overlay      + 1px border --color-border-strong + backdrop
```

Shadow use: a single subtle shadow (`0 1px 3px rgba(0,0,0,0.4)`) is permitted at Level 3+ only. Never multiple layered shadows. Never colored shadows.

---

## Texture Strategy

### Grain / Noise Overlay
A monochromatic noise texture (2–4% opacity SVG or CSS noise filter) is applied to Level 1 surfaces only. This provides material depth without visual clutter.

Implementation: CSS `filter: url(#noise)` or a repeating SVG background pattern at ~120px tile size. Opacity: 2–3% on dark backgrounds.

### Inner Borders for Depth
Components use subtle inner top border (1px, `rgba(255,255,255,0.04)`) to simulate light catching the top edge — the standard technique used in Tailscale, Linear, and other high-quality dark UIs.

```css
/* Inner highlight border — top edge of cards */
box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.04);
```

### Radial focus treatment
Active/focused panels may use a very subtle radial gradient from the center of content (`rgba(59, 130, 246, 0.03)` to transparent) to draw visual attention without disrupting density.

---

## Animation Philosophy

**Rule: animate state, not decoration.**

| Interaction | Animation | Duration | Easing |
|-------------|-----------|----------|--------|
| Page transition | Fade + 4px Y translate | 150ms | ease-out |
| Panel open/close | Height + opacity | 200ms | ease-in-out |
| Status badge change | Cross-fade | 120ms | linear |
| Row hover | Background color | 80ms | linear |
| Modal appear | Scale 0.97→1 + opacity | 180ms | ease-out |
| Notification appear | Translate X from right | 200ms | spring (stiffness: 400, damping: 30) |
| Data refresh | None (silent) | — | — |
| Error pulse | Single opacity pulse (1→0.7→1) | 400ms | ease-in-out |

Never: infinite looping animations on idle UI, entrance animations on page load for data tables, animation on every keystroke.

**Reduced motion:** All animations collapse to instant opacity transitions when `prefers-reduced-motion: reduce` is active.

---

## Interaction Philosophy

### Keyboard-first
Every action reachable by keyboard. Tab order is logical. `Escape` dismisses. `Enter` confirms. `K` opens command palette (future).

### Hover is supplementary
Hover reveals secondary actions (copy button, quick edit). Primary actions are never hidden behind hover.

### Optimistic updates
Label edits and toggle changes apply immediately in the UI and revert on error. No full-page refreshes.

### Confirmation is contextual
Destructive actions (revoke device, delete snapshot) require a confirmation step. Non-destructive actions (rename, toggle sync) do not.

### Timestamps
- Relative time ("3 hours ago") in list views and feeds.
- Absolute time (ISO with timezone) in detail views, available on hover for relative times.
- Monotonically ordered sequence numbers (snapshot_sequence) displayed prominently alongside timestamps.

### IDs
- Device IDs: show first 8 chars + ellipsis with full value in tooltip and copy-on-click.
- Transaction IDs: same treatment.
- SHA256: first 12 chars visible, full value in tooltip.
- All ID regions use monospace font and cursor: pointer for copy.

### Empty states
Every list and table has a designed empty state with an icon, a title, and a description. Never a blank white space.
