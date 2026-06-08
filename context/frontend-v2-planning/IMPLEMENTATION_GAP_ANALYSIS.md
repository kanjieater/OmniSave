# Frontend V2 — Implementation Gap Analysis

**Audit date:** 2026-05-30
**Spec source:** `FRONTEND_V2_MASTER_SPEC.md` + supporting docs `03–12`
**Codebase audited:** `server/ui/src/`

---

## Methodology

Every spec requirement cross-referenced against the current source tree. Evidence is `file:line` where relevant. Severity scale:

- **Critical** — Missing or broken; blocks user workflow or represents a fundamental spec violation.
- **Major** — Significant missing feature or design-consistency divergence that visibly affects the product.
- **Minor** — Polish gap, component incompleteness, or non-blocking spec deviation.

---

## Summary Scorecard

| Phase | Description | Status |
|-------|-------------|--------|
| 0 — Foundations | Token system, Tailwind v4, TanStack Query | Mostly complete. Token naming deviations. |
| 1 — Design System | Primitive components | Partially complete. Several missing or incomplete. |
| 2 — Shell | AppShell, SideNav, TopBar, OfflineBanner | Mostly complete. Several behavioral gaps. |
| 3 — Dashboard & Library | Rebuilt dashboard, library, game overview | Partially complete. Dashboard layout deviates from spec. |
| 4 — Conflict Workspace | Conflict resolution UX | Partially complete. Missing confirmation step and error handling. |
| 5 — Visualization Layer | Lineage graph (React Flow + ELK) | **Not started.** |
| 6 — Remaining Pages + MUI Removal | Devices, Activity, Settings, Auth; MUI removed | Pages rebuilt. MUI **not removed from bundle.** |

---

## Phase 0 — Foundations

### P0-1: Tailwind v4 + @tailwindcss/vite configured
| | |
|---|---|
| **Status** | Complete |
| **Evidence** | [vite.config.ts](../../server/ui/vite.config.ts): `plugins: [react(), tailwindcss()]` |
| **Missing** | — |
| **Severity** | — |

---

### P0-2: Token system `src/styles/tokens.css`
| | |
|---|---|
| **Status** | Partially complete — token file exists but naming deviates from spec |
| **Evidence** | [styles/tokens.css](../../server/ui/src/styles/tokens.css) |
| **Missing work** | (a) Spacing: spec names `--space-1` through `--space-24`; implementation uses `--spacing-1` through `--spacing-20` (Tailwind v4 convention, but violates spec naming; also missing `--space-0` reset and `--space-24` value). (b) Motion: spec names `--motion-duration-instant/fast/normal/slow/slower` and `--motion-ease-*`; implementation uses `--animate-duration-*` and `--animate-ease-*` (missing `--motion-duration-instant: 0ms`). (c) Missing shadow tokens: `--shadow-inner-highlight` (inset highlight) and `--shadow-focus` (focus ring) not defined. (d) Missing border shorthand tokens: `--border-subtle`, `--border-base`, `--border-strong`, `--border-focus`, `--border-error`, `--border-none`. (e) Missing `--z-base: 0` (lowest z-index layer). (f) Missing `--icon-2xl: 32px` icon size. (g) Missing breakpoint tokens `--bp-sm/md/lg/xl/2xl`. (h) Missing letter-spacing tokens `--tracking-tight/normal/wide/widest`. |
| **Severity** | Major |

---

### P0-3: `globals.css` base styles
| | |
|---|---|
| **Status** | Complete |
| **Evidence** | [styles/globals.css](../../server/ui/src/styles/globals.css): body background, font, focus ring, sr-only, surface-highlight, surface-noise |
| **Missing** | — |
| **Severity** | — |

---

### P0-4: `cn()` utility helper
| | |
|---|---|
| **Status** | Complete |
| **Evidence** | [lib/utils.ts](../../server/ui/src/lib/utils.ts) |
| **Missing** | — |
| **Severity** | — |

---

### P0-5: TanStack Query `queryClient` wired
| | |
|---|---|
| **Status** | Complete |
| **Evidence** | [lib/queryClient.ts](../../server/ui/src/lib/queryClient.ts): `retry: 3`, `staleTime: 15_000`; provider in [main.tsx](../../server/ui/src/main.tsx):9 |
| **Missing** | — |
| **Severity** | — |

---

