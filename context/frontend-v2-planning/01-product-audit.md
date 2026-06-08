# 01 — Product Audit

## Scope

Every screen, modal, and workflow in OmniSave V1 (Material UI build, current git state).

---

## Screens Audited

### 1. AuthPage

**Purpose:** Bootstrap server (first run) or enter admin token.

**Complexity:** Low | **Clarity:** Medium | **Density:** Low | **Visual Quality:** Poor

**Pain Points:**
- Two interaction paths (bootstrap vs login) share the same form with no visual separation. First-time users cannot immediately determine which path applies.
- Token display after bootstrap has no copy-to-clipboard affordance.
- No feedback on why authentication failed — error messages are generic.
- No explanation of what "bootstrap" means in domain terms.
- No logout affordance visible after login (buried in Settings).

**Visual Issues:**
- Centered card on default MUI grey background. No brand identity. No logo or product wordmark.
- Typography hierarchy is MUI default, not intentional.

**Mobile:** Works incidentally (single centered card). No mobile-specific design.

---

### 2. Dashboard

**Purpose:** Global status overview — recent games, device status, recent events.

**Complexity:** High | **Clarity:** Low | **Density:** Low | **Visual Quality:** Poor

**Pain Points:**
- Three sections with no clear hierarchy. Arriving after 12 hours offline, the user has no immediate "what happened" answer.
- `RecentGamesRow` is horizontal scrolling on desktop — hides content, breaks on mobile.
- `DeviceStatusOverview` table has no sorting, no filtering, no inline actions.
- `LiveEventFeed` duplicates information in game cards and device rows without interpretive value.
- "Active Errors" stat is buried — errors are the highest-priority signal and should dominate when present.
- No "last updated" indicator. Polling feedback is invisible.
- Stats row uses identical card treatment for very different concepts (games count vs. active errors vs. pending deliveries).

**Information Architecture Problems:**
- No clear answer to "Is everything ok?" on first glance.
- Game cards show five competing data points simultaneously (icon, name, status, snapshot count, last activity).
- Event feed and device table fall below the fold on typical laptop viewports.

**Visual Issues:**
- Heavy MUI card shadows create visual clutter.
- Status chips are not visually distinctive enough for operational status (SYNCED/CONFLICT/ERROR).
- Icon images from RomM vary in size, creating ragged card layouts.
- Excessive inter-section whitespace.

**Mobile:** Horizontal scroll card row is broken. Table does not reflow. Practically unusable.

---

### 3. GamePage (Game Detail)

**Purpose:** Per-game snapshot lineage, device sync status, conflict resolution.

**Complexity:** Very High | **Clarity:** Low | **Density:** Medium | **Visual Quality:** Poor

**Pain Points:**
- `SnapshotList` renders lineage as a vertical list with CSS-margin indentation. Complex lineages become unreadable.
- Conflict branch snapshots are styled in amber with no spatial separation from canonical snapshots.
- "Push to devices" conflict resolution action is low-discoverability.
- `GameDeviceSyncStatus` uses internal enum terminology (SYNCED, OUT_OF_SYNC, DOWNLOADING, NO_DELIVERY) without explanation.
- Rename affordance has no visual hint (no pencil icon, no hover underline).
- No breadcrumb navigation.
- SHA256 and transaction_id shown raw, without truncation or copy affordance.
- No snapshot count or date range shown at page top.
- Delete snapshot action has no confirmation dialog.

**Information Architecture Problems:**
- Device sync matrix and snapshot lineage are conceptually linked but visually separated with no connector.
- HEAD snapshot is not visually prominent — same styling as all others.
- "Restore" action terminology is ambiguous — restore to what? Which device?

**Mobile:** Snapshot table overflows. Device sync cards stack but lose visual context. Practically unusable.

---

### 4. DevicesPage

**Purpose:** List of registered devices, revoke action.

**Complexity:** Low | **Clarity:** Medium | **Density:** Low | **Visual Quality:** Poor

**Pain Points:**
- Table-only presentation. No visual identity for devices (no hardware type icon).
- "Last seen" shown as absolute timestamp — relative time is more useful.
- Online/offline status absent — user must mentally compute from last_seen threshold.
- Rename action missing from list view.
- No empty state for first-time users.
- No search or filter.

**Mobile:** Table rows too wide. No responsive reflow.

---

### 5. DeviceDetailPage

**Purpose:** Per-device configuration — games, sync preferences, rename, revoke.

**Complexity:** Medium | **Clarity:** Medium | **Density:** Medium | **Visual Quality:** Poor

