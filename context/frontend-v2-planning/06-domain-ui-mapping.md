# 06 — Domain-UI Mapping

Maps every OmniSave domain concept to its visual representation, user-facing terminology, and interaction model.

---

## Core Rule

**Never expose internal enum names to users.** Raw states like `READY_FOR_RESTORE`, `SUPERSEDED`, `INBOUND` are developer vocabulary. Every domain concept maps to user-goal language.

---

## Snapshot

**Domain definition:** An immutable archive of a game's save data at a point in time. Identified by `transaction_id`, numbered by `snapshot_sequence`.

**User mental model:** A saved version of a game, like a commit in git or a backup point in time.

**User-facing term:** **Save** (in action contexts), **Snapshot** (acceptable in technical detail views)

**Visual representation:**

| Context | Representation |
|---------|---------------|
| In lineage graph | `SnapshotNode` — rectangular node with sequence number, device label, timestamp, and state indicator |
| In history list | `SnapshotRow` — compact table row with sequence number, device, timestamp, size, state badge |
| In conflict workspace | `SnapshotCard` — full card with all details side-by-side |
| In dashboard | Not shown directly — aggregated into game status |

**State → Visual mapping:**

| Internal state | User label | Color | Icon |
|---------------|------------|-------|------|
| HEAD / COMMITTED | **Current** | `--color-success` | `GitCommit` |
| PERSISTED | **Saved** | `--color-info` | `GitCommit` |
| RECEIVED (inbound) | **Received** | `--color-neutral` | `Download` |
| CONFLICT_BRANCH | **Conflict** | `--color-warning` | `GitBranch` |
| FAILED | **Failed** | `--color-error` | `XCircle` |
| SUPERSEDED | **Archived** | `--color-neutral` (dim) | `Archive` |

**Actions available by state:**

| State | User-facing action |
|-------|-------------------|
| HEAD | "Push to devices" (re-deliver) |
| CONFLICT_BRANCH | "Make this the current save" |
| Any non-failed | "Delete" (with confirmation) |
| FAILED | (no action except delete) |

---

## HEAD

**Domain definition:** The snapshot with the highest `snapshot_sequence` among non-conflict committed inbound transactions. The authoritative save for a game.

**User mental model:** "The most recent good save" — the version all devices should converge to.

**User-facing term:** **Current Save**

**Visual representation:**
- In lineage graph: `SnapshotNode` with `head` variant — accent border, "CURRENT" badge in top-right corner, larger visual weight.
- In game detail header: displayed prominently as "Snapshot #42 · 3 hours ago"
- In device sync matrix: "Cloud #42" in the Cloud # column

---

## Conflict

**Domain definition:** When two devices upload different saves while offline, both descend from the same parent sequence but diverge. `has_conflict = 1` on one branch.

**User mental model:** Two different versions of the game exist that can't be automatically merged — like two people editing the same document.

**User-facing term:** **Conflict** (retained — users understand this concept)

**Visual representation:**

| Context | Representation |
|---------|---------------|
| Game card | Amber `StatusBadge` ("CONFLICT"), amber left border on card |
| Dashboard health row | Counted in error state or as a distinct warning |
| Library list | Game row highlighted with amber left border |
| Nav badge | Library badge shows conflict count |
| Game detail | `ConflictBanner` — full-width amber banner with details |
| Lineage graph | Conflict branch nodes in amber, divergence point labeled |

**ConflictBanner content:**
- Title: "Two conflicting saves exist"
- Body: "Your Switch OLED and Switch Lite saved at different points while offline. You need to choose which version to keep."
- CTA: "Resolve Conflict"

**Resolution flow:**
1. User clicks "Resolve Conflict" from anywhere conflict is shown.
2. `ConflictWorkspace` modal opens showing both snapshots side-by-side.
3. User selects one snapshot.
4. Confirmation step: "This will make Snapshot #42 the current save for all devices. Snapshot #41 will be archived (not deleted)."
5. POST to `/api/v1/ui/snapshots/{txn}/push`.
6. Modal closes. Game status updates to SYNCED.