### P0-6: React 19 + Vite 6
| | |
|---|---|
| **Status** | Not upgraded |
| **Evidence** | [package.json](../../server/ui/package.json):30 — `"react": "^18.3.1"`, line 37 — `"vite": "^5.4.10"` |
| **Missing** | Upgrade React to 19 and Vite to 6 |
| **Severity** | Minor |

---

## Phase 1 — Design System

### P1-1: shadcn/ui primitive components (Button, Input, Dialog, Sheet, Switch, Tooltip, Separator, Skeleton)
| | |
|---|---|
| **Status** | Complete |
| **Evidence** | `components/ui/button.tsx`, `input.tsx`, `dialog.tsx`, `sheet.tsx`, `switch.tsx`, `tooltip.tsx`, `separator.tsx`, `skeleton.tsx` |
| **Missing** | — |
| **Severity** | — |

---

### P1-2: Select and Textarea primitives
| | |
|---|---|
| **Status** | Not present in `components/ui/` |
| **Evidence** | `@radix-ui/react-select` is in [package.json](../../server/ui/package.json):13 but no `select.tsx` exists in `components/ui/`. No `textarea.tsx`. |
| **Missing** | `components/ui/select.tsx`, `components/ui/textarea.tsx` |
| **Severity** | Minor |

---

### P1-3: `DataTable` reusable component
| | |
|---|---|
| **Status** | Not implemented |
| **Evidence** | `@tanstack/react-table` installed (package.json:16) but no `DataTable` component exists. Each page (DevicesPage, LibraryPage, EventsPage, GamePage) implements its own inline table. |
| **Missing** | `components/ui/data-table.tsx` with variants (default/compact/comfortable), sortable headers, sticky header, skeleton rows, empty state, row hover actions, `@tanstack/react-virtual` for >100 rows |
| **Severity** | Major |

---

### P1-4: `StatusBadge`
| | |
|---|---|
| **Status** | Complete |
| **Evidence** | [components/ui/status-badge.tsx](../../server/ui/src/components/ui/status-badge.tsx): all game and sync state variants, dot+label, size variants |
| **Missing** | `lg` size variant not implemented (only `sm` and `md`) |
| **Severity** | Minor |

---

### P1-5: `IdDisplay`
| | |
|---|---|
| **Status** | Complete |
| **Evidence** | [components/ui/id-display.tsx](../../server/ui/src/components/ui/id-display.tsx): truncated monospace, copy button, tooltip with full ID |
| **Missing** | — |
| **Severity** | — |

---

### P1-6: `RelativeTime`
| | |
|---|---|
| **Status** | Complete |
| **Evidence** | [components/ui/relative-time.tsx](../../server/ui/src/components/ui/relative-time.tsx) |
| **Missing** | — |
| **Severity** | — |

---

### P1-7: `EmptyState`
| | |
|---|---|
| **Status** | Complete |
| **Evidence** | [components/ui/empty-state.tsx](../../server/ui/src/components/ui/empty-state.tsx) |
| **Missing** | — |
| **Severity** | — |

---

### P1-8: `SideNav` — expand behavior
| | |
|---|---|
| **Status** | Partially complete — rail renders correctly; expand behavior missing |
| **Evidence** | [components/layout/SideNav.tsx](../../server/ui/src/components/layout/SideNav.tsx): icon-only rail (56px). No hover/click expand to 220px with icon+label. |
| **Missing** | Expanded state (220px, icon + label visible) triggered by hover on desktop or explicit click. Spec: "collapsed rail (icon only, 56px)" ↔ "expanded: icon + label (220px)". |
| **Severity** | Major |

---

### P1-9: `TopBar`
| | |
|---|---|
| **Status** | Complete |
| **Evidence** | [components/layout/TopBar.tsx](../../server/ui/src/components/layout/TopBar.tsx): role="banner", breadcrumb slot, bell icon with error badge, hamburger for mobile |
| **Missing** | — |
| **Severity** | — |

---

### P1-10: `Breadcrumb`
| | |
|---|---|
| **Status** | Partially complete — structure correct; content incomplete |
| **Evidence** | [components/layout/Breadcrumb.tsx](../../server/ui/src/components/layout/Breadcrumb.tsx): nav + ol, aria-label, aria-current, ChevronRight separator |
| **Missing** | (a) Game segment shows raw `title_id.slice(0,12)` instead of resolved display name. (b) Device segment shows raw `device_id.slice(0,8)` instead of resolved device name. (c) Mobile truncation to last 2 segments with `…` prefix not implemented. |
| **Severity** | Major |

