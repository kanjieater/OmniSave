# 04 — Component Library

All components are built on shadcn/ui + Radix primitives with the OmniSave design token system. Each component section describes: purpose, states, variants, accessibility, mobile behavior, and performance requirements.

---

## Navigation

### SideNav

**Purpose:** Primary application navigation. Fixed left rail on desktop, slide-over sheet on mobile.

**States:**
- Default: collapsed rail (icon only, 56px width)
- Expanded: icon + label (220px width)
- Mobile: hidden, triggered by hamburger → sheet overlay

**Variants:**
- `rail` — icon-only, collapsed
- `expanded` — icon + label
- `mobile-sheet` — full-height overlay

**Items:**
- Each item: icon + label + optional badge (error count)
- Active state: `--color-bg-selected` background, left accent border (2px `--color-accent`)
- Hover: `--color-bg-hover` background, 80ms transition

**Accessibility:**
- `role="navigation"`, `aria-label="Main navigation"`
- Active item: `aria-current="page"`
- Keyboard: Tab between items, Enter to navigate
- Focus ring visible on keyboard focus

**Mobile behavior:**
- Rail hidden. Hamburger button in TopBar triggers sheet.
- Sheet closes on route change or backdrop click.

**Performance:** No lazy loading. Nav renders with first paint.

---

### Breadcrumb

**Purpose:** Secondary navigation showing current location within hierarchy.

**States:** Static (rendered server-side or from route state)

**Structure:** `Dashboard / Games / Zelda: TOTK`
- Each segment except last: clickable link
- Last segment: current page, `aria-current="page"`
- Separator: `ChevronRight` icon, 12px, `--color-text-muted`

**Accessibility:** `nav` + `aria-label="Breadcrumb"` + `ol` list structure

**Mobile:** Collapses to show only last two segments with `…` prefix.

---

### TopBar

**Purpose:** Fixed header with page title, breadcrumb, global actions (notification bell, status indicator).

**Slots:** left (breadcrumb), center (page title on mobile), right (bell, offline badge, user menu)

**States:** Default | Offline (red badge + "Offline" label) | Loading (spinner)

**Accessibility:** `role="banner"`

**Mobile:** Full width. Hamburger button in left slot.

---

## Tables

### DataTable

**Purpose:** Reusable tabular data display. Used for: devices list, events list, game list, snapshot list.

**States:** Loading | Empty | Populated | Error

**Variants:**
- `default` — standard density (40px rows)
- `compact` — 32px rows (snapshot list, events)
- `comfortable` — 48px rows (device detail, settings)

**Features:**
- Sortable columns (click header, cycles asc/desc/none)
- Row click navigation
- Row hover actions (revealed on hover: edit, delete, copy)
- Sticky header
- Virtualized for >200 rows (using `@tanstack/react-virtual`)

**Empty state:** Icon + heading + description. Never a blank table body.

**Loading state:** Skeleton rows (3–5), same height as data rows.

**Accessibility:**
- `role="table"` with proper `th` / `td` semantics
- Sortable headers: `aria-sort="ascending|descending|none"`
- Row actions: `aria-label` on icon buttons
- Keyboard: Tab to header, Space/Enter to sort; Tab through rows

**Mobile:** Columns collapse. Primary column (name) always visible. Secondary columns hidden below `--bp-md`. "More" expansion per row optional.

**Performance:** Virtual rendering for >100 rows. Skeleton on initial load only (subsequent refreshes are silent).

---

## Cards

### SummaryCard

**Purpose:** Dashboard stat display (total games, active errors, pending deliveries, devices online).

**States:** Loaded | Loading (skeleton) | Error

**Structure:**
```
┌─────────────────────────────┐
│  Icon   Label               │
│                             │
│  12     (large number)      │
│  ↑ 2 today  (delta)         │
└─────────────────────────────┘
```

**Variants:**
- `default` — neutral styling
- `alert` — error color when value > 0 (used for Active Errors)
- `info` — accent color (used for Pending Deliveries)

