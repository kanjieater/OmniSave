# 10 — Wireframe Specifications

Detailed textual wireframes for every major screen. All layouts are described for the desktop (≥1024px) breakpoint unless noted. Mobile notes follow each screen.

Legend:
```
[...]     — button or interactive element
<...>     — text content
(...)     — icon
●         — colored status dot
───       — horizontal divider
│         — vertical divider or border
[x]       — close button
⚠         — warning icon
✓         — checkmark / success icon
```

---

## Global Shell

```
┌─────────────────────────────────────────────────────────────────────────┐
│ TopBar                                                                  │
│ (≡) OmniSave          <Dashboard / Zelda: TOTK>           (Bell●3) [?] │
├───────┬─────────────────────────────────────────────────────────────────┤
│       │                                                                 │
│  (◎)  │   [page content]                                               │
│  (◉)  │                                                                 │
│  (◎)  │                                                                 │
│  (◎)  │                                                                 │
│  (◎)  │                                                                 │
│       │                                                                 │
│  ─── │                                                                 │
│  (⚙) │                                                                 │
│       │                                                                 │
└───────┴─────────────────────────────────────────────────────────────────┘
```

**SideNav (56px rail, icons only):**
- (LayoutDashboard) — Dashboard [Badge: 3 errors]
- (Gamepad2) — Library [Badge: 1 conflict]
- (Monitor) — Devices
- (Activity) — Activity
- Separator
- (Settings) — Settings

**TopBar:**
- Left: hamburger (mobile) or nothing (desktop)
- Center-left: product wordmark "OmniSave" (small, muted)
- Center: breadcrumb
- Right: notification bell (with error count badge), help icon

---

## Auth Page — Bootstrap (First Run)

```
┌────────────────────────────────────────────────────┐
│                                                    │
│          (Shield icon 48px)                        │
│          OmniSave                                  │
│          <Your server is ready.>                   │
│                                                    │
│  ┌──────────────────────────────────────────────┐  │
│  │  (1)  Save your access token                 │  │
│  │                                              │  │
│  │  ┌────────────────────────────────────────┐  │  │
│  │  │  a8f3d92c1e4b7f0a...  (monospace)    │  │  │
│  │  └──────────────────────┬─────────────────┘  │  │
│  │                         [(Copy)]              │  │
│  │                                              │  │
│  │  ⚠ Store this token securely.               │  │
│  │    You'll need it to log in.                 │  │
│  │                                              │  │
│  └──────────────────────────────────────────────┘  │
│                                                    │
│  [Continue to Dashboard →]                         │
│                                                    │
└────────────────────────────────────────────────────┘
```

---

## Auth Page — Login (Returning User)

```
┌────────────────────────────────────────────────────┐
│                                                    │
│          (Shield icon 48px)                        │
│          OmniSave                                  │
│          <Enter your access token>                 │
│                                                    │
│  ┌──────────────────────────────────────────────┐  │
│  │  Access Token                                │  │
│  │  [····················] (Eye toggle)         │  │
│  └──────────────────────────────────────────────┘  │
│                                                    │
│  [Sign In]                                         │
│                                                    │
│  <Error: Invalid token> (shown if failed)          │
│                                                    │
└────────────────────────────────────────────────────┘
```

---

## Dashboard — Healthy State