---

### P1-11: `SummaryCard`
| | |
|---|---|
| **Status** | Component implemented; not used on Dashboard |
| **Evidence** | [components/ui/summary-card.tsx](../../server/ui/src/components/ui/summary-card.tsx): complete with variants (default/alert/info), role="status", aria-live |
| **Missing** | Dashboard does not render the 3-card summary row (games, devices, errors). Component exists but is dead code in the current dashboard layout. |
| **Severity** | Major (see Dashboard section) |

---

### P1-12: `HardwareIcon` — OLED/Lite badge variants
| | |
|---|---|
| **Status** | Partially complete |
| **Evidence** | [components/ui/hardware-icon.tsx](../../server/ui/src/components/ui/hardware-icon.tsx): resolves Switch/PC correctly but no "OLED" or "Lite" badge overlay |
| **Missing** | Spec: "Switch OLED: Gamepad2 + 'OLED' badge", "Switch Lite: Gamepad2 + 'Lite' badge" |
| **Severity** | Minor |

---

### P1-13: Banned arbitrary values in component code
| | |
|---|---|
| **Status** | Multiple violations present |
| **Evidence** | `mt-[3px]` (EventsPage.tsx:53), `mt-[2px]` (EventsPage.tsx:56, GamePage, NotificationDrawerV2), `px-[3px]` (SideNav:79, TopBar:62, BottomNav:46), `px-[6px]` (status-badge.tsx:66), `py-[1px]` (status-badge.tsx:66), `py-[2px]` (status-badge.tsx:66, GamePage), `gap-[2px]` (BottomNav:37), `w-[2px]` (SideNav:71 — 2px accent bar), `text-[10px]` (SideNav:79, TopBar:62, BottomNav:46, status-badge.tsx:66), `min-h-[56px]` (BottomNav:37), `h-5 rounded-r-full` unnamed magic (SideNav:71) |
| **Missing** | All pixel values must be extracted to tokens. Specific tokens needed: `--space-px` or `--spacing-px` for 2px/3px nudges, and icon badge typography size for 10px text. |
| **Severity** | Major |

---

## Phase 2 — Navigation & Shell

### P2-1: `AppShellV2`
| | |
|---|---|
| **Status** | Complete |
| **Evidence** | [components/layout/AppShellV2.tsx](../../server/ui/src/components/layout/AppShellV2.tsx): desktop rail, mobile overlay, TopBar, OfflineBanner, BottomNav, NotificationDrawer |
| **Missing** | — |
| **Severity** | — |

---

### P2-2: `NotificationDrawerV2` — "Dismiss all" consequence explanation
| | |
|---|---|
| **Status** | Violates banned pattern |
| **Evidence** | [components/layout/NotificationDrawerV2.tsx](../../server/ui/src/components/layout/NotificationDrawerV2.tsx):46 — "Dismiss all" button with no explanation of what dismissal means for underlying errors |
| **Missing** | Spec explicitly bans: `❌ "Dismiss all" without explaining what it means for the underlying issue`. Button label or helper text must clarify that errors are acknowledged (not fixed) and will re-appear if syncs fail again. |
| **Severity** | Major |

---

### P2-3: `OfflineBanner` — retry countdown
| | |
|---|---|
| **Status** | Partially complete — banner renders; countdown not wired |
| **Evidence** | [components/ui/offline-banner.tsx](../../server/ui/src/components/ui/offline-banner.tsx):17 accepts `retryIn` prop but AppShellV2.tsx:57 passes no `retryIn` value |
| **Missing** | Countdown timer in AppShell that decrements and passes `retryIn` to OfflineBanner |
| **Severity** | Major |

---

### P2-4: Offline detection wired to TanStack Query `onError`
| | |
|---|---|
| **Status** | Partially complete — detection works but not via specified mechanism |
| **Evidence** | [contexts/OfflineContext.tsx](../../server/ui/src/contexts/OfflineContext.tsx): uses independent `failureCount` state. Spec (Phase 2 task 5): "`onError` callback on global query client increments failure counter" |
| **Missing** | Wire TanStack Query global `onError` to `recordFailure()`. Current approach may miss failures that don't reach the context's `recordFailure` path. |
| **Severity** | Major |

---