**Accessibility:** `role="status"`, `aria-live="polite"` for live-updating stats.

**Mobile:** Full-width stack. 2-per-row grid on tablet.

---

### GameCard

**Purpose:** Compact game representation in lists and recent-games section.

**States:** Loaded | Loading | SYNCED | CONFLICT | ERROR | NO_DATA

**Structure:**
```
┌──────────────────────────────────┐
│  [icon 48px]   Game Title        │
│                ● SYNCED  seq:42  │
│                3 devices · 2h ago│
└──────────────────────────────────┘
```

**States mapped to visual:**
- SYNCED: `--color-success` dot
- CONFLICT: `--color-warning` dot + amber border
- ERROR: `--color-error` dot + red border
- NO_DATA: `--color-neutral` dot

**Accessibility:** `role="article"`, keyboard focusable, Enter to navigate.

**Mobile:** Full-width. Icon scaled to 40px.

---

### DeviceCard

**Purpose:** Device summary in device list and dashboard.

**Structure:**
```
┌──────────────────────────────────┐
│  [hardware icon]  Device Name    │
│                   ● Online       │
│                   3 pending · Switch OLED │
└──────────────────────────────────┘
```

**Online indicator:** Green dot if last_seen < 5 min. Tooltip: "Last seen 2 minutes ago".
**Pending count:** Shown only if > 0.
**Hardware type icon:** Gamepad2 (Switch), Monitor (PC), Smartphone (mobile).

---

## Dialogs

### Modal

**Purpose:** Focused action or information requiring user attention.

**Variants:**
- `dialog` — standard dialog with title, body, footer actions
- `alert` — destructive confirmation (red title, destructive button)
- `drawer` — side-panel dialog (notification drawer, settings)

**States:** Hidden | Open | Loading (actions in progress)

**Structure:**
```
┌─ Modal ──────────────────────────────┐
│  Title                          [X]  │
│                                      │
│  Body content                        │
│                                      │
│  ──────────────────────────────────  │
│  [Cancel]              [Confirm]     │
└──────────────────────────────────────┘
```

**Accessibility:**
- `role="dialog"`, `aria-modal="true"`, `aria-labelledby` pointing to title
- Focus trapped inside modal when open
- Escape closes modal
- Focus returns to trigger element on close
- Backdrop click closes non-destructive modals

**Mobile:** Full-screen bottom sheet on `< --bp-md`.

---

### ConflictWorkspace

**Purpose:** Specialized modal/workspace for conflict resolution. High-stakes, requires careful UX.

**Structure (full breakdown in 10-wireframe-spec.md):**
```
┌─ Resolve Conflict ──────────────────────────────────┐
│  Zelda: TOTK — Diverged at Snapshot #38             │
│                                                     │
│  OPTION A                    OPTION B               │
│  ┌────────────────┐          ┌────────────────┐     │
│  │  Switch OLED   │          │  Switch Lite   │     │
│  │  Snapshot #42  │          │  Snapshot #41  │     │
│  │  3 hours ago   │          │  5 hours ago   │     │
│  │  12.4 MB       │          │  12.1 MB       │     │
│  │                │          │                │     │
│  │  [Select this] │          │  [Select this] │     │
│  └────────────────┘          └────────────────┘     │
│                                                     │
│  Diverged from snapshot #38 · 2026-05-28 14:32      │
│                                                     │
│  ⚠ The other snapshot will be archived (not lost)   │
│                                                     │
│                          [Cancel]  [Confirm Restore] │
└─────────────────────────────────────────────────────┘
```

**Accessibility:** All standard modal rules + explicit labeling of each option with device name.

---

### ConfirmDialog

**Purpose:** Destructive action confirmation (revoke device, delete snapshot).

**Variants:** `destructive` (red confirm button), `standard` (accent confirm button)

**Required fields:** title, description, confirm label, cancel label.

---

## Forms

### Input

**States:** Default | Focused | Filled | Error | Disabled

