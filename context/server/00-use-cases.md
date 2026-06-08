# 00-use-cases.md — OmniSave Core User Flows

Defines **only user-visible flows** in OmniSave. Everything else: internal automation.

Guiding principle:
> System invisible unless fails. When fails, user picks snapshot.

As the exec, here's my response. No. The user should never be bothered by the conflict. WE go to restore a save on device. WE can check it before we restore to see if the on partition save has changed or not versus what we loaded last. We should check that first. If it does differ, we should upload it to the server asap, mark it as a different lineage and continue our restore. That way, if we did happen to overwrite something, at least the user could manually push that "soft conflict" save back. We would check that the existing partition didnt change since the last restore and restore their soft conflict pushed save safely. Is this the direction you are taking us ? if not you need to tell your dev (claude) specifically how to get there, while reassuring me (the exec) you're meeting my vision


---

# 1. Normal Operation (Zero Interaction Flow)

## Trigger
User plays any game on any device (Switch, PC, emulator, Android client).

## System Behavior
- Detect game close or save event
- Extract save data
- Create immutable snapshot
- Upload to server
- Server stores snapshot
- HEAD updated automatically
- Other devices converge to HEAD

## User Experience
- No required interaction
- Optional toast: "Sync complete"
- Dashboard may update last sync time

## Outcome
- Saves always backed up
- Devices auto-synced
- No user awareness required

---

# 2. First-Time Device Registration (One-Time Setup)

## Trigger
New device connects with unseen `device_id`.

## System Behavior
- Server registers device
- Associates with incoming snapshot(s)
- Marks device `unverified`

## UI Behavior (Only setup interaction in system)

Dashboard shows:
> New device detected

Fields:
- Device fingerprint (masked/short ID)
- Suggested name (optional)

Actions:
- Approve device
- Rename device
- Reject device

## User Action
- Approve + optionally name device

## Outcome
- Device becomes trusted
- Joins silent sync network
- No further prompts unless reinstalled or reset

---

# 3. Snapshot Conflict / Divergence

## Trigger
Two+ devices produce different saves for same game while offline.

Example:
- Switch plays Game → Snapshot A
- PC plays same Game → Snapshot B

## System Behavior
- Both snapshots stored
- Neither discarded
- Server cannot safely determine single HEAD

## UI Behavior (Game View)

Game shows:
> Conflict detected — multiple active saves

Snapshot list:
- Snapshot A (Switch, timestamp)
- Snapshot B (PC, timestamp)

Labels:
- One may be marked `[HEAD (current)]` or ambiguous state

## User Action
Only action available (UI only — device never initiates this):
- **Make Active**

User selects one snapshot.

## System Result
- Selected snapshot becomes HEAD
- Other snapshot remains archived
- No deletion
- Timeline divergence preserved

## Key Principle
> No diffing, no merging, no comparison UI.

---

# 4. Error / Recovery Flow

## Trigger
System detects failure:
- upload failure
- restore failure
- missing chunks
- storage error
- server unreachable during critical operation

## System Behavior
- Preserve all existing snapshots
- Do NOT overwrite data
- Mark transaction failed or pending retry

## UI Behavior (Dashboard)

Game or system shows:
> ⚠ Sync Error

Details:
- Reason (short, human readable)
- Affected game/device

Actions:
- Retry
- Open snapshots

## User Action
- Retry operation OR
- Manually select snapshot

## Outcome
- System recovers without data loss
- No automatic destructive fixes

---

# 5. Device Replacement / Re-Linking

## Trigger
Device reinstalled, reset, or appears with new identity but existing save history.

## System Behavior
- Detect overlapping lineage or similar game history
- Flag potential duplicate device identity

## UI Behavior

Prompt:
> This device appears to contain existing save history

Options:
- Merge into existing device
- Register as new device

## User Action
- Choose identity resolution

## Outcome
- Either unified device timeline or split device history
- No silent duplication

---

# 6. Snapshot Pruning (Storage Control)

## Trigger
- Game has excessive snapshot history
- User requests cleanup
- Storage pressure threshold reached

## UI Behavior (Game View → Snapshot List)

Each snapshot shows:
- timestamp
- device origin
- optional HEAD label
- delete icon

Bulk actions:
- Keep last N snapshots
- Delete selected snapshots

## User Action
- Delete individual snapshots OR
- Bulk prune

## System Behavior
- Deletes only selected snapshots
- Never deletes HEAD unless explicitly chosen
- Never affects other branches automatically

---

# 7. Passive Browsing (Informational Mode)

## Trigger
User opens dashboard without specific goal.

## UI Behavior

Dashboard shows:
- list of games (deduplicated)
- last sync time per game
- current HEAD snapshot per game
- device status overview

No prompts or forced actions.

## Outcome
- Pure observability layer
- No required interaction

---

# SYSTEM SUMMARY

OmniSave has exactly **four interaction primitives**:

1. Approve new device (once per device)
2. Choose snapshot when conflict exists (UI only — not available on device)
3. Retry when error occurs
4. Delete snapshots when storage full

Everything else fully automated.

---

# DESIGN GUARANTEE

> User should never think about sync, lineage, or conflict.
> Only ever see snapshots when system cannot safely choose one.