### P2-5: Mobile bottom navigation
| | |
|---|---|
| **Status** | Complete |
| **Evidence** | [components/layout/BottomNav.tsx](../../server/ui/src/components/layout/BottomNav.tsx): 5 items, icons, labels, error badge, safe-area inset |
| **Missing** | — |
| **Severity** | — |

---

### P2-6: Skip-to-content link (accessibility)
| | |
|---|---|
| **Status** | Not implemented |
| **Evidence** | AppShellV2.tsx — no skip link present |
| **Missing** | Hidden skip link as first focusable element: `<a href="#main-content" className="sr-only focus:not-sr-only ...">Skip to content</a>`. Required by WCAG 2.1 AA (Success Criterion 2.4.1). |
| **Severity** | Major |

---

### P2-7: Route transitions (React.Suspense + fade)
| | |
|---|---|
| **Status** | Not implemented |
| **Evidence** | App.tsx — no Suspense wrapper around Routes; no fade animation |
| **Missing** | Wrap `<Routes>` in `<React.Suspense>` with fade-in animation |
| **Severity** | Minor |

---

## Phase 3 — Dashboard & Library

### P3-1: `HealthRow` — dashboard primary status
| | |
|---|---|
| **Status** | Complete |
| **Evidence** | [components/dashboard/Dashboard.tsx](../../server/ui/src/components/dashboard/Dashboard.tsx):14 — first rendered element, role="status", healthy/error states, correct color tokens |
| **Missing** | — |
| **Severity** | — |

---

### P3-2: `SummaryCard` row (3 stats: games, devices, errors)
| | |
|---|---|
| **Status** | Not implemented on Dashboard |
| **Evidence** | Dashboard.tsx renders no SummaryCard row. Spec wireframe (10-wireframe-spec.md) shows 3 cards directly below HealthRow. |
| **Missing** | Row of 3 `SummaryCard` components: "Games" (Gamepad2 icon), "Devices" (Monitor icon), "Active Errors" (XCircle icon, `alert` variant when > 0) |
| **Severity** | Major |

---

### P3-3: `GameActivityList` — vertical list (replaces horizontal scroll)
| | |
|---|---|
| **Status** | Wrong layout — grid instead of vertical list |
| **Evidence** | Dashboard.tsx:104 — `grid-cols-3 sm:grid-cols-4 md:grid-cols-5 lg:grid-cols-6` icon grid |
| **Missing** | Spec mandates "GameActivityList — replaces horizontal scroll row with a vertical list" showing: `[icon] Game Title  ● SYNCED · Snap #42 · 2h ago`. Current grid layout is the V1 anti-pattern (horizontal icon row) reframed as a grid — still fails the "vertical list" requirement. |
| **Severity** | Major |

---

### P3-4: Device status panel (dashboard)
| | |
|---|---|
| **Status** | Complete |
| **Evidence** | Dashboard.tsx:148 — DeviceStatusIndicator, pending count, link to device detail |
| **Missing** | — |
| **Severity** | — |

---

### P3-5: Activity feed (dashboard, last 10 events)
| | |
|---|---|
| **Status** | Complete |
| **Evidence** | Dashboard.tsx:196 — event dot, label, summary, RelativeTime |
| **Missing** | — |
| **Severity** | — |

---

### P3-6: Library — `GameList` with search
| | |
|---|---|
| **Status** | Complete |
| **Evidence** | [components/library/LibraryPage.tsx](../../server/ui/src/components/library/LibraryPage.tsx): search input, filtered/sorted list, conflict priority sort, EmptyState |
| **Missing** | — |
| **Severity** | — |

---

### P3-7: Library — sort controls
| | |
|---|---|
| **Status** | Not implemented |
| **Evidence** | LibraryPage.tsx — auto-sorts by conflict/error/activity but no user-facing sort controls |
| **Missing** | Spec: "sortable, filterable table of games" with explicit sort controls. User should be able to choose sort column (name, last activity, status). |
| **Severity** | Minor |

---

### P3-8: Library nav badge — conflict count
| | |
|---|---|
| **Status** | Not implemented |
| **Evidence** | SideNav.tsx:28 — Library item has no badge. Spec: "Library [Badge: 1 conflict]" in navigation. |
| **Missing** | Library nav item should show conflict count badge (amber, not error red). Requires `conflictCount` prop to be computed and passed to SideNav. |
| **Severity** | Minor |

---