```
┌───────┬───────────────────────────────────────────────────────────────┐
│ Nav   │  Dashboard                          Updated 30s ago            │
│       │                                                                │
│  (◉)  │  ┌─────────────────────────────────────────────────────────┐  │
│       │  │  ✓  All saves are in sync                               │  │
│       │  │     12 games · 3 devices · 0 errors                     │  │
│       │  └─────────────────────────────────────────────────────────┘  │
│       │                                                                │
│       │  ┌──────────┐  ┌──────────┐  ┌──────────┐                    │
│       │  │ 12 games │  │ 3 devices│  │ 0 errors │                    │
│       │  │ (Gamepad)│  │ (Monitor)│  │ (Check)  │                    │
│       │  └──────────┘  └──────────┘  └──────────┘                    │
│       │                                                                │
│       │  Recent Games                           [View Library →]       │
│       │  ┌────────────────────────────────────────────────────────┐   │
│       │  │ [icon] Zelda: TOTK      ● SYNCED  · Snap #42  · 2h ago │   │
│       │  │ [icon] Metroid Dread    ● SYNCED  · Snap #18  · 6h ago │   │
│       │  │ [icon] Mario Kart 8    ● SYNCED  · Snap #7   · 1d ago  │   │
│       │  └────────────────────────────────────────────────────────┘   │
│       │                                                                │
│       │  ┌───────────────────────────┐  ┌──────────────────────────┐  │
│       │  │ Devices                   │  │ Recent Activity          │  │
│       │  │ (Monitor) Switch OLED     │  │ ● Upload · TOTK · 2h     │  │
│       │  │           ● Online        │  │ ● Upload · MK8  · 1d     │  │
│       │  │ (Monitor) Switch Lite     │  │ ● Download · TOTK · 1d   │  │
│       │  │           ○ 3h ago        │  │ ● Upload · Metroid · 2d  │  │
│       │  │           [View All →]    │  │ [View All →]             │  │
│       │  └───────────────────────────┘  └──────────────────────────┘  │
└───────┴────────────────────────────────────────────────────────────────┘
```

---

## Dashboard — Error State (Active Errors)

```
│  ┌─────────────────────────────────────────────────────────────────┐  │
│  │  ⚠  2 sync errors require your attention                       │  │
│  │     Upload failed · Metroid Dread · Switch Lite                 │  │
│  │     Download timed out · Mario Kart 8 · Switch OLED            │  │
│  │                                   [View Errors →]              │  │
│  └─────────────────────────────────────────────────────────────────┘  │
```

(Replaces the "All saves are in sync" health row)

---

## Library Page

```
┌───────┬───────────────────────────────────────────────────────────────┐
│ Nav   │  Library                  [Search games...]  [Sort ▼] [Filter] │
│       ├────────────────────────────────────────────────────────────────┤
│       │  12 games                                                      │
│       │                                                                │
│       │  ┌────────────────────────────────────────────────────────┐   │
│       │  │ [icon] Zelda: TOTK      ● SYNCED  · Snap #42 · 2h ago  │   │
│       │  │        3 devices                              [→]       │   │
│       │  ├────────────────────────────────────────────────────────┤   │
│       │  │ [icon] Metroid Dread    ⚠ CONFLICT · Snap #18 · 4h ago │   │
│       │  │        2 devices · Resolve needed             [→]       │   │
│       │  ├────────────────────────────────────────────────────────┤   │
│       │  │ [icon] Mario Kart 8    ● SYNCED  · Snap #7  · 1d ago   │   │
│       │  │        3 devices                              [→]       │   │
│       │  ├────────────────────────────────────────────────────────┤   │
│       │  │ ...                                                      │   │
│       │  └────────────────────────────────────────────────────────┘   │
└───────┴────────────────────────────────────────────────────────────────┘
```

---

## Game Detail — Overview Tab (No Conflict)

```
┌───────┬───────────────────────────────────────────────────────────────┐
│ Nav   │  ← Library                                                    │
│       │                                                                │
│       │  [icon 64px]  Zelda: TOTK                         [Edit (✎)]  │
│       │               ● SYNCED · Current Save: #42                    │
│       │                                                                │
│       │  [Overview]  [History]                                         │
│       ├────────────────────────────────────────────────────────────────│
│       │                                                                │
│       │  Sync Status                                                   │
│       │  ┌────────────────────────────────────────────────────────┐   │
│       │  │ Device          Status       Device Save  Cloud Save    │   │
│       │  │─────────────────────────────────────────────────────── │   │
│       │  │ Switch OLED     ● In Sync    #42          #42           │   │
│       │  │ Switch Lite     ↓ Needs Update  #38       #42           │   │
│       │  │ PC              ○ Not configured  —        —             │   │
│       │  └────────────────────────────────────────────────────────┘   │
│       │                                                                │
│       │  Recent Activity                          [View all activity →] │
│       │  ● Upload · Switch OLED · 2h ago · Snapshot #42              │
│       │  ● Download · Switch Lite · 6h ago · Snapshot #41            │
│       │  ● Upload · Switch OLED · 1d ago · Snapshot #41              │
│       │                                                                │
└───────┴────────────────────────────────────────────────────────────────┘
```