**Style:** Dark input background (`--color-bg-input`), `--border-base`, focus shifts to `--border-focus` with `--shadow-focus`.

**Variants:** `default`, `inline` (for rename-in-place on labels)

**Accessibility:** Always has associated `<label>`. Error messages use `aria-describedby`. Required fields use `aria-required`.

---

### Toggle

**Purpose:** Binary on/off (sync preferences per device/game).

**States:** On | Off | Disabled | Loading (pending API call)

**Loading state:** Spinner replaces knob during API call.

**Accessibility:** `role="switch"`, `aria-checked`, `aria-label` with context (e.g., "Sync Zelda: TOTK on Switch OLED").

**Mobile:** 44px tap target minimum.

---

### InlineEdit

**Purpose:** Click-to-edit labels (game name, device name).

**States:** View | Edit | Saving | Error

**Behavior:**
- View: label with `Edit2` icon on hover
- Edit: input field with confirm (Enter) and cancel (Escape)
- Saving: disabled input with spinner
- Error: red border, error message below, keeps edit mode open

---

## Timeline Components

### EventRow

**Purpose:** Single row in the event feed / events page.

**Structure:**
```
● [icon]  UPLOAD COMPLETED     2h ago
          Zelda: TOTK · Switch OLED
```

**Color of dot:** maps to event type (success=green, error=red, info=blue, neutral=grey)

**Variants:** `compact` (events page), `featured` (dashboard feed)

**Accessibility:** `role="listitem"`, timestamp as `<time datetime="...">`.

---

### EventTimeline

**Purpose:** Grouped event feed with time-period headers.

**Groups:** Today | Yesterday | This week | Older

**Header:** `<h3>` with light styling, not a prominent section break.

**Performance:** Virtualized list for >50 events. Infinite scroll / "load more" pagination.

---

### TransactionTimeline

**Purpose:** Shows the state progression of a single transaction (UPLOADING → PROCESSING → READY_FOR_RESTORE → COMPLETED).

**Structure:** Horizontal or vertical step indicator with timestamps at each transition.

**States of each step:** Pending (grey) | Active (blue, spinning) | Complete (green) | Failed (red) | Skipped (dashed)

---

## Snapshot Components

### SnapshotNode

**Purpose:** Single snapshot in a lineage graph.

**Variants:**
- `head` — current HEAD (larger, accent border, "HEAD" badge)
- `canonical` — committed, non-head snapshot
- `conflict-branch` — divergent branch (amber)
- `failed` — failed transaction (red)
- `superseded` — archived (grey, reduced opacity)

**Structure (node in DAG):**
```
┌──────────────────────┐
│  ● COMMITTED    HEAD │
│  #42 · Switch OLED   │
│  3h ago · 12.4 MB    │
└──────────────────────┘
```

**Actions (hover):** Push to devices, Delete, Copy SHA256

---

### LineageGraph

**Purpose:** DAG visualization of snapshot history. (see 07-visualization-strategy.md for technology choice)

**Layout:** Top-to-bottom with newest at top. Branches rendered to the right of canonical chain.

**Interactions:**
- Pan and zoom (pinch on mobile, mouse wheel on desktop)
- Click node to open SnapshotDetailPanel
- "Resolve" button on conflict branch nodes

---

### SnapshotDetailPanel

**Purpose:** Slide-in panel showing full details of a selected snapshot.

**Fields:** sequence number, device, timestamp, size, SHA256 (truncated + copy), parent sequence, state, transaction_id.

**Actions:** Push to all devices, Push to specific device, Delete.

---

## Conflict Components

### ConflictBanner

**Purpose:** Persistent banner on GamePage when a conflict exists.

**Structure:**
```
⚠  Conflict detected — 2 divergent saves exist for this game.
   Snapshots #41 and #42 both descend from #38.  [Resolve →]
```

**Dismissal:** Not dismissible until conflict is resolved. High visual weight (amber background, full-width).

---

### ConflictBadge

**Purpose:** Small inline badge on game cards and nav items indicating conflict state.