### P3-9: `GamePage` overview tab — DeviceSyncMatrix, conflict banner, recent activity
| | |
|---|---|
| **Status** | Complete |
| **Evidence** | [components/game/GamePage.tsx](../../server/ui/src/components/game/GamePage.tsx):32, 228, 268 |
| **Missing** | — |
| **Severity** | — |

---

### P3-10: `ConflictBanner` as standalone reusable component
| | |
|---|---|
| **Status** | Not a standalone component |
| **Evidence** | GamePage.tsx:228 — conflict banner is inlined as a `<div>` block |
| **Missing** | Extract to `components/game/ConflictBanner.tsx`. Spec defines it as a named component used in the "Component Inventory" section. |
| **Severity** | Minor |

---

### P3-11: `ConflictBadge` — dot/chip variants
| | |
|---|---|
| **Status** | Not implemented |
| **Evidence** | No `ConflictBadge` component exists |
| **Missing** | `dot` variant for nav badge counts; `chip` variant for game cards (labeled "CONFLICT"). Used in SideNav Library badge and GameCard. |
| **Severity** | Minor |

---

## Phase 4 — Conflict Workspace

### P4-1: `ConflictWorkspace` modal — side-by-side cards
| | |
|---|---|
| **Status** | Complete |
| **Evidence** | [components/game/ConflictWorkspace.tsx](../../server/ui/src/components/game/ConflictWorkspace.tsx):119 — `grid-cols-1 sm:grid-cols-2`, SnapshotCard with selection state, aria-pressed |
| **Missing** | — |
| **Severity** | — |

---

### P4-2: Snapshot card — device name, sequence, timestamp
| | |
|---|---|
| **Status** | Complete |
| **Evidence** | ConflictWorkspace.tsx:54 — device label, sequence (`#${snap.sequence_num}`), RelativeTime |
| **Missing** | — |
| **Severity** | — |

---

### P4-3: Snapshot card — size display
| | |
|---|---|
| **Status** | Not implemented |
| **Evidence** | ConflictWorkspace.tsx — SnapshotCard has no size field |
| **Missing** | Spec wireframe shows "12.4 MB" on each card. Requires `file_size_bytes` field from API response; display as human-readable size. |
| **Severity** | Minor |

---

### P4-4: Divergence point "Both descend from Snapshot #X"
| | |
|---|---|
| **Status** | Partially complete |
| **Evidence** | ConflictWorkspace.tsx:113 — shows `Two saves diverged from Save #${divergedAt}` |
| **Missing** | Spec: "Diverged from snapshot #38 · 2026-05-28 14:32" — missing absolute timestamp of divergence point. |
| **Severity** | Minor |

---

### P4-5: Two-step confirmation flow
| | |
|---|---|
| **Status** | Not implemented — single-step only |
| **Evidence** | ConflictWorkspace.tsx:101–158 — "Confirm Restore" immediately triggers mutation |
| **Missing** | Spec Phase 4 task 5: "Confirm step: show what will happen to the losing snapshot." This should be a distinct second step (or clearly labeled confirm dialog) before mutation fires. Current UX has a warning note but no true confirm step. |
| **Severity** | Major |

---

### P4-6: Optimistic update (game status → SYNCED, conflict banner disappears)
| | |
|---|---|
| **Status** | Not implemented |
| **Evidence** | ConflictWorkspace.tsx:90 — `onSuccess: () => void qc.invalidateQueries(...)` (server refetch, not optimistic) |
| **Missing** | Spec: "Optimistic update: game status → SYNCED, conflict banner disappears." Status should clear immediately on confirm click; revert if mutation fails. |
| **Severity** | Minor |

---

### P4-7: Error handling — revert on failed push
| | |
|---|---|
| **Status** | Not implemented |
| **Evidence** | ConflictWorkspace.tsx — mutation has no `onError` handler |
| **Missing** | If `pushSnapshot` fails: show error message in modal, keep modal open, leave conflict state unchanged. |
| **Severity** | Major |

---

## Phase 5 — Visualization Layer

**Phase 5 is entirely unimplemented.** The History tab currently renders a flat table of snapshots (`SnapshotRow`) rather than a lineage graph.

### P5-1: `@xyflow/react` + `elkjs` installed (lazy)
| | |
|---|---|
| **Status** | Not installed |
| **Evidence** | package.json — no `@xyflow/react` or `elkjs` entry |
| **Missing** | Install both packages; ensure @xyflow/react is lazy-imported only |
| **Severity** | Critical |

---

