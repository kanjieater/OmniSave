# 05 — Information Architecture

## Core Principle

Every screen answers one primary question. Secondary questions are progressive disclosures — available but not competing for attention.

The information hierarchy from `context/server/08-frontend-ui.md` governs all screens:
1. **State Views** — Is the system healthy? What is the current canonical state?
2. **Exception Handling** — What requires user action?
3. **Activity Feed** — What has happened recently?
4. **Audit** — Full historical record.

---

## Application Structure

```
OmniSave
├── Dashboard                 (State View)
│   ├── Health Status Pane    (primary: is everything ok?)
│   ├── Games with activity   (secondary: what changed?)
│   ├── Device status         (secondary: who is connected?)
│   └── Recent events         (tertiary: detailed activity)
│
├── Library                   (State View — game catalog)
│   ├── Game list (filterable, sortable)
│   └── Game Detail
│       ├── Status + HEAD snapshot
│       ├── Device sync matrix
│       ├── Conflict workspace (if conflict exists)
│       └── Snapshot lineage graph
│
├── Devices                   (State View — device catalog)
│   ├── Device list
│   └── Device Detail
│       ├── Device info + status
│       └── Games on device (sync preferences)
│
├── Activity                  (Activity Feed)
│   └── Event timeline (filterable by device, game, type)
│
└── Settings                  (Admin)
    ├── Auth (token rotation)
    └── Integrations (RomM mapping)
```

---

## Navigation Hierarchy

### Primary Navigation (SideNav)

| Item | Icon | Badge | Route |
|------|------|-------|-------|
| Dashboard | LayoutDashboard | error count | `/` |
| Library | Gamepad2 | conflict count | `/library` |
| Devices | Monitor | — | `/devices` |
| Activity | Activity | — | `/activity` |
| Settings | Settings | — | `/settings` |

**Rules:**
- Badge on Dashboard: total unacknowledged errors.
- Badge on Library: total games with CONFLICT status.
- No badge on Devices, Activity, Settings.
- Active item is visually distinct (accent left border + selected background).

### Secondary Navigation (In-page tabs or sub-nav)

Used only in high-complexity pages:

**Game Detail sub-nav:**
- Overview (default: status + sync matrix)
- History (snapshot lineage graph)

**Settings sub-nav:**
- Authentication
- Integrations

### Breadcrumb Navigation

All detail pages show breadcrumb:

```
Dashboard / Library / Zelda: TOTK
Dashboard / Devices / Switch OLED
```

Breadcrumb segments are clickable links. Current page is not a link.

---

## Dashboard Structure

The dashboard answers: **"What is the current state of my game saves?"**

### Layout (Desktop)

```
┌─────────────────────────────────────────────────────────┐
│  TopBar                                                 │
├─────────┬───────────────────────────────────────────────┤
│         │  Health Row                                   │
│         │  [All Good ✓]  or  [2 Errors ⚠]  [1 Conflict]│
│ SideNav │                                               │
│         │  ┌──────────┐  ┌──────────┐  ┌──────────┐    │
│         │  │ 12 games │  │ 3 devices│  │ 0 errors │    │
│         │  └──────────┘  └──────────┘  └──────────┘    │
│         │                                               │
│         │  Recent Game Activity           [View all →]  │
│         │  ┌──────────────────────────────────────────┐ │
│         │  │ [icon] TOTK          SYNCED  · 2h ago    │ │
│         │  │ [icon] Metroid Dread CONFLICT · 4h ago   │ │
│         │  │ [icon] Mario Kart    SYNCED  · 1d ago    │ │
│         │  └──────────────────────────────────────────┘ │
│         │                                               │
│         │  Devices                  Activity            │
│         │  ┌───────────────┐  ┌──────────────────────┐  │
│         │  │ Switch OLED   │  │ Upload completed     │  │
│         │  │ ● Online      │  │ TOTK · 2h ago        │  │
│         │  │ Switch Lite   │  │ Conflict detected    │  │
│         │  │ ○ 3h ago      │  │ Metroid · 4h ago     │  │
│         │  └───────────────┘  └──────────────────────┘  │
└─────────┴───────────────────────────────────────────────┘
```