---

## Game Detail — Overview Tab (Conflict Present)

```
│       │  [icon 64px]  Metroid Dread                       [Edit (✎)]  │
│       │               ⚠ CONFLICT · Two divergent saves exist          │
│       │                                                                │
│       │  ┌─────────────────────────────────────────────────────────┐  │
│       │  │  ⚠  Conflict detected — 2 conflicting saves exist       │  │
│       │  │     Switch OLED saved at #19, Switch Lite saved at #18  │  │
│       │  │     Both descend from Snapshot #17.                     │  │
│       │  │                                    [Resolve Conflict →]  │  │
│       │  └─────────────────────────────────────────────────────────┘  │
│       │                                                                │
│       │  Sync Status                                                   │
│       │  ...                                                           │
```

---

## Game Detail — History Tab (Lineage Graph)

```
│       │  [Overview]  [History ●]                                       │
│       ├────────────────────────────────────────────────────────────────│
│       │                                                                │
│       │  ┌──────────────────────────────────────────────────┐  ┌───┐  │
│       │  │                                                  │  │   │  │
│       │  │         [Graph canvas — pan, zoom]               │  │Map│  │
│       │  │                                                  │  │   │  │
│       │  │   ┌─────────────────────┐                        │  └───┘  │
│       │  │   │ ● CURRENT      HEAD │                        │         │
│       │  │   │ #42 · Switch OLED   │                        │         │
│       │  │   │ 2h ago · 12.4 MB    │                        │         │
│       │  │   └────────────┬────────┘                        │         │
│       │  │                │                                  │         │
│       │  │   ┌────────────┴────────┐                        │         │
│       │  │   │ ● SAVED             │                        │         │
│       │  │   │ #41 · Switch OLED   │                        │         │
│       │  │   │ 6h ago · 12.1 MB    │                        │         │
│       │  │   └────────────┬────────┘                        │         │
│       │  │                │                                  │         │
│       │  │   ┌────────────┴──────────────────────────────┐  │         │
│       │  │   │ ● SAVED   #40 · Switch OLED · 1d          │  │         │
│       │  │   └────────────┬──────────────────────────────┘  │         │
│       │  └────────────────┼──────────────────────────────┘  │         │
│       │                   └──────────────────────────────────┘         │
│       │                                                                │
│       │  [accessibility: 12 saves — most recent: #42, Switch OLED, 2h] │
```

---

## Conflict Resolution Workspace (Modal)

```
┌─ Resolve Conflict ────────────────────────────────────────────────── [x] ┐
│                                                                           │
│  Metroid Dread — Two saves diverged from Snapshot #17                    │
│  <Choose which version to make the current save for all devices.>         │
│                                                                           │
│  ┌──────────────────────────────┐  ┌──────────────────────────────────┐  │
│  │  Switch OLED                 │  │  Switch Lite                     │  │
│  │  ──────────────────────      │  │  ──────────────────────────────  │  │
│  │  Save #19                    │  │  Save #18                        │  │
│  │  3 hours ago                 │  │  5 hours ago                     │  │
│  │  12.4 MB                     │  │  12.1 MB                         │  │
│  │  Fingerprint: a8f3d92c...    │  │  Fingerprint: b1c4e83a...        │  │
│  │                              │  │                                  │  │
│  │  [Choose this version]       │  │  [Choose this version]           │  │
│  └──────────────────────────────┘  └──────────────────────────────────┘  │
│                                                                           │
│  ─────────────────────────────────────────────────────────────────────   │
│                                                                           │
│  ⚠  The other save will be archived — not deleted.                       │
│     You can view it in the save history.                                  │
│                                                                           │
│                                          [Cancel]  [Restore Save #19 →]  │
└───────────────────────────────────────────────────────────────────────────┘
```

**After "Choose this version" click (step 2 confirm state):**

The chosen card gains an accent border and checkmark badge. The "Restore Save #19 →" button becomes active and labeled.

---

## Devices Page