### P5-2: `useLineageLayout` hook
| | |
|---|---|
| **Status** | Not implemented |
| **Evidence** | No such hook in source tree |
| **Missing** | `hooks/useLineageLayout.ts` — takes `Snapshot[]`, calls ELK async layout, returns React Flow nodes + edges arrays |
| **Severity** | Critical |

---

### P5-3: `LineageGraph` component (lazy-loaded)
| | |
|---|---|
| **Status** | Not implemented |
| **Evidence** | No `LineageGraph` component exists |
| **Missing** | `components/game/LineageGraph.tsx` — React Flow canvas, custom SnapshotNode, edge styles (canonical vs conflict branch), MiniMap (>20 nodes), loaded via `React.lazy` |
| **Severity** | Critical |

---

### P5-4: `SnapshotNode` — custom React Flow node
| | |
|---|---|
| **Status** | Not implemented |
| **Evidence** | No `SnapshotNode` component exists |
| **Missing** | Variants: head, canonical, conflict-branch (amber), failed (red), superseded (grey/muted). Hover actions: push, delete, copy SHA256. |
| **Severity** | Critical |

---

### P5-5: `SnapshotDetailPanel` — slide-in on node click
| | |
|---|---|
| **Status** | Not implemented |
| **Evidence** | No `SnapshotDetailPanel` component exists |
| **Missing** | Sheet/drawer showing all snapshot fields; actions: push to all devices, push to specific device, delete |
| **Severity** | Critical |

---

### P5-6: History tab — LineageGraph with `React.lazy` + Suspense fallback
| | |
|---|---|
| **Status** | Not implemented — flat table used instead |
| **Evidence** | [components/game/GamePage.tsx](../../server/ui/src/components/game/GamePage.tsx):124 — `HistoryTab` renders a `<table>` with `SnapshotRow` rows |
| **Missing** | Replace `HistoryTab` with `React.lazy(() => import('./LineageGraph'))` wrapped in `<Suspense fallback={<SkeletonList />}>` |
| **Severity** | Critical |

---

### P5-7: Mobile fallback (linear list when `< --bp-md`)
| | |
|---|---|
| **Status** | Accidentally present (flat table is the only mode) |
| **Evidence** | GamePage.tsx:124 — current flat table happens to work as a mobile list, but it is not a fallback from a graph; it is the entire implementation |
| **Missing** | Once LineageGraph is implemented: conditionally render flat list on `< --bp-md` viewports |
| **Severity** | Minor (will apply once Phase 5 is started) |

---

### P5-8: Accessibility summary table below graph
| | |
|---|---|
| **Status** | Not implemented |
| **Evidence** | — |
| **Missing** | Spec: "Accessible alternative (summary table) provided for lineage graph." Hidden visually, readable by screen readers. |
| **Severity** | Major |

---

## Phase 6 — Remaining Pages + MUI Removal

### P6-1: Devices V2 (`DevicesPage`, `DeviceDetailPage`)
| | |
|---|---|
| **Status** | Complete |
| **Evidence** | [components/devices/DevicesPage.tsx](../../server/ui/src/components/devices/DevicesPage.tsx), [DeviceDetailPage.tsx](../../server/ui/src/components/devices/DeviceDetailPage.tsx) — full V2 implementation with tokens, InlineEdit, Switch, ConfirmDialog |
| **Missing** | — |
| **Severity** | — |

---

### P6-2: Activity page V2 (`EventsPage`) — time-grouped timeline
| | |
|---|---|
| **Status** | Complete |
| **Evidence** | [components/events/EventsPage.tsx](../../server/ui/src/components/events/EventsPage.tsx): grouped by Today/Yesterday/days-ago, EventRow with dot+icon+summary, RelativeTime |
| **Missing** | — |
| **Severity** | — |

---

### P6-3: Activity filter controls (type, device, game)
| | |
|---|---|
| **Status** | Not implemented |
| **Evidence** | EventsPage.tsx — no filter controls |
| **Missing** | Spec: "Filter controls (type, device, game)" on Activity page |
| **Severity** | Major |

---

### P6-4: Activity "load more" pagination
| | |
|---|---|
| **Status** | Not implemented |
| **Evidence** | EventsPage.tsx:84 — `api.events(200)` hard limit |
| **Missing** | Replace hard limit with infinite scroll or "Load more" button |
| **Severity** | Minor |

---