**Key decisions:**
- Health row is always the first thing seen (is anything broken?).
- Stats row is secondary context (how many of each thing?).
- Game activity list replaces the horizontal-scroll card row.
- Devices and Activity are side-by-side in a two-column grid below the fold.
- If errors > 0, the Health row becomes an error state that dominates visually.

### Dashboard error state

```
┌─────────────────────────────────────────────────┐
│  ⚠  2 sync errors require your attention        │
│     Metroid Dread failed to deliver              │
│     Mario Kart 8 upload timed out               │
│                          [View Errors →]         │
└─────────────────────────────────────────────────┘
```

This replaces the normal health row when errors exist.

---

## Game Library Structure

**Primary question:** "Which games have activity or issues?"

### Library Layout

```
┌─────────────────────────────────────────────────────────┐
│  Library                          [Search...]  [Filter ▼]│
├─────────────────────────────────────────────────────────┤
│  Sort: Last Activity ▼                                  │
│                                                         │
│  ┌────────────────────────────────────────────────────┐ │
│  │ [icon]  Zelda: TOTK            ● SYNCED   · 2h ago  │ │
│  │         Snapshot #42 · 3 devices                    │ │
│  ├────────────────────────────────────────────────────┤ │
│  │ [icon]  Metroid Dread          ⚠ CONFLICT · 4h ago  │ │
│  │         Snapshot #18 · 2 devices                    │ │
│  ├────────────────────────────────────────────────────┤ │
│  │ [icon]  Mario Kart 8           ● SYNCED   · 1d ago  │ │
│  │         Snapshot #7 · 3 devices                     │ │
│  └────────────────────────────────────────────────────┘ │
└─────────────────────────────────────────────────────────┘
```

**Sort options:** Last activity (default), Name A-Z, Status (errors first), Most snapshots.

**Filter options:** Status (All, SYNCED, CONFLICT, ERROR, NO_DATA), Device.

---

## Game Detail Structure

**Primary question:** "What is the state of this game's saves across my devices?"

### Sub-page: Overview (default)

```
┌─────────────────────────────────────────────────────────┐
│  ← Library / Zelda: TOTK                               │
│                                                         │
│  [game icon 64px]  Zelda: TOTK                    [Edit]│
│                    ● SYNCED · Snapshot #42              │
│                                                         │
│  ┌─ CONFLICT BANNER (if exists) ───────────────────────┐│
│  │  ⚠ Divergent saves detected  [Resolve →]            ││
│  └─────────────────────────────────────────────────────┘│
│                                                         │
│  Sync Status                                            │
│  ┌──────────────────────────────────────────────────┐   │
│  │ Switch OLED  ● In Sync    #42   #42              │   │
│  │ Switch Lite  ↓ Needs Update  #38  #42            │   │
│  └──────────────────────────────────────────────────┘   │
│                                                         │
│  Recent Activity                                        │
│  [last 5 events for this game, compact]                 │
│                                                         │
│                         [View full history →]           │
└─────────────────────────────────────────────────────────┘
```

### Sub-page: History

Full lineage graph. Snapshot detail panel on node click.

---

## Device Structure

**Primary question:** "What is the status of each of my devices?"

### Devices List

```
┌─────────────────────────────────────────────────────────┐
│  Devices                                                │
├─────────────────────────────────────────────────────────┤
│  ┌────────────────────────────────────────────────────┐ │
│  │ [icon] Switch OLED   ● Online   12 games  [→]      │ │
│  ├────────────────────────────────────────────────────┤ │
│  │ [icon] Switch Lite   ○ 3h ago   8 games   [→]      │ │
│  └────────────────────────────────────────────────────┘ │
└─────────────────────────────────────────────────────────┘
```

### Device Detail

```
┌─────────────────────────────────────────────────────────┐
│  ← Devices / Switch OLED                               │
│                                                         │
│  [icon 48px]  Switch OLED                      [Edit]   │
│               ● Online · Last seen 2 min ago            │
│               Device ID: a1b2c3d4...           [Copy]   │
│                                                         │
│  Sync Preferences                    [Toggle all]       │
│  ┌──────────────────────────────────────────────────┐   │
│  │ Zelda: TOTK         [●─] Enabled                 │   │
│  │ Metroid Dread       [●─] Enabled                 │   │
│  │ Mario Kart 8        [○─] Disabled                │   │
│  └──────────────────────────────────────────────────┘   │
│                                                         │
│  ─────────────────────────────────────────────────────  │
│  Danger Zone                                            │
│  [Revoke Device]                                        │
└─────────────────────────────────────────────────────────┘
```

---

## Activity Page Structure

**Primary question:** "What has happened in the last X time period?"

```
┌─────────────────────────────────────────────────────────┐
│  Activity          [Filter: All ▼] [Device: All ▼]      │
├─────────────────────────────────────────────────────────┤
│  Today                                                  │
│  ● Upload completed  · Zelda: TOTK · Switch OLED · 2h   │
│  ⚠ Conflict detected · Metroid · Switch Lite · 4h       │
│  ● Download complete · Zelda: TOTK · Switch Lite · 6h   │
│                                                         │
│  Yesterday                                              │
│  ● Upload completed  · Mario Kart · Switch OLED · 1d    │
│  ● Upload completed  · TOTK · Switch Lite · 1d          │
├─────────────────────────────────────────────────────────┤
│  [Load earlier events]                                  │
└─────────────────────────────────────────────────────────┘
```

**Filter controls:** Event type (All, Uploads, Downloads, Conflicts, Errors), Device, Game (text search).

---

## Mobile Navigation

**Pattern:** Bottom tab bar (5 tabs max).

```
┌─────────────────────────────────────────────────────────┐
│  [page content, full width]                             │
├──────────┬──────────┬──────────┬──────────┬────────────┤
│ Dashboard│ Library  │ Devices  │ Activity │ Settings   │
│ [icon]   │ [icon]   │ [icon]   │ [icon]   │ [icon]     │
└──────────┴──────────┴──────────┴──────────┴────────────┘
```

- Bottom bar: `position: fixed`, `z-index: --z-sticky`
- Safe area inset respected (iOS home bar)
- Active item: `--color-accent` icon + label
- Badge on Dashboard tab (error count)

**Mobile page layout:**
- No sidebar
- TopBar: logo left, bell right, title center
- Content: full-width single column
- Modals: bottom sheets (slide up from bottom, full width)

---

## Responsive Breakpoints

| Breakpoint | Layout | Nav | Tables | Cards |
|-----------|--------|-----|--------|-------|
| < 640px | Mobile | Bottom bar | Single-column list | Full-width |
| 640–1024px | Tablet | Hamburger → sheet | 2-3 columns visible | Grid 2-col |
| > 1024px | Desktop | Fixed sidebar rail | All columns | Dense list |

**Feature availability by breakpoint:**
- Lineage graph: full on desktop, simplified (list) on mobile
- DataTable: full on desktop, collapsed rows on mobile
- Device sync matrix: full on desktop, stacked cards on mobile
- ConflictWorkspace: side-by-side on desktop, stacked on mobile

---

## Feature Grouping Rationale

### Why "Library" not "Games"?
The term "Library" matches the mental model of owning a collection of games. "Games" sounds like a catalog you're browsing, not your personal collection.

### Why "Activity" not "Events"?
"Activity" is user language. "Events" is developer language (from the internal event stream). The concept is the same — but "Activity" communicates the user's goal (what has been happening).

### Why separate Dashboard from Library?
Dashboard = operational view (current health, recent activity). Library = catalog view (all games, their status, history). These serve different visit intentions:
- Dashboard: "Did anything go wrong while I was away?"
- Library: "What saves do I have? What's the state of a specific game?"

### Why Settings separate from Devices?
Devices = operational objects (what hardware exists, what is it syncing?). Settings = administrative configuration (auth, integrations). These are distinct mental models: devices are domain objects, settings are system configuration.