**Pain Points:**
- Device info card mixes rarely-needed fields (device_id, MAC) with actionable fields (display_name, online status).
- Toggle switches for per-game sync have no save button, no confirmation, no undo.
- Hardware type shown as plain text — missed opportunity for icon treatment.
- "Online" indicator has no tooltip explaining the 5-minute threshold.
- No "last sync activity" for the device.
- Revoke button styled as destructive without explaining consequences (data remains on server).

**Mobile:** Reasonably functional (single column). Toggle switches too small for touch.

---

### 6. EventsPage

**Purpose:** Audit stream of all system events.

**Complexity:** Low | **Clarity:** Medium | **Density:** Low | **Visual Quality:** Poor

**Pain Points:**
- Hard 200-event limit with no pagination.
- Event `event_type` values are raw enum strings (UPLOAD_STARTED, SYNC_COMPLETED).
- No filtering by event type, device, or game.
- No time-period grouping (today, yesterday, last week).
- Link navigation from event rows to game/device detail is not discoverable.
- No export.

**Visual Issues:**
- Flat table with no visual rhythm. All events styled identically regardless of severity.
- Absolute ISO timestamps throughout.

---

### 7. SettingsPage

**Purpose:** Token rotation, RomM username mapping.

**Complexity:** Low | **Clarity:** Low | **Density:** Low | **Visual Quality:** Poor

**Pain Points:**
- Token rotation shows new token inline with no copy affordance and no storage guidance.
- RomM username mapping has no explanation of purpose.
- No validation on RomM username field.
- Auth section and RomM section visually undifferentiated — unrelated concerns mixed.
- No server version / about information.

---

### 8. NotificationDrawer

**Purpose:** Show unacknowledged errors (failed transactions).

**Complexity:** Low | **Clarity:** Medium | **Density:** Medium | **Visual Quality:** Poor

**Pain Points:**
- "Errors" conflates failed transactions with user-actionable alerts.
- "Dismiss all" clears notification state without explaining whether the underlying issue is resolved.
- Error items show raw transaction_id values.
- No retry action inline — user must navigate to game detail.
- High error badge counts create anxiety without resolution path.

---

### 9. ConflictResolverModal

**Purpose:** User selects which snapshot becomes HEAD during a conflict.

**Complexity:** High | **Clarity:** Low | **Density:** Low | **Visual Quality:** Poor

**Pain Points:**
- Only offers "push this snapshot to all devices" with no explanation of consequences for the other snapshot.
- No side-by-side comparison of conflicting snapshots (timestamp, device, sequence number).
- No visualization of the branch divergence point.
- The losing snapshot becomes SUPERSEDED silently — never communicated.
- No confirmation step before pushing.
- Terminology is internal ("push snapshot" vs. user goal "restore to all devices").

---

## Summary Scores

| Screen             | Complexity | Clarity | Density | Visual Quality |
|--------------------|-----------|---------|---------|---------------|
| AuthPage           | 2/10      | 5/10    | 2/10    | 3/10          |
| Dashboard          | 7/10      | 3/10    | 2/10    | 3/10          |
| GamePage           | 9/10      | 3/10    | 4/10    | 3/10          |
| DevicesPage        | 3/10      | 5/10    | 3/10    | 3/10          |
| DeviceDetailPage   | 5/10      | 5/10    | 4/10    | 3/10          |
| EventsPage         | 3/10      | 4/10    | 3/10    | 3/10          |
| SettingsPage       | 2/10      | 3/10    | 2/10    | 2/10          |
| NotificationDrawer | 4/10      | 5/10    | 5/10    | 3/10          |
| ConflictResolver   | 8/10      | 2/10    | 2/10    | 2/10          |

*Complexity = inherent domain complexity. Clarity = how well UI communicates it. Density = information per viewport (higher is better for tool UIs). Visual Quality = aesthetic execution.*

---

## Cross-Cutting Problems

### 1. Global Visual Inconsistency
MUI default theme with minimal customization. Nothing feels OmniSave-specific. Inconsistent border radius, spacing, and elevation across components.

### 2. Information Architecture Failure
No screen has a clear primary question it answers instantly. The hierarchy defined in `context/server/08-frontend-ui.md` (State > Exceptions > Activity > Audit) is not implemented. No breadcrumbs.

### 3. Operational Blindness
Healthy and unhealthy system states receive identical visual treatment. Error urgency is not communicated through visual weight. No progressive disclosure.

### 4. Mobile Failure
Tables do not reflow. Horizontal scroll card row breaks. Touch targets undersized. No mobile-specific navigation pattern.

### 5. Terminology Problems
Raw enum strings shown to users (UPLOADING, READY_FOR_RESTORE, SUPERSEDED). Internal IDs shown without truncation or copy affordance. Action labels use internal language ("push", "inbound", "outbound") instead of user-goal language ("restore", "sync", "deliver").