### P6-5: Settings page V2
| | |
|---|---|
| **Status** | Complete |
| **Evidence** | [components/settings/SettingsPage.tsx](../../server/ui/src/components/settings/SettingsPage.tsx): Auth section (token rotation, sign out), Switch User mapping, RomM integration |
| **Missing** | — |
| **Severity** | — |

---

### P6-6: Auth page V2
| | |
|---|---|
| **Status** | Complete |
| **Evidence** | [components/auth/AuthPage.tsx](../../server/ui/src/components/auth/AuthPage.tsx): bootstrap flow, token display with copy, login form, eye toggle |
| **Missing** | — |
| **Severity** | — |

---

### P6-7: MUI removed from `package.json`
| | |
|---|---|
| **Status** | **Not done — MUI still in bundle** |
| **Evidence** | package.json:3–5 — `"@mui/material": "^9.0.1"`, `"@emotion/react": "^11.14.0"`, `"@emotion/styled": "^11.14.1"`, `"@mui/icons-material": "^9.0.1"` |
| **Missing** | Remove all four MUI packages. Run `npm run build` to verify bundle. Expected bundle reduction: ~330 KB compressed. |
| **Severity** | Critical |

---

### P6-8: V1 `theme.ts` removed
| | |
|---|---|
| **Status** | Not removed |
| **Evidence** | [src/theme.ts](../../server/ui/src/theme.ts):1 — V1 MUI `createTheme()` definition still present |
| **Missing** | Delete `src/theme.ts` after MUI is removed |
| **Severity** | Major |

---

### P6-9: V1 ghost component files removed
| | |
|---|---|
| **Status** | Not removed — 9 V1 files remain in source tree |
| **Evidence** | Active routes use V2 components. But the following MUI-dependent V1 files still exist: `components/layout/AppShell.tsx`, `components/layout/NotificationDrawer.tsx`, `components/dashboard/RecentGamesRow.tsx`, `components/dashboard/LiveEventFeed.tsx`, `components/dashboard/DeviceStatusOverview.tsx`, `components/devices/RevokeDeviceModal.tsx`, `components/game/ConflictResolverModal.tsx`, `components/game/GameDeviceSyncStatus.tsx`, `components/game/SnapshotList.tsx` |
| **Missing** | Delete all 9 files; verify no route or import references them |
| **Severity** | Minor |

---

## Missing Domain Components

### DC-1: `ActivitySparkline`
| | |
|---|---|
| **Status** | Not implemented |
| **Evidence** | No `ActivitySparkline` component exists |
| **Missing** | Spec: "Mini bar chart showing sync activity over time (for dashboard). SVG, no external library. 120×32px." |
| **Severity** | Minor |

---

### DC-2: `SyncProgressBar`
| | |
|---|---|
| **Status** | Not implemented |
| **Evidence** | No `SyncProgressBar` component exists |
| **Missing** | Spec: "Shows upload/download progress during active transactions." Smooth animation via `--motion-duration-slow`. |
| **Severity** | Minor |

---

### DC-3: `TransactionTimeline`
| | |
|---|---|
| **Status** | Not implemented |
| **Evidence** | No `TransactionTimeline` component exists |
| **Missing** | Spec: "Horizontal or vertical step indicator for UPLOADING → PROCESSING → READY_FOR_RESTORE → COMPLETED state progression with timestamps at each step." |
| **Severity** | Minor |

---

### DC-4: `DeviceSyncMatrix` — user-language labels verified
| | |
|---|---|
| **Status** | Complete |
| **Evidence** | GamePage.tsx:19 — `SYNC_STATE_LABEL` maps `SYNCED→"In Sync"`, `OUT_OF_SYNC→"Needs Update"`, `DOWNLOADING→"Downloading…"`, `NO_DELIVERY→"Not Configured"` |
| **Missing** | — |
| **Severity** | — |

---

### DC-5: `DeviceStatusIndicator` — pulse behavior
| | |
|---|---|
| **Status** | Spec non-compliant animation |
| **Evidence** | [components/ui/device-status-indicator.tsx](../../server/ui/src/components/ui/device-status-indicator.tsx):25 — uses `animate-ping` which is a continuous Tailwind pulse |
| **Missing** | Spec: "Single radial pulse from center, 1-second duration, repeats every 4 seconds." Current implementation pulses continuously on every animation cycle, not once every 4 seconds. Requires custom CSS animation with a delay. |
| **Severity** | Minor |

---

## Accessibility Gaps

