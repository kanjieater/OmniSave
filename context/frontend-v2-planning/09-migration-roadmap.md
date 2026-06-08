# 09 — Migration Roadmap

Phased migration from V1 (Material UI) to V2 (shadcn/ui + Tailwind v4). Each phase delivers a releasable increment.

---

## Guiding Principles

1. **Parallel build, not big-bang rewrite.** V2 components live alongside V1 components. Pages migrate one at a time. Users see a working UI at every phase.
2. **MUI removal is the last step.** Don't waste time removing MUI early — focus on building V2 first.
3. **Type safety gates every step.** `npx tsc --noEmit` must pass before any phase is declared done.
4. **No new features during migration.** Design system work is not the time to add capabilities. Migrate what exists; extend afterward.

---

## Phase 0: Foundations

**Goal:** Development environment and token system ready. No user-visible changes.

**Duration estimate:** 1–2 days

### Tasks

1. Install dependencies:
   ```bash
   npm install tailwindcss@4 @tailwindcss/vite lucide-react
   npm install @radix-ui/react-dialog @radix-ui/react-dropdown-menu @radix-ui/react-tooltip
   npm install @radix-ui/react-switch @radix-ui/react-select
   npm install @tanstack/react-query @tanstack/react-virtual @tanstack/react-table
   npm install tailwindcss-animate class-variance-authority clsx tailwind-merge
   ```

2. Configure Tailwind v4 in `vite.config.ts`:
   ```ts
   import tailwindcss from '@tailwindcss/vite'
   plugins: [react(), tailwindcss()]
   ```

3. Create `src/styles/tokens.css` — the complete token system from `03-design-system.md`. This file defines all `@theme` variables.

4. Create `src/styles/globals.css` — imports tokens, sets base HTML/body styles to dark theme, applies `font-sans` to body.

5. Update `main.tsx` to import `globals.css` (replaces current `index.css`).

6. Create `src/lib/utils.ts` — `cn()` helper (clsx + tailwind-merge).

7. Create `src/components/ui/` directory. This is where shadcn/ui components will live.

8. Add `src/components/ui/button.tsx` — first shadcn component via `npx shadcn add button`. Verify it renders with design tokens.

9. Wire TanStack Query: create `src/lib/queryClient.ts` with global config (retry: 3, staleTime: 30s).

**Deliverables:**
- Token file established.
- Tailwind v4 building without errors.
- shadcn/ui Button rendering with correct dark theme.
- TanStack Query provider wrapping the app.

**Risks:**
- Tailwind v4 + Vite config conflicts with existing Vite setup. Mitigation: upgrade to Vite 6 if needed.
- CSS specificity conflicts between existing MUI styles and new Tailwind utilities. Mitigation: prefix Tailwind utilities with a container class during transition.

**Dependencies:** None (can start immediately).

---

## Phase 1: Design System

**Goal:** All primitive components available in design system. No page rebuild yet.

**Duration estimate:** 3–5 days

### Tasks

Add shadcn/ui components one at a time. For each, verify it matches the design language from `02-design-language.md`:

**Batch A — Form primitives:**
- Input (dark background, focus ring, error state)
- Toggle / Switch (44px touch target, loading state variant)
- Select (dropdown with Radix popover)
- Textarea

**Batch B — Feedback:**
- Badge / StatusBadge (status color variants from domain mapping)
- Tooltip (dark, concise, no rounded pill)
- Alert (OfflineBanner base)

**Batch C — Overlay:**
- Dialog (focus trap, escape closes, dark backdrop)
- Sheet (side panel, used for mobile nav + NotificationDrawer)

**Batch D — Layout:**
- Card (surface Level 1, inner highlight border)
- Separator (subtle divider)
- Skeleton (shimmer loading states)

