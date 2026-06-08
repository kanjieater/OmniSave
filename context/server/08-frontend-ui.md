# OmniSave V1: Frontend Implementation Specification

This document defines the strict UI contracts, state models, and routing requirements for the OmniSave web client. All of this should be allowed for use on desktop and mobile.

## 0. Global Frontend Principles

### 0.1 The Presentation Mapping Rule (Strict)

The UI MUST NEVER expose raw system identifiers outside of an explicit "Developer/Debug" toggle. The frontend is strictly a consumer of resolved display names:

* `title_id` (e.g., `0100F2C0115B6000`) ➔ **Game Title string + Box Art/Icon image**.
* `device_id` (MAC) ➔ **Friendly Display Name** (e.g., "Switch OLED", "Living Room PC").
* `snapshot_sequence` ➔ **Snapshot Sequence Number** (e.g., "Save #42").

### 0.2 Interaction Lifecycle (Optimistic vs. Pessimistic)

* **Destructive/State-Changing Actions** (e.g., Change HEAD, Prune, Revoke Device, ACK Error): Must be *Pessimistic*. The UI enters a `MUTATING` state and waits for the `200 OK` from the API before updating the DOM.

### 0.3 Data Freshness & Polling Halts

The UI relies on short-polling to remain eventually consistent with the device sync network.

* **Pause Rule:** All background polling MUST be strictly paused while a `MUTATING` or `PRUNING` state is active to prevent race conditions from overwriting pending UI states.
* **Update Contract:** Polling updates must be processed as full replacements. No incremental patch diffing.

### 0.4 Global API Failure Contract (The Circuit Breaker)

* **Trigger:** 3 consecutive failed polling requests.
* **State Transition (`GLOBAL_OFFLINE`):**
1. The Global Exception Banner is completely overridden by a critical red banner: *"OmniSave Server Unreachable."*
2. All mutation actions globally are immediately disabled.
3. Standard polling halts. Enters an exponential backoff ping (max 60s).


* **Recovery:** Upon a `200 OK` health ping, the `GLOBAL_OFFLINE` state clears and standard polling resumes.

### 0.5 UI Information Hierarchy (Source of Truth Rules)

All system observability surfaces MUST derive from the following strict hierarchy to prevent cognitive overlap:

* **Level 1 — State Views (Authoritative Truth):** Define current reality. State-driven, not event-driven.
* `/game/:title_id` (Snapshot state + device sync state)
* `/devices` (Device trust + health)
* Dashboard Game Cards (Condensed state projection)


* **Level 2 — Actionable Exceptions (Required Decisions):** Override all other feeds when present.
* Exception Banner (Conflicts, upload failures, new unverified devices).
* Notification Bell (Device-side errors requiring manual ACK).


* **Level 3 — Activity Feed (User-Centric Narrative):** Dashboard `LiveEventFeed` only. A curated stream of meaningful gameplay/sync changes. A convenience view, not a source of truth.
* **Level 4 — Event Log (System Truth):** `/events`. Immutable audit stream. Debuggable history only. NEVER used to derive UI state.

---

## 1. Route Map

The application consists of a single layout shell wrapping four primary routes.

* **`/`** ➔ Redirects to `/dashboard`.
* **`/dashboard`** ➔ Global status, exception queue, user-centric recent activity.
* **`/game/:title_id`** ➔ Snapshot lineage for a specific game.
* **`/devices`** ➔ Hardware trust management.
* **`/events`** ➔ System-wide immutable audit stream.

---

## 2. Global Modal & Exception System

### 2.1 The Global Exception Banner

* **Render Rule:** If pending exceptions exist, render a sticky banner directly below the top nav.
* **Priority Ordering Rule:** `CONFLICT` > `UPLOAD_ERROR` > `NEW_DEVICE`.
* **Collapse Rule:** Display top 3 highest-priority exceptions. Collapse remainder into "+N more issues".

### 2.2 The Notification Bell (Device Error Hub)

Located in the global top nav. Tracks hardware errors requiring two-way acknowledgment.

* **Render Rule:** Red badge with unacknowledged error count. Clicking opens a popover.
* **Two-Way ACK Lifecycle:** 1. User clicks **"Acknowledge & Clear"**. Button enters `MUTATING`.
2. API Call fired. Server marks DB resolved and queues a physical client clear command.
3. On `200 OK`, error is removed from UI.

### 2.3 Global Modal Stack

* **Rule:** Modals stack via Z-Index. Only one transactional modal active at a time.
* **Dismissal Rule:** Transactional modals CANNOT be dismissed by clicking the background overlay.

---

## 3. Screen Contracts & State Models

### 3.1 Screen: `/dashboard`

**State Model (Enum):**