### A-1: Skip-to-content link
| | |
|---|---|
| **Status** | Missing (also listed as P2-6) |
| **Severity** | Major |

### A-2: DataTable keyboard navigation (arrow keys, sort)
| | |
|---|---|
| **Status** | Not applicable — no DataTable component exists |
| **Severity** | Major (blocked by DC missing DataTable) |

### A-3: Screen reader test (NVDA + VoiceOver)
| | |
|---|---|
| **Status** | Not performed |
| **Severity** | Minor |

### A-4: `prefers-reduced-motion` respected
| | |
|---|---|
| **Status** | Complete |
| **Evidence** | tokens.css:143 — `@media (prefers-reduced-motion: reduce)` collapses all `--animate-duration-*` to 0ms |
| **Severity** | — |

---

## Performance Gaps

### PERF-1: Initial JS bundle < 150 KB
| | |
|---|---|
| **Status** | Definitely failing — MUI not removed |
| **Evidence** | package.json — MUI still installed (~330 KB compressed contribution) |
| **Severity** | Critical |

### PERF-2: `@xyflow/react` lazy-loaded only
| | |
|---|---|
| **Status** | Not started — library not installed |
| **Severity** | Critical |

### PERF-3: `ConflictWorkspace` lazy-loaded
| | |
|---|---|
| **Status** | Not implemented |
| **Evidence** | GamePage.tsx:16 — `import { ConflictWorkspace } from './ConflictWorkspace'` is eager |
| **Missing** | `const ConflictWorkspace = React.lazy(() => import('./ConflictWorkspace'))` |
| **Severity** | Minor |

---

## Summary: Complete vs. Incomplete vs. Missing

### Complete (spec requirement fully met)
- Tailwind v4 + @tailwindcss/vite configured
- globals.css base styles (dark body, focus ring, sr-only, surface-highlight)
- cn() utility, queryClient.ts, main.tsx wiring
- Button, Input, Dialog, Sheet, Switch, Tooltip, Separator, Skeleton (shadcn/ui primitives)
- StatusBadge (sm/md variants), IdDisplay, RelativeTime, EmptyState
- AppShellV2 (shell structure, offline banner slot, mobile overlay)
- TopBar (role="banner", breadcrumb slot, bell with badge, hamburger)
- BottomNav (mobile 5-item nav)
- HealthRow (dashboard primary element)
- Dashboard devices panel, activity feed
- LibraryPage (search, conflict-priority sort, empty state)
- GamePage overview tab (DeviceSyncMatrix, inline conflict banner, recent 5 events)
- ConflictWorkspace modal (side-by-side cards, selection interaction, warning note)
- DevicesPage, DeviceDetailPage (rename, sync prefs, remove)
- EventsPage (time-grouped, correct event labels)
- SettingsPage (auth, Switch user mapping, RomM integration)
- AuthPage (bootstrap + login flows)
- SummaryCard component (exists, not used)
- prefers-reduced-motion respected

### Partially Implemented (spec requirement exists but has gaps)
- tokens.css (naming deviations, missing token groups)
- SideNav (rail renders, expand behavior missing)
- Breadcrumb (structure correct, raw IDs not resolved names)
- NotificationDrawerV2 (works, banned "Dismiss all" pattern)
- OfflineBanner (renders, countdown not wired)
- OfflineContext (detection works, not via TanStack Query onError)
- ConflictWorkspace (no size field, no 2-step confirm, no error handling)
- HardwareIcon (Switch/PC resolved, OLED/Lite badges missing)
- DeviceStatusIndicator (pulse exists, wrong cadence)

### Not Implemented (spec requirement exists, no implementation)
- Phase 5 entirely: @xyflow/react, elkjs, LineageGraph, SnapshotNode, SnapshotDetailPanel, useLineageLayout
- DataTable reusable component
- Select, Textarea shadcn/ui primitives
- SummaryCard row on Dashboard
- GameActivityList (vertical list) — dashboard shows grid
- Library sort controls
- Library conflict count badge in SideNav
- ConflictBanner as standalone component, ConflictBadge
- Activity filter controls (device, game, type)
- Skip-to-content accessibility link
- Route transitions (Suspense + fade)
- ActivitySparkline, SyncProgressBar, TransactionTimeline
- MUI removal from package.json (Critical — ~330 KB bundle still loaded)
- V1 theme.ts cleanup, V1 ghost component files cleanup
- Activity "load more" pagination
- React 19 + Vite 6 upgrade