---

## Transaction

**Domain definition:** A unit of sync work — either inbound (device uploads to server) or outbound (server delivers to device). Has state machine: UPLOADING → PROCESSING → READY_FOR_RESTORE → COMPLETED (or FAILED).

**User mental model:** Not visible as a concept. Users think in terms of "syncing" or "downloading" — they don't need to know transactions exist.

**User-facing visibility:** Only in error states (when a transaction fails, it surfaces as an "error" requiring acknowledgment).

**State → User language:**

| Internal state | Direction | User label | Status |
|---------------|-----------|------------|--------|
| UPLOADING | inbound | "Uploading..." | In progress |
| PROCESSING | inbound | "Processing..." | In progress |
| READY_FOR_RESTORE | outbound | "Ready to download" | Pending |
| COMPLETED | any | (silent — no user-facing state) | Done |
| FAILED | inbound | "Upload failed" | Error |
| FAILED | outbound | "Download failed" | Error |
| SUPERSEDED | outbound | (silent — archived) | — |

**Visual representation of failed transactions:**
- In `NotificationDrawer`: Each error is a row showing game name, device name, direction (upload/download), and timestamp. NOT the raw transaction_id.
- In `ActivityPage`: Shown as error event row.

---

## Device

**Domain definition:** Hardware identity identified by MAC address (`device_id`). Has `display_name`, `hardware_type`, `last_seen`.

**User mental model:** A physical gaming device — their Switch, their PC.

**User-facing term:** **Device** (retained)

**Visual representation:**

| Context | Representation |
|---------|---------------|
| Device list | `DeviceCard` with hardware icon, display name, online indicator, game count |
| Device detail | Full page with sync preferences |
| Game sync matrix | Row per device showing sync state |
| Event feed | Device name (from label, fallback to truncated ID) |
| Error drawer | Device name |

**Online/offline determination:**
- Online: `last_seen` within 5 minutes.
- Display: green pulsing dot + "Online" label.
- Offline: grey dot + "Last seen X ago".

**Hardware type icons:**
- Switch (any): `Gamepad2` icon
- Additional variant badge ("OLED", "Lite") as small text label alongside

**Rename behavior:**
- `InlineEdit` component on device name.
- Saves to `labels` table via `PUT /api/v1/ui/labels/device/{device_id}`.
- Optimistic update.

**Revoke Device:**
- User-facing term: "Remove Device"
- Description in confirm dialog: "This device will no longer sync saves. Your existing saves on OmniSave are not deleted."
- Button label: "Remove Device"
- Confirm dialog variant: `destructive`

---

## Upload

**Domain definition:** Inbound transaction — device sends save data to server.

**User mental model:** "Saving to the cloud" or "syncing." Automatic — happens on game close.

**User-facing term:** "Synced" or "Uploaded" (past tense). "Syncing" (in progress, if ever shown).

**Visual representation:**
- In activity feed: "Uploaded · Zelda: TOTK · Switch OLED · 2h ago"
- Status badge: `Upload` icon (Lucide) + timestamp
- In progress: progress bar (only shown if polling reveals in-progress transaction; rare in practice since uploads are fast)

---

## Download / Delivery

**Domain definition:** Outbound transaction — server delivers a snapshot to a device via the `READY_FOR_RESTORE` → `COMPLETED` flow.

**User mental model:** "The Switch received the latest save." Automatic — happens on device boot/wake.

**User-facing term:** "Downloaded" (past), "Downloading" (in progress).

**Visual representation:**
- In device sync matrix: "Downloading..." state row
- In activity feed: "Downloaded · Zelda: TOTK · Switch Lite · 6h ago"

---

## Lineage

**Domain definition:** The parent-child chain of snapshots via `parent_sequence_num`. Enables detection of divergent branches.