```
┌───────┬───────────────────────────────────────────────────────────────┐
│ Nav   │  Devices                                                       │
│       ├────────────────────────────────────────────────────────────────│
│       │  3 devices                                                     │
│       │                                                                │
│       │  ┌────────────────────────────────────────────────────────┐   │
│       │  │ (Gamepad2) Switch OLED    ● Online  · 12 games   [→]   │   │
│       │  ├────────────────────────────────────────────────────────┤   │
│       │  │ (Gamepad2) Switch Lite    ○ 3h ago  · 8 games    [→]   │   │
│       │  ├────────────────────────────────────────────────────────┤   │
│       │  │ (Monitor)  Gaming PC      ○ 1d ago  · 3 games    [→]   │   │
│       │  └────────────────────────────────────────────────────────┘   │
└───────┴────────────────────────────────────────────────────────────────┘
```

---

## Device Detail Page

```
┌───────┬───────────────────────────────────────────────────────────────┐
│ Nav   │  ← Devices                                                    │
│       │                                                                │
│       │  (Gamepad2 48px)  Switch OLED                      [Edit (✎)] │
│       │                   ● Online · Last seen 2 minutes ago           │
│       │                   Device ID: a1b2c3d4...            [(Copy)]   │
│       │                                                                │
│       │  Sync Preferences               [Enable All] [Disable All]    │
│       │  ┌────────────────────────────────────────────────────────┐   │
│       │  │ [icon] Zelda: TOTK           [●─] Enabled              │   │
│       │  │ [icon] Metroid Dread         [●─] Enabled              │   │
│       │  │ [icon] Mario Kart 8          [○─] Disabled             │   │
│       │  └────────────────────────────────────────────────────────┘   │
│       │                                                                │
│       │  ───────────────────────────────────────────────────────────  │
│       │                                                                │
│       │  [⚠ Remove Device]                                             │
│       │  <Removes this device from OmniSave. Save data is kept.>       │
│       │                                                                │
└───────┴────────────────────────────────────────────────────────────────┘
```

---

## Activity Page

```
┌───────┬───────────────────────────────────────────────────────────────┐
│ Nav   │  Activity     [Type: All ▼]  [Device: All ▼]  [Game: Search] │
│       ├────────────────────────────────────────────────────────────────│
│       │                                                                │
│       │  Today                                                         │
│       │  ● Upload completed  · Zelda: TOTK  · Switch OLED · 2h ago   │
│       │  ⚠ Conflict detected · Metroid      · Switch Lite  · 4h ago  │
│       │  ● Download complete · Zelda: TOTK  · Switch Lite  · 6h ago  │
│       │                                                                │
│       │  Yesterday                                                     │
│       │  ● Upload completed  · Mario Kart 8 · Switch OLED · 1d ago   │
│       │  ● Upload completed  · TOTK         · Switch Lite  · 1d ago  │
│       │  ✗ Upload failed     · Metroid      · Switch OLED · 1d ago   │
│       │                                                                │
│       │  3 days ago                                                    │
│       │  ● Upload completed  · Mario Kart 8 · Switch Lite  · 3d ago  │
│       │                                                                │
│       │  [Load earlier events]                                         │
└───────┴────────────────────────────────────────────────────────────────┘
```

---

## Settings Page

```
┌───────┬───────────────────────────────────────────────────────────────┐
│ Nav   │  Settings                                                      │
│       ├────────────────────────────────────────────────────────────────│
│       │                                                                │
│       │  Authentication                                                │
│       │  ┌────────────────────────────────────────────────────────┐   │
│       │  │ Access Token                                           │   │
│       │  │ <Your token is stored in this browser.>               │   │
│       │  │                                                        │   │
│       │  │ [Rotate Token]                                         │   │
│       │  │ <Generates a new token. Old token stops working.>      │   │
│       │  └────────────────────────────────────────────────────────┘   │
│       │                                                                │
│       │  ─────────────────────────────────────────────────────────    │
│       │                                                                │
│       │  RomM Integration                                              │
│       │  ┌────────────────────────────────────────────────────────┐   │
│       │  │ Device → RomM Username mapping                         │   │
│       │  │ <Maps devices to your RomM user for save attribution.> │   │
│       │  │                                                        │   │
│       │  │ Switch OLED    [kanjieater     ] [Save] [Remove]       │   │
│       │  │ Switch Lite    [kanjieater     ] [Save] [Remove]       │   │
│       │  │ Gaming PC      [──────────────]                        │   │
│       │  └────────────────────────────────────────────────────────┘   │
│       │                                                                │
│       │  ─────────────────────────────────────────────────────────    │
│       │                                                                │
│       │  About                                                         │
│       │  OmniSave Server · v2.0.0                                      │
│       │  [Logout]                                                      │
└───────┴────────────────────────────────────────────────────────────────┘
```