* `LOADING_DASHBOARD`
* `READY`
* `ERROR_FETCH`
* `EMPTY_SYSTEM`

**Component 1: `RecentGamesRow` (Top Section)**

* **Render Rule:** Horizontal scrolling cards of the 10 most recently synced titles. Click routes to `/game/:title_id`.
* **Data:** `{ titleId, gameName, gameIconUrl, lastSyncedAt, headSequenceNum, status: 'SYNCED' | 'CONFLICT' | 'ERROR' }`

**Component 2: `DeviceStatusOverview` (Middle Section)**

* **Render Rule:** Compact pills showing hardware status.
* **Data:** `{ deviceId, deviceName, hardwareType, connectionState: 'ONLINE' | 'OFFLINE', lastPingAt, hasPendingUpload }`

**Component 3: `LiveEventFeed` (Bottom Section)**

* **Render Rule:** User-centric timeline (Level 3 Hierarchy). Infinite scroll.
* **Data:** `{ eventId, timestamp, eventType, status, summary, gameIconUrl?, deviceName?, entityLink? }`

### 3.2 Screen: `/game/:title_id`

**State Model (Enum):**

* `LOADING_GAME_DATA`
* `READY`
* `MUTATING_HEAD`
* `PRUNING`
* `EMPTY_SNAPSHOTS`

**Component 1: `GameDeviceSyncStatus` (The Device Projection)**

* **Render Rule:** Row of cards answering "Is this physical device up to date with the cloud?"
* **Data Contract (The Projection Model):** The frontend relies entirely on this server-derived object; it does not calculate sync math locally.
```typescript
{
  deviceId: string;
  deviceName: string;
  hardwareType: string;
  syncState: 'SYNCED' | 'DOWNLOADING' | 'OUT_OF_SYNC' | 'GAME_RUNNING';
  localSequenceNum: number | null; // What is physically on the SD card
  cloudHeadSequenceNum: number;    // What the cloud says it should have
  lastSeenAt: string;
}

```



**Component 2: `SnapshotList` (The Lineage)**

* **Sorting Rule:** Strict descending order by `timestamp`.
* **HEAD Invariance Rule:** Exactly ONE snapshot can have `isHead = true`.
* **Identity Stability Rule:** `sequenceNum` is immutable and globally unique. Disappearing snapshots are considered pruned.
* **Interaction:** Clicking "Make Active" invokes the pessimistic `MUTATING_HEAD` flow (UI API only — not callable from device).
* **Data:** `{ sequenceNum, timestamp, deviceName, isHead, hasConflict }`

### 3.3 Screen: `/devices`

**State Model (Enum):**

* `LOADING_DEVICES`
* `READY`
* `EMPTY_TRUSTED`

**Component 1: `PendingDeviceQueue**`

* **Render Rule:** Only renders if unapproved devices exist. Requires explicit "Approve" or "Reject".

**Component 2: `TrustedDeviceList**`

* **Interaction Rule:** Clicking "Revoke" triggers a destructive confirmation modal.
* **Data:** `{ deviceId, deviceName, hardwareType, lastSeen, syncCount }`

### 3.4 Screen: `/events` (System Audit Stream)

**State Model (Enum):**

* `LOADING_EVENTS`
* `READY`
* `ERROR_FETCH`
* `EMPTY_EVENTS`

**Component: `SystemEventLog**`

* **Strict Observability Rule:** Read-only historical audit stream (Level 4 Hierarchy). The frontend MUST NEVER derive application state from this stream.
* **Rendering Rules:** Strict chronological ordering (newest first). Infinite scroll. No nesting.
* **Data:** `{ eventId, timestamp, type, summary, entityLink? }`

---

## 4. Specific Modal Contracts

### 4.1 The Conflict Resolver Modal

* **Trigger:** Click "Resolve" on a conflict banner or `SnapshotList`.
* **State Block:** Halts background polling for this `title_id`.
* **Layout Rule:** Strictly two columns side-by-side representing divergent saves.
* **Commit Action:** Emits "Make Active" lifecycle via UI API. Closes modal on `200 OK`.

### 4.2 The Storage Pruner Modal

* **Trigger:** Click "Prune Storage" in `/game/:title_id`.
* **Form State:** Radio buttons (`Keep Last 5`, `Delete older than 30 days`).
* **Commit Action:** Pessimistic `DELETE` call. Modal shows loading state until complete.

### 4.3 Upload Failure Recovery Modal

* **Trigger:** User clicks an `UPLOAD_ERROR` exception.
* **Options:**
* **"Wait for Retry"** (Dismisses modal, relies on device polling).
* **"Abort Upload"** (Marks transaction FAILED, reverts to previous HEAD).