**User mental model:** "The history of saves for a game." Like git commit history.

**User-facing term:** **Save History**

**Visual representation:**
- `LineageGraph` on the History sub-page of Game Detail.
- Canonical chain: vertical flow, newest at top.
- Conflict branch: forks to the right.
- Nodes: `SnapshotNode` components.
- Branch labels: device name.

**Simplified view for mobile:**
- Linear list of snapshots in reverse chronological order.
- Conflict branch snapshots shown with amber left border, labeled "[Device] — Conflict branch".

---

## Sequence Number

**Domain definition:** `snapshot_sequence` — monotonically increasing integer per game across all devices. Assigned server-side.

**User mental model:** Save version number. "Save #42 is the latest."

**User-facing term:** "#42" (short form), "Version 42" (long form in detail contexts)

**Visual representation:**
- Always monospace font (`--font-mono`).
- Displayed prominently in snapshot nodes, game headers, device sync matrix.
- Range: shown as "#38 → #42" when displaying sync delta.

---

## SHA256 / Fingerprint

**Domain definition:** `sha256` hash of the save archive. Used for integrity verification.

**User mental model:** Not relevant to most users. Available for technical verification.

**User-facing visibility:** Detail views only. Never in list contexts.

**Visual representation:**
- First 12 characters displayed in monospace.
- Full value in tooltip.
- `Copy` button on hover.
- Label: "Fingerprint" (more approachable than "SHA256 hash")

---

## Admin Token

**Domain definition:** The single bearer token for UI authentication. Stored in `server_config` table.

**User mental model:** "The password to the dashboard."

**User-facing term:** **Access Token**

**Visual representation:**
- On first setup: displayed once in a code block with explicit copy button and instruction to save it.
- After rotation: same treatment.
- Stored: in localStorage under `os_token`.

**Bootstrap flow user language:**
- Step 1: "Your OmniSave server is ready."
- Step 2: "Save this access token — you'll need it to log in."
- [Access Token display with copy button]
- Step 3: [Continue button]

---

## Polling / Live Data

**Domain definition:** Client-side polling at fixed intervals (15s dashboard, 20s activity, 30s errors).

**User mental model:** Data is live. The dashboard "just knows" what's happening.

**Visual representation:**
- No visible polling indicator (polling is invisible when healthy).
- "Last updated" timestamp in top-right of dashboard (subtle, secondary text).
- On poll failure: offline detection → `OfflineBanner`.
- Retry countdown visible in `OfflineBanner`.

---

## RomM Integration

**Domain definition:** Read-only metadata service providing game names and icons via `romm_game_cache` and `romm_title_map`.

**User mental model:** "Where game icons and names come from" — invisible when working.

**User-facing visibility:**
- Game icons displayed from RomM cache URL (with fallback to generic Gamepad2 icon if unavailable).
- Game names from RomM cache (with fallback to title_id truncated).
- RomM username mapping in Settings → Integrations.
- No other RomM UI exposure.

**Fallback handling:**
- Icon not available: generic `Gamepad2` icon in `--color-text-muted`.
- Name not available: title_id first 12 chars + ellipsis in monospace.

---

## Terminology Quick Reference

| Internal term | User-facing term |
|--------------|-----------------|
| snapshot | save, snapshot (technical) |
| transaction | (hidden) |
| HEAD | Current Save |
| SUPERSEDED | Archived |
| READY_FOR_RESTORE | Ready to download |
| inbound | (upload, from device perspective) |
| outbound | (download, from device perspective) |
| has_conflict | Conflict |
| device_id | Device ID (truncated) |
| transaction_id | (hidden unless error) |
| snapshot_sequence | #N (save number) |
| sha256 | Fingerprint |
| admin_token | Access Token |
| bootstrap | Setup |
| acknowledge (error) | Dismiss |
| push (snapshot) | Restore to all devices |
| revoke (device) | Remove device |