---

## Notification Drawer

```
┌────────────────────────────────────────────────── [x] ┐
│  Sync Errors                        [Dismiss all]      │
├────────────────────────────────────────────────────────│
│  ⚠  Metroid Dread — Upload failed                     │
│     Switch Lite · 4 hours ago                          │
│     [Go to game →]                       [Dismiss]     │
├────────────────────────────────────────────────────────│
│  ⚠  Mario Kart 8 — Download timed out                │
│     Switch OLED · 1 day ago                            │
│     [Go to game →]                       [Dismiss]     │
└────────────────────────────────────────────────────────┘
```

---

## Confirm / Revoke Device Modal

```
┌─ Remove Device ──────────────────────────────── [x] ┐
│                                                      │
│  (⚠ icon 32px)                                       │
│  Remove Switch Lite?                                 │
│                                                      │
│  <This device will no longer sync saves with         │
│  OmniSave. Your existing saves on the server         │
│  are not deleted.>                                   │
│                                                      │
│                         [Cancel]  [Remove Device]    │
└──────────────────────────────────────────────────────┘
```

---

## Mobile Views (375px)

### Dashboard (Mobile)

```
┌──────────────────────────────────────────┐
│  (≡)  OmniSave                  (Bell●3) │
├──────────────────────────────────────────┤
│                                          │
│  ✓ All saves are in sync                 │
│  12 games · 3 devices                    │
│                                          │
│  ┌──────────────────────────────────┐    │
│  │ [icon] TOTK      ● SYNCED  2h   │    │
│  │ [icon] Metroid   ⚠ CONFLICT 4h  │    │
│  │ [icon] Mario Kart ● SYNCED  1d  │    │
│  └──────────────────────────────────┘    │
│                                          │
│  [View all activity →]                   │
│                                          │
├──────────┬──────────┬──────────┬─────────┤
│ Dashboard│ Library  │ Devices  │Activity │
│   (◉)   │  (○)     │  (○)     │  (○)   │
└──────────┴──────────┴──────────┴─────────┘
```

### Conflict Workspace (Mobile — stacked)

```
┌──────────────────────────────────────────┐
│  Resolve Conflict                   [x]  │
├──────────────────────────────────────────┤
│  Metroid Dread                           │
│  <Choose a save to restore.>             │
│                                          │
│  ┌──────────────────────────────────┐    │
│  │  Switch OLED                     │    │
│  │  Save #19 · 3 hours ago          │    │
│  │  12.4 MB                         │    │
│  │  [Choose this version]           │    │
│  └──────────────────────────────────┘    │
│                                          │
│  ┌──────────────────────────────────┐    │
│  │  Switch Lite                     │    │
│  │  Save #18 · 5 hours ago          │    │
│  │  12.1 MB                         │    │
│  │  [Choose this version]           │    │
│  └──────────────────────────────────┘    │
│                                          │
│  ⚠ The other save will be archived.     │
│                                          │
│  [Cancel]    [Restore Selected →]        │
└──────────────────────────────────────────┘
```

### Lineage (Mobile — list view, no graph)

```
┌──────────────────────────────────────────┐
│  ← Library / Zelda: TOTK                │
│  [Overview] [History ●]                  │
├──────────────────────────────────────────┤
│  Save History (12 saves)                 │
│                                          │
│  ┌──────────────────────────────────┐    │
│  │ ● CURRENT    #42 · 2h ago        │    │
│  │   Switch OLED · 12.4 MB          │    │
│  ├──────────────────────────────────┤    │
│  │ ● Saved      #41 · 6h ago        │    │
│  │   Switch OLED · 12.1 MB          │    │
│  ├──────────────────────────────────┤    │
│  │ ⚠ Conflict   #40 · 8h ago        │    │
│  │   Switch Lite · 11.9 MB          │    │
│  │   [View conflict]                 │    │
│  └──────────────────────────────────┘    │
└──────────────────────────────────────────┘
```