**Variant:** `dot` (in nav badge count), `chip` (in game card, labeled "CONFLICT")

---

## Device Components

### DeviceStatusIndicator

**Purpose:** Online/offline dot with tooltip.

**States:** Online (green, pulsing — single pulse every 4s), Offline (grey, static), Unknown (yellow)

**Pulse animation:** Single radial pulse from center, 1-second duration, repeats every 4 seconds. Stops on `prefers-reduced-motion`.

**Tooltip:** "Online · Last seen 2 minutes ago" or "Offline · Last seen 3 hours ago"

---

### HardwareIcon

**Purpose:** Visual identity for device hardware type.

**Icons:**
- Switch (any model): Gamepad2 icon
- Switch OLED: Gamepad2 + "OLED" badge
- Switch Lite: Gamepad2 + "Lite" badge
- PC: Monitor icon

**Size:** 20px in list contexts, 32px in detail contexts.

---

### DeviceSyncMatrix

**Purpose:** Shows sync state across all devices for a single game.

**Structure:**
```
Device          State           Local #  Cloud #
Switch OLED     ● SYNCED        42       42
Switch Lite     ○ OUT OF SYNC   38       42
PC              ↓ DOWNLOADING   —        42
```

**States→labels (user language, not enum names):**
- SYNCED → "In Sync"
- OUT_OF_SYNC → "Needs Update"
- DOWNLOADING → "Downloading..."
- NO_DELIVERY → "Not Configured"

---

## Graph Components

### ActivitySparkline

**Purpose:** Mini bar chart showing sync activity over time (for dashboard).

**Technology:** Lightweight SVG, no external library.

**Data:** Event count per day, last 14 days.

**Size:** 120px × 32px. No axes, no labels. Tooltip on hover shows "4 events on May 28".

---

### SyncProgressBar

**Purpose:** Shows upload/download progress during active transactions.

**Structure:** Horizontal progress bar with percentage label and bytes transferred.

**Animation:** Smooth width transition (`--motion-duration-slow` + `--motion-ease-out`).

**States:** Active (accent color, animated) | Complete (success color, static) | Failed (error color, static)

---

## Status Components

### StatusBadge

**Purpose:** Compact status indicator used throughout (game status, transaction state, sync state).

**Variants:** `dot+label`, `label-only`, `dot-only`

**Size:** `sm` (inline in tables), `md` (cards), `lg` (page headers)

**Token mapping:** See `03-design-system.md` Status→Color mapping.

**Accessibility:** Never relies on color alone — always includes text label or `aria-label`.

---

### OfflineBanner

**Purpose:** Full-width alert when server is unreachable (3+ poll failures).

**Structure:**
```
[WifiOff icon]  Connection lost — OmniSave server is unreachable.
                Retrying in 12s...                    [Retry now]
```

**Position:** Pinned below TopBar, above page content. Full width. Cannot be dismissed.

**Color:** Error (`--color-error-subtle` background, `--color-error-border` border).

---

### NotificationBell

**Purpose:** Header bell icon with error count badge.

**States:** No errors (grey bell) | Has errors (red bell + count badge)

**Badge:** `--radius-full` pill, `--color-error` background, max display "9+" for counts > 9.

**Interaction:** Click opens NotificationDrawer.

---

## Empty States

Standard empty state structure:

```
[Icon — 48px, --color-text-muted]

No devices registered yet

Connect your Nintendo Switch to start syncing saves.

[Action Button — optional]
```

**Required for:** DevicesPage, EventsPage, GameList, SnapshotList, NotificationDrawer.

---

## Loading States

**Skeleton loading:** Used for initial page load only. Rectangular placeholders at same height/width as real content. Color: `--color-bg-hover` animated with a shimmer sweep.

**Inline spinner:** `Loader2` icon (Lucide), 16px, spinning at 0.8 rotations/second. Used for: button loading, data refreshes in-place, toggle saving state.

**Never:** Full-page spinners after initial load. Data refreshes are always silent.