**Batch E — Navigation:**
- SideNav component (custom — not in shadcn. Built from scratch with Radix-compatible approach)
- TopBar component (custom)
- Breadcrumb component (custom — Radix doesn't provide this)

**Custom components built this phase:**
- `StatusBadge` — with all state variants from domain mapping
- `IdDisplay` — truncated monospace ID with copy button
- `RelativeTime` — timestamp with tooltip showing absolute value
- `EmptyState` — standard empty state template

**Deliverables:**
- Complete `src/components/ui/` directory.
- All shadcn/ui components rendered with correct dark theme tokens.
- Custom primitives built and tested.
- Visual consistency: all components use token values, no arbitrary values.

**Risks:**
- Time underestimation on custom components (SideNav is complex). Mitigation: implement SideNav as a simple vertical list first, refine rail/expand behavior in Phase 2.
- Font loading issues (Inter variable + JetBrains Mono). Mitigation: use fontsource npm packages for self-hosting with FOUC prevention.

**Dependencies:** Phase 0 complete.

---

## Phase 2: Navigation & Shell

**Goal:** New application shell (SideNav, TopBar, routing) live in production.

**Duration estimate:** 2–3 days

### Tasks

1. Build `AppShell` V2:
   - Fixed SideNav (rail mode, expandable on hover/click on desktop).
   - TopBar with breadcrumb, notification bell.
   - Mobile: bottom tab bar.
   - Route transitions: `React.Suspense` + fade animation.

2. Build `NotificationDrawer` V2 using Sheet component.

3. Build `OfflineBanner` V2 with retry countdown.

4. Replace V1 `AppShell` with V2. All V1 page content renders inside V2 shell.
   - V1 page components still use MUI internally — this is expected.
   - Shell V2 wraps V1 pages. Result: new nav, old content.

5. Wire TanStack Query to global offline detection:
   - `onError` callback on global query client increments failure counter.
   - After 3 failures: set `isOffline = true`.
   - `OfflineBanner` reads `isOffline`.

6. Keyboard navigation: Tab works through SideNav, TopBar actions.

**Deliverables:**
- New shell rendering all existing pages.
- Notification drawer working.
- Offline detection working.
- Mobile bottom navigation working.
- Breadcrumb on all pages.

**Risks:**
- MUI CSS specificity leaking into new shell styles. Mitigation: wrap all V1 pages in a `<div className="v1-legacy">` container and use CSS containment.
- Mobile bottom nav conflicts with existing MUI Drawer. Mitigation: remove MUI Drawer from AppShell as part of this phase.

**Dependencies:** Phase 1 complete.

---

## Phase 3: Dashboard & Library

**Goal:** Dashboard and Library pages rebuilt in V2.

**Duration estimate:** 4–6 days

### Tasks

**Dashboard:**
1. `HealthRow` component — answers "Is everything ok?" (replaces stats cards as the primary attention item when errors exist).
2. `SummaryCard` components — 3 stats (games, devices, errors).
3. `GameActivityList` — replaces horizontal scroll row with a vertical list.
4. `DeviceStatusPanel` — compact device list with online indicators.
5. `ActivityFeed` — compact event list (last 10 events).
6. Wire TanStack Query: `useQuery('dashboard', fetchDashboard, { refetchInterval: 15_000 })`.

**Library:**
1. `GameList` — sortable, filterable table of games.
2. Filter/sort controls.
3. `GameCard` V2 (for mobile grid layout).

**Game Detail (Overview tab only):**
1. Page header (icon, name, status, inline edit).
2. `ConflictBanner`.
3. `DeviceSyncMatrix`.
4. Recent activity (5 events, compact).

**Deliverables:**
- Dashboard rendering with V2 design.
- Library page rendering with V2 design.
- Game Detail overview tab rendering with V2 design.
- Dashboard load time <500ms to interactive.

**Risks:**
- Game icon loading from RomM: handle missing icons gracefully (fallback to hardware icon). This must be done correctly in V2 since V1 handles it poorly.
- Dashboard polling with TanStack Query may behave differently than V1's custom hook. Test: error counting, offline detection, stale data display.

**Dependencies:** Phase 2 complete.

---

## Phase 4: Conflict Workspace

**Goal:** Conflict resolution rebuilt with proper UX.

**Duration estimate:** 3–4 days

### Tasks

1. `ConflictWorkspace` modal — side-by-side snapshot cards.
2. Snapshot cards showing: device name, sequence number, timestamp, size.
3. Selection interaction (click card, accent border, checkmark).
4. Divergence point information ("Both descend from Snapshot #38").
5. Confirm step: show what will happen to the losing snapshot.
6. POST to `/api/v1/ui/snapshots/{txn}/push`.
7. Optimistic update: game status → SYNCED, conflict banner disappears.
8. Error handling: if push fails, revert optimistic update, show error message.

**Deliverables:**
- ConflictWorkspace resolves conflicts correctly.
- User-language throughout (no enum names exposed).
- Accessible modal (focus trap, Escape cancels, keyboard-selectable cards).

**Risks:**
- API: does the current `/snapshots/{txn}/push` endpoint return sufficient data for the side-by-side comparison? May need to fetch both conflict snapshots separately. Verify against `ui_api.py`.
- Confirmation step adds a second modal/step. Ensure focus management is correct for multi-step dialog.

**Dependencies:** Phase 3 complete.

---

## Phase 5: Visualization Layer

**Goal:** Snapshot lineage graph (History tab) live.

**Duration estimate:** 5–8 days (highest effort phase)

### Tasks

1. Install `@xyflow/react` + `elkjs` (lazy import only).
2. `useLineageLayout` hook:
   - Input: `Snapshot[]` array from `/api/v1/ui/games/{title_id}`.
   - Output: React Flow nodes and edges arrays.
   - Calls ELK layout algorithm asynchronously.
3. `LineageGraph` component (lazy-loaded):
   - Custom `SnapshotNode` renders `SnapshotNode` component.
   - Custom edge styles (canonical chain vs. conflict branch).
   - MiniMap for graphs with >20 nodes.
   - `SnapshotDetailPanel` slide-in on node click.
4. `SnapshotDetailPanel`:
   - All snapshot fields (see `04-component-library.md`).
   - Actions: push to all devices, push to specific device, delete.
5. History tab integration:
   - `React.lazy` import of `LineageGraph`.
   - Suspense fallback: skeleton list.
6. Mobile fallback: when viewport < `--bp-md`, show linear snapshot list instead of graph.
7. Accessibility: summary table below graph (screen reader).

**Deliverables:**
- Lineage graph rendering correctly for games with 1–50 snapshots.
- Conflict branches visible and labeled.
- Node actions working (push, delete).
- Mobile fallback working.
- Performance: graph renders in <300ms for 50 nodes.

**Risks:**
- ELK layout algorithm is async — initial render may show nodes in wrong position before layout completes. Mitigation: show skeleton until first layout resolves.
- Large lineage graphs (100+ snapshots) may have performance issues. Mitigation: limit display to last 100 snapshots with "show older" pagination.
- React Flow bundle size (~230KB) must be lazy-loaded to avoid impacting dashboard TTI.

**Dependencies:** Phase 3 complete (Game Detail page structure must exist before History tab is added).

---

## Phase 6: Remaining Pages + MUI Removal

**Goal:** All pages migrated. MUI removed from bundle.

**Duration estimate:** 3–5 days

### Tasks

**Devices (full rebuild):**
1. `DeviceList` V2.
2. `DeviceDetailPage` V2 (rename, sync prefs, revoke).
3. `RevokeDeviceModal` V2 (ConfirmDialog variant).

**Activity:**
1. `EventTimeline` with time-period grouping.
2. Filter controls (type, device, game).
3. Load more pagination (replaces hard 200-event limit).

**Settings:**
1. Auth section (token rotation, bootstrap).
2. Integrations section (RomM mapping).
3. Visual separation between sections.

**Auth:**
1. `AuthPage` V2 (bootstrap flow with clear multi-step UX).
2. Token display with copy button and storage guidance.

**MUI removal:**
1. Verify no V1 components remain in any active route.
2. Remove `@mui/material`, `@emotion/react`, `@emotion/styled` from `package.json`.
3. Remove V1 `theme.ts` and V1 import chains.
4. Run `npm run build` — bundle should decrease by ~330KB.
5. Run type check. Run visual regression (manual).

**Deliverables:**
- All pages on V2 design.
- MUI removed from bundle.
- Full V2 system live.

**Dependencies:** Phases 1–5 complete.

---

## Mobile Optimization (Ongoing, not a separate phase)

Mobile optimizations are applied per-page as each phase completes:
- Each page layout validated at 375px, 768px, 1280px viewport widths.
- Bottom tab bar already installed in Phase 2.
- Conflict workspace: stacked on mobile in Phase 4.
- Lineage graph: linear list fallback in Phase 5.

No dedicated mobile phase — mobile is a quality gate for each phase, not a separate workstream.

---

## Phase Summary

| Phase | Description | Effort | User Impact |
|-------|-------------|--------|-------------|
| 0 | Foundations | 1–2d | None |
| 1 | Design System | 3–5d | None |
| 2 | Navigation & Shell | 2–3d | New nav shell |
| 3 | Dashboard & Library | 4–6d | Rebuilt dashboard, library |
| 4 | Conflict Workspace | 3–4d | Rebuilt conflict resolution |
| 5 | Visualization Layer | 5–8d | Lineage graph |
| 6 | Remaining Pages + MUI removal | 3–5d | All pages V2, faster bundle |
| **Total** | | **21–33 days** | |

Estimates assume one focused developer. Actual timeline depends on familiarity with Tailwind v4 + shadcn/ui.
