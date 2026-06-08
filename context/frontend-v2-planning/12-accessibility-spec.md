# 12 — Accessibility Specification

OmniSave V2 targets WCAG 2.1 Level AA compliance throughout.

---

## Standards

- **WCAG 2.1 AA** — minimum bar for all user-facing screens
- **ARIA 1.1** — correct role, property, and state semantics
- **Keyboard navigability** — every interaction reachable without mouse
- **Screen reader compatibility** — tested with NVDA (Windows) and VoiceOver (macOS)
- **Reduced motion** — all animations respect `prefers-reduced-motion`

---

## Contrast Requirements

All text must meet WCAG 2.1 AA contrast ratios:

| Context | Minimum ratio |
|---------|--------------|
| Normal text (< 18px) | 4.5:1 |
| Large text (≥ 18px or 14px bold) | 3:1 |
| UI components and graphical objects | 3:1 |
| Disabled elements | No requirement (clearly disabled) |

### Token contrast audit (against `--color-bg-base: #0C0D10`)

| Token | Value | Contrast vs base | Pass? |
|-------|-------|-----------------|-------|
| `--color-text-primary` | #E8EAF0 | 16.8:1 | ✓ AA/AAA |
| `--color-text-secondary` | #9198AC | 5.8:1 | ✓ AA |
| `--color-text-muted` | #585E72 | 3.1:1 | ✓ AA (large text) |
| `--color-text-disabled` | #3A3F52 | 1.9:1 | ✗ (expected — disabled state) |
| `--color-success` | #22C55E | 4.6:1 | ✓ AA |
| `--color-warning` | #EAB308 | 5.1:1 | ✓ AA |
| `--color-error` | #EF4444 | 4.8:1 | ✓ AA |
| `--color-accent` | #3B82F6 | 4.5:1 | ✓ AA (borderline — verify in use) |
| `--color-info` | #60A5FA | 5.9:1 | ✓ AA |

**Note on `--color-accent` (#3B82F6):** Exactly at the 4.5:1 threshold. Do not use accent text on the elevated surface (`--color-bg-elevated: #191C23`) for body text — only for interactive labels (buttons, links) at 14px+ where large-text 3:1 applies.

**Status indicators:** Never rely on color alone. Every status must include:
1. Color (dot, badge background)
2. Text label (SYNCED, CONFLICT, ERROR)
3. Icon (optional, but aids comprehension)

---

## Keyboard Navigation

### Global tab order

```
1. Skip-to-content link (hidden, reveals on focus — links to main content)
2. TopBar (notification bell, help)
3. SideNav items (top to bottom)
4. Main content area
5. Page-level actions
```

Skip-to-content link is the first focusable element on every page. Pressing Tab once from a fresh page focus should reach it.

### Navigation keyboard interactions

| Key | Action |
|-----|--------|
| `Tab` | Move forward through focusable elements |
| `Shift+Tab` | Move backward |
| `Enter` or `Space` | Activate button, link, toggle |
| `Escape` | Close modal, drawer, dropdown |
| `Arrow keys` | Navigate within composite widgets (menu, list) |
| `Home` / `End` | First / last item in menu or list |

### Table keyboard interactions

DataTable rows are navigable via keyboard:
- `Tab` to table
- `Arrow keys` to navigate rows
- `Enter` to navigate to row detail page
- Row actions (edit, delete): revealed via `Tab` within the focused row

### Modal keyboard behavior

1. On open: focus moves to the first focusable element inside the modal (or the modal title if no focusable element comes first).
2. Focus is **trapped** inside the modal. Tab cycles within the modal only.
3. On close (Escape, Cancel button, or successful action): focus returns to the element that triggered the modal.
4. Backdrop click: closes non-destructive modals. Destructive modals (ConfirmDialog) do not close on backdrop click.

### Lineage Graph keyboard behavior

The React Flow canvas is not keyboard-navigable (SVG canvas limitation).
Provide an accessible table alternative below the graph:

```html
<section aria-label="Save history table (accessible alternative)">
  <table>
    <caption>Save history for Zelda: TOTK — 12 saves</caption>
    <thead>
      <tr>
        <th>Save #</th>
        <th>Device</th>
        <th>Date</th>
        <th>Status</th>
        <th>Actions</th>
      </tr>
    </thead>
    <tbody>
      <tr>
        <td>#42</td>
        <td>Switch OLED</td>
        <td><time datetime="2026-05-28T14:32:00Z">2 hours ago</time></td>
        <td>Current</td>
        <td><button>Push to all devices</button></td>
      </tr>
      ...
    </tbody>
  </table>
</section>
```

This table is visually hidden (CSS `sr-only`) but accessible to screen readers and keyboard users who navigate to it.

---

## Screen Reader Support

### ARIA roles used

| Component | Role |
|-----------|------|
| SideNav | `navigation` + `aria-label="Main navigation"` |
| TopBar | `banner` |
| Main content | `main` |
| Footer | `contentinfo` |
| Modal | `dialog` + `aria-modal="true"` + `aria-labelledby` |
| Notification drawer | `dialog` + `aria-label="Sync errors"` |
| Alert banner | `alert` (assertive) for errors, `status` for informational |
| Data table | `table` with proper `th scope` attributes |
| Event timeline | `feed` (ARIA 1.1 live region) |
| Status badge | `status` (for updatable badges) |
| Toggle switch | `switch` + `aria-checked` |
| Loading spinner | `status` + `aria-label="Loading..."` |
| Empty state | `region` + `aria-label="No data"` |

### Live regions

Dynamic content that updates without page navigation must use live regions:

| Content | Live region type |
|---------|----------------|
| Dashboard poll updates | `aria-live="polite"` on stats container |
| Error badge count in nav | `aria-live="polite"` + `aria-label="N sync errors"` |
| Offline banner appear | `role="alert"` (assertive — user must know immediately) |
| Toast notifications | `role="status"` (polite) |
| Polling "last updated" timestamp | `aria-live="polite"` (polite, low priority) |

**Rule:** Use `assertive` only for genuine errors that require immediate user attention (offline, critical failure). Everything else is `polite`.

### Screen reader text for icon-only elements

Every icon-only button must have an accessible name:

```html
<!-- Wrong -->
<button><BellIcon /></button>

<!-- Correct -->
<button aria-label="Notifications — 3 sync errors">
  <BellIcon aria-hidden="true" />
</button>
```

Icon-only buttons: `aria-label` on the button. Icon has `aria-hidden="true"`.

Status dots: `<span class="sr-only">Online</span>` adjacent to the visual dot.

### ID and hash displays

```html
<!-- Device ID display -->
<span>
  <span aria-hidden="true">a1b2c3d4...</span>
  <span class="sr-only">Device ID: a1b2c3d4e5f6789012345678</span>
  <button aria-label="Copy device ID">
    <CopyIcon aria-hidden="true" />
  </button>
</span>
```

---

## Focus Management

### Focus visibility

All focusable elements show a visible focus ring:
- Default browser outline is **not** removed.
- Custom focus ring: `box-shadow: var(--shadow-focus)` (2px ring in accent color with 2px gap).
- `:focus-visible` pseudo-class used (not `:focus`) to hide ring on mouse click but show on keyboard focus.

```css
:focus-visible {
  outline: none;
  box-shadow: var(--shadow-focus);
}
```

### Focus trapping components

Components using Radix primitives (Dialog, Sheet, DropdownMenu, Select) handle focus trapping automatically via `@radix-ui/react-focus-scope`. No custom trap code required.

### Route change focus

On client-side navigation:
1. Focus moves to the `<h1>` of the new page (or the page's main `<section>` if no `<h1>`).
2. This allows screen reader users to hear the new page title announced.

Implementation: `useEffect(() => { pageRef.current?.focus(); }, [location.pathname]);` where `pageRef` points to an element with `tabIndex={-1}` (focusable but not in tab order).

---

## Reduced Motion

All CSS animations check `prefers-reduced-motion`. Implementation strategy:

```css
/* In tokens.css — duration tokens collapse to 0ms */
@media (prefers-reduced-motion: reduce) {
  :root {
    --motion-duration-fast:    0ms;
    --motion-duration-normal:  0ms;
    --motion-duration-slow:    0ms;
    --motion-duration-slower:  0ms;
  }
}
```

Since all animations use token values (`transition: background-color var(--motion-duration-fast)`), this single override disables all animations system-wide.

**Exceptions (cannot be collapsed to 0ms):**
- The DeviceStatusIndicator "online" pulse: replaced with a static dot (no pulse) when reduced motion is active.
- Skeleton shimmer: replaced with static fill color.
- `@keyframes` animations: each must include `@media (prefers-reduced-motion: reduce)` override to set `animation: none`.

---

## Form Accessibility

### Labels

Every input has an associated `<label>`:

```html
<!-- Correct -->
<label for="device-name">Device Name</label>
<input id="device-name" type="text" />

<!-- Also correct (wrapping) -->
<label>
  Device Name
  <input type="text" />
</label>
```

Never use `placeholder` as a substitute for a label.

### Error messages

```html
<input
  id="token-input"
  type="password"
  aria-invalid="true"
  aria-describedby="token-error"
/>
<p id="token-error" role="alert">Invalid token. Check that you copied it correctly.</p>
```

Error messages appear immediately below the field. `role="alert"` announces them to screen readers when they appear.

### Required fields

```html
<input type="text" required aria-required="true" />
```

Visual required indicator (asterisk) has `aria-hidden="true"`. Required state is communicated via `aria-required`.

### Toggle switch

```html
<button
  role="switch"
  aria-checked="true"
  aria-label="Sync Zelda: TOTK on Switch OLED"
>
  <!-- visual knob -->
</button>
```

The label must include context (which game, which device) — not just "Sync enabled".

---

## Color Independence

Every piece of information communicated by color must also be communicated by:
1. Text (label, description)
2. Icon (optional but preferred)
3. Shape or position (for charts)

### Checklist by component

| Component | Color used for | Non-color alternative |
|-----------|---------------|----------------------|
| StatusBadge | Status type | Text label ("SYNCED", "CONFLICT") |
| DeviceStatusIndicator | Online/offline | Text label + icon (Wifi vs WifiOff) |
| EventRow | Event type | Icon per type + text |
| SnapshotNode | Snapshot state | Text state label |
| ConflictBanner | Warning | Warning icon + text |
| OfflineBanner | Error | Error icon + text |
| LineageEdge | Branch type | Dashed vs solid stroke (conflict vs canonical) |
| TransactionTimeline | Step state | Step number + text label |

---

## Semantic HTML

Use the correct HTML element for the job. No `<div>` where a semantic element exists.

| Use case | Element |
|----------|---------|
| Page title | `<h1>` (one per page) |
| Section titles | `<h2>`, `<h3>` (in logical order) |
| Navigation | `<nav>` |
| Main content | `<main>` |
| Footer | `<footer>` |
| Buttons | `<button>` (not `<div onClick>`) |
| Links | `<a href>` (not `<button>` for navigation) |
| Lists | `<ul>/<li>` or `<ol>/<li>` |
| Tables | `<table>/<thead>/<tbody>/<th>/<td>` |
| Time | `<time datetime="ISO-8601">` |
| Code/IDs | `<code>` or `<kbd>` |
| Alerts | `<p role="alert">` or `<div role="alert">` |

---

## Testing Protocol

### Automated

- `axe-core` via `@axe-core/react` in development mode (console warnings on violations).
- `eslint-plugin-jsx-a11y` in ESLint config (enforced in CI).

### Manual

For each phase completion:
1. Keyboard-only navigation: Tab through every page, verify all actions reachable.
2. VoiceOver (macOS): navigate Dashboard and Game Detail, verify all content announced correctly.
3. Contrast check: browser DevTools CSS Overview → Color Contrast.
4. Zoom to 200%: verify no content is clipped or inaccessible.
5. Reduced motion: enable in OS settings, verify no animations run.

### Screen reader testing script (minimal)

```
1. Open Dashboard. Verify: page title announced, stat values announced.
2. Tab to notification bell. Verify: "Notifications — 3 sync errors" announced.
3. Activate bell. Verify: drawer announced as dialog with label "Sync errors".
4. Escape. Verify: focus returns to bell.
5. Navigate to Library. Verify: new page title announced.
6. Open Game Detail for a conflicted game. Verify: conflict banner text announced.
7. Activate "Resolve Conflict". Verify: dialog announced, both options readable.
8. Escape. Verify: focus returns to trigger button.
```
