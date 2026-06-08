This brings the architecture to its logical conclusion. The system is no longer just a set of APIs; it is a **Deterministic UI Commit Graph System**. By enforcing strict monotonicity, acyclicity, and single-parent constraints, the frontend is reduced to a pure function: `render(revision) -> UI`.

The addition of the **Revision Graph Integrity Contract** and the **Global Projection Invariant** closes the final gaps, ensuring that "time travel" debugging and deterministic test harnesses are mathematically sound.

Here is the finalized specification, incorporating these critical invariants.

---

# OmniSave V1: UI-API Projection Stability & Identity Specification

## 1. Architectural Objective

The UI-API is formally defined as a **versioned projection engine over an event-sourced distributed state machine with deterministic UI replay semantics.** Its objective is to guarantee both the structural continuity and the temporal stability of data, shielding the frontend from distributed systems logic, transport flapping, and network noise.

The frontend is strictly a pure deterministic renderer over a strictly controlled, verified revision graph.

## 2. Projection Identity & Lineage Model

A projection is an observable manifestation of a specific entity's state graph. It acts as a "UI commit," maintaining a strict lineage to enable deterministic replay, rollback debugging, and time-travel stepping.

### 2.1 Identity Attributes

Every UI-API response MUST embed a `_metadata` block defining its exact identity and lineage.

* **`view_scope`:** The isolated boundary of the projection (e.g., `GLOBAL_DASHBOARD`, `GAME_LINEAGE`).
* **`entity_id`:** The primary subject of the scope (e.g., `0100F2C0115B6000`); `null` for global scopes.
* **`revision_id`:** A monotonically increasing integer representing the UI-visible version of this specific projection scope. Acts as the UI commit hash.
* **`previous_revision_id`:** The immediate ancestor of this revision.
* **`snapshot_cursor`:** The underlying database commit timestamp (`MAX(global_commit_timestamp)`) used to anchor the graph evaluation.

### 2.2 Global Projection Invariant

At any point in time, for a given `view_scope` and `entity_id`, there exists exactly **one** valid active `revision_id` that represents the latest stable projection state. This strictly prevents dual-head UI states and split-brain dashboard rendering.

## 3. The Revision Emission Engine

The UI-API employs a strict emission engine to determine when a new `revision_id` is born.

### 3.1 Revision Emission Function

A new `revision_id` MUST be emitted if and only if the semantic truth of the projection has changed.

**Canonical Rule:**

```text
normalize(projection_state, snapshot_cursor) != normalize(previous_projection_state, previous_snapshot_cursor)

```

The `normalize()` function MUST explicitly enforce:

1. **Stable Ordering:** All arrays must be deterministically sorted.
2. **Semantic Field Isolation:** Non-semantic fields (e.g., physical timestamps used strictly for display) MUST be stripped prior to evaluation.
3. **Canonicalization of Math:** Floating/incremental progress values must be clamped and stepped according to mathematical checkpoint boundaries.

### 3.2 Revision Coalescing Window

Candidate revision triggers inside a rolling time window $\Delta t$ (e.g., 1000ms) MUST be coalesced into a single `revision_id` emission, UNLESS a critical boundary is crossed (Terminal state, Conflict emergence, or HEAD change).

## 4. Revision Graph Integrity Contract

To support deterministic replay and ensure temporal sanity, the sequence of emitted projections MUST adhere to strict graph invariants.

### 4.1 Invariants

The revision graph must remain a connected, acyclic, strictly monotonic chain per `view_scope`.

1. **Monotonicity:** `revision_id(n+1) > revision_id(n)`
2. **Acyclicity:** `previous_revision_id` MUST NEVER point to a future or sibling revision.
3. **Single-Parent Constraint:** Each revision MUST have exactly one parent per `view_scope`.
4. **No Orphan Projections:** Every emitted revision MUST trace back to an initial genesis revision.

### 4.2 Replay Boundary Definition

A projection replay is defined as the deterministic reconstruction of a contiguous revision subgraph bounded by two `revision_ids` within a single `view_scope`.

## 5. Projection Stability Contract

### 5.1 Temporal Stability (Anti-Flapping)

The state payload will not flicker across polling cycles. Intermediate UI states and transient lease drops (recovered within the $\Delta t$ window) are completely invisible to the frontend.

### 5.2 Structural Stability (Schema Invariance)

The object shape and data contract of a `view_scope` will not mutate between revisions. The frontend is guaranteed that no runtime schema inference is necessary.

## 6. Projection Delta Model & Causality Tags

The `_delta` block MUST include a `semantic_transition` enum, allowing the frontend to distinguish between "re-render the DOM," "animate a progress bar," and "interrupt a modal flow."

Strict Enum Values:

* `STATE_TRANSITION` (Phase shift, e.g., `UPLOADING` $\rightarrow$ `PROCESSING`)
* `PROGRESS_UPDATE` (Checkpoint validated)
* `ENTITY_MUTATION` (Renaming/Revocation)
* `CONFLICT_EMERGENCE` (Divergent timeline detected)
* `HEAD_CHANGE` (Canonical save state updated)
* `DEVICE_SYNC_CHANGE` (Hardware presence update)

## 7. Response Payload Structure Template

All UI-API endpoints MUST conform to this deterministic envelope:

```json
{
  "_metadata": {
    "view_scope": "GAME_LINEAGE",
    "entity_id": "0100F2C0115B6000",
    "revision_id": 10292,
    "previous_revision_id": 10291,
    "snapshot_cursor": 1685232000
  },
  "_delta": {
    "changed_fields": [
      "device_sync_matrix[1].sync_state",
      "device_sync_matrix[1].active_transfer.progress_percentage"
    ],
    "semantic_transition": "PROGRESS_UPDATE"
  },
  "data": { ... Route-specific structurally stable view model ... }
}

```