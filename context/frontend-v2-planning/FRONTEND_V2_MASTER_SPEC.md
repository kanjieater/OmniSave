# OmniSave Frontend V2 — Master Specification

This document synthesizes all planning documents into a single implementation blueprint. Read the individual documents for full detail. This document is the executive summary and decision record.

---

## What This Is

OmniSave is infrastructure software for game save synchronization across Nintendo Switch devices. The current UI (Material UI, V1) fails on every dimension: wrong aesthetic, poor information hierarchy, broken mobile experience, and unusable conflict resolution. V2 is a complete rebuild of the frontend layer with no changes to the backend API.

---

## The Core Design Decision

OmniSave should feel like **Tailscale or Proxmox** — not like a generic SaaS dashboard.

This means:
- Dark, material surfaces with texture depth
- Typography-driven hierarchy (font weight and size, not color and decoration)
- Data density over empty whitespace
- Technical precision in presentation (IDs, hashes, sequence numbers are formatted but visible)
- Calm, purposeful motion
- Operational clarity: "Is everything ok?" is answerable in under 2 seconds

The aesthetic reference set: Tailscale dashboard, Linear, Warp terminal, Proxmox, GitHub Actions, Obsidian.

---

## Technology Stack

| Layer | Choice | Rationale |
|-------|--------|-----------|
| Framework | React 19 + TypeScript (strict) | Existing investment, correct choice |
| Build | Vite 6 | Fast, modern, Tailwind v4 compatible |
| Component model | **shadcn/ui** (copy-and-own, Radix primitives) | Full design control, zero abstraction overhead, correct accessibility from Radix |
| Styling | **Tailwind CSS v4** | CSS-first config maps directly to token system |
| Icons | lucide-react | Tree-shakeable, consistent, MIT |
| Server state | **TanStack Query v5** | Replaces custom polling hooks with production-grade caching and retry |
| Routing | React Router v7 | No change from V1 |
| Tables | @tanstack/react-table | Headless — renders with our design system |
| Virtualization | @tanstack/react-virtual | For event lists and snapshot tables |
| Visualization | **@xyflow/react + elkjs** (lazy) | React-native node graph, ELK layout. Lazy-loaded, only on History tab |
| Animation | tailwindcss-animate (minimal) | Token-driven, respects prefers-reduced-motion |
| **Removed** | @mui/material, @emotion | Saves ~330KB compressed from initial bundle |

---

## Information Architecture

Five primary sections:

```
Dashboard    — "Is everything ok right now?"
Library      — "What saves do I have? What's the state of each game?"
Devices      — "What hardware is registered? What is it syncing?"
Activity     — "What has happened recently?"
Settings     — "Auth token, RomM mapping"
```

The hierarchy within every screen follows the spec-mandated order:
**State > Exceptions > Activity > Audit**

The dashboard Health Row is always the first visible element — it answers "Is everything ok?" with a single color and sentence before any other content loads.

---

## Design Tokens (Critical Values)

The complete token set is in `03-design-system.md`. The most critical values:

```css
/* Surfaces */
--color-bg-base:       #0C0D10    /* page background */
--color-bg-subtle:     #111318    /* primary surface */
--color-bg-elevated:   #191C23    /* raised elements */

/* Text */
--color-text-primary:  #E8EAF0
--color-text-secondary:#9198AC
--color-text-muted:    #585E72

/* Accent */
--color-accent:        #3B82F6

/* Status */
--color-success:       #22C55E    /* SYNCED/COMPLETED */
--color-warning:       #EAB308    /* CONFLICT */
--color-error:         #EF4444    /* FAILED/ERROR */
--color-neutral:       #6B7280    /* SUPERSEDED/NO_DATA */

/* Typography */
--font-sans:           'Inter', system-ui
--font-mono:           'JetBrains Mono', monospace  /* IDs, hashes, seq numbers */
```

**One rule enforced by design system:** No arbitrary values in component code. Every color, spacing, radius, shadow, and timing value references a token.

---

## Domain-to-UI Mapping (Key Decisions)

Full mapping in `06-domain-ui-mapping.md`. Critical translations:

| Internal concept | User-facing |
|-----------------|-------------|
| Snapshot (HEAD) | Current Save |
| SUPERSEDED | Archived |
| READY_FOR_RESTORE | Ready to download |
| has_conflict=1 | Conflict (retained word) |
| POST /push | "Restore to all devices" |
| DELETE /devices/:id | "Remove Device" |
| admin_token | Access Token |
| bootstrap | Setup |
| snapshot_sequence | #42 (monospace, prominent) |
| transaction_id | Hidden except in errors; truncated + copy |
| sha256 | Fingerprint (first 12 chars + copy) |

---

## Critical UX Fixes (V1 → V2)

These V1 failures drove the entire design:

| Problem | V2 Solution |
|---------|-------------|
| Horizontal scroll card row | Replaced with vertical list (GameActivityList) |
| "Is everything ok?" not answerable | Health Row: first element on dashboard |
| Conflict resolution modal is inadequate | ConflictWorkspace: side-by-side cards, explicit consequences |
| Lineage is a CSS-indented list | LineageGraph: React Flow DAG, ELK layout |
| Internal enum strings shown to users | Domain-UI mapping enforces user-goal language |
| Mobile is broken | Responsive breakpoints, bottom tab nav, mobile fallbacks |
| Raw IDs shown unformatted | IdDisplay component: truncated, monospace, copy button |
| No breadcrumb navigation | Breadcrumb on all detail pages |
| MUI aesthetics feel generic | shadcn + Tailwind v4 with purpose-built token system |

---

## Component Inventory

Full catalog in `04-component-library.md`. Key custom components:

**Infrastructure components (built once, used everywhere):**
- `StatusBadge` — all domain status states with icon + color + label
- `IdDisplay` — truncated monospace ID with copy
- `RelativeTime` — relative timestamp with absolute in tooltip
- `OfflineBanner` — non-dismissible error banner (3 poll failures)
- `EmptyState` — standard empty state template
- `DeviceStatusIndicator` — online/offline dot with tooltip

**Domain-specific components:**
- `HealthRow` — dashboard primary status (all good / errors present)
- `GameActivityList` — replaces horizontal scroll row
- `DeviceSyncMatrix` — per-device sync state table for a game
- `ConflictBanner` — persistent amber conflict alert
- `ConflictWorkspace` — side-by-side conflict resolution modal
- `LineageGraph` — React Flow DAG (lazy-loaded)
- `SnapshotNode` — custom React Flow node for lineage graph
- `SnapshotDetailPanel` — slide-in detail panel on snapshot node click
- `TransactionTimeline` — horizontal state step indicator

---

## Migration Phases

Full plan in `09-migration-roadmap.md`. Six phases with parallel build approach (no big-bang rewrite):

| Phase | What ships | Effort |
|-------|-----------|--------|
| 0 — Foundations | Token system, Tailwind v4, TanStack Query | 1–2d |
| 1 — Design System | All primitive components in `src/components/ui/` | 3–5d |
| 2 — Shell | New SideNav, TopBar, mobile nav (wraps V1 pages) | 2–3d |
| 3 — Dashboard + Library | Rebuilt dashboard, library, game overview | 4–6d |
| 4 — Conflict Workspace | Rebuilt conflict resolution with proper UX | 3–4d |
| 5 — Visualization | Lineage graph (React Flow + ELK), History tab | 5–8d |
| 6 — Remaining + MUI removal | Devices, Activity, Settings, Auth; MUI removed | 3–5d |
| **Total** | | **21–33d** |

---

## Performance Targets

Full budget in `11-performance-budget.md`. Gates, not aspirations:

| Metric | Target |
|--------|--------|
| Initial JS bundle | < 150 KB compressed |
| Dashboard LCP | < 1.5s (cold) / < 300ms (warm) |
| Route navigation | < 200ms to skeleton |
| Button click response | < 100ms visual feedback |
| Interaction TBT | < 100ms |
| Mobile Lighthouse score | > 85 |
| MUI removal savings | ~330 KB |

Visualization bundle (~280 KB) is lazy-loaded only on the History tab. It does not impact dashboard performance.

---

## Accessibility Targets

Full spec in `12-accessibility-spec.md`.

- WCAG 2.1 AA compliance required
- All text contrast ratios verified against dark token values
- Keyboard navigation: every action reachable without mouse
- Focus trapping in all modals (Radix handles this automatically)
- Status information never communicated by color alone
- Accessible alternative (summary table) provided for lineage graph
- `prefers-reduced-motion` respected via token duration collapse
- Screen reader tested on NVDA + VoiceOver

---

## What Not To Do

These patterns are explicitly banned:

- ❌ Arbitrary values in components (`bg-[#ff0000]`, `p-[13px]`)
- ❌ Status information by color alone
- ❌ Raw enum strings shown to users (UPLOADING, SUPERSEDED, READY_FOR_RESTORE)
- ❌ Heavy drop shadows at surface level
- ❌ Horizontal scroll card rows
- ❌ `<div onClick>` where `<button>` is correct
- ❌ placeholder as a substitute for label
- ❌ Loading @xyflow/react in the initial bundle
- ❌ MUI and Tailwind in the same component (during migration, wrap V1 pages to isolate CSS)
- ❌ Glassmorphism, excessive gradients, decorative animations
- ❌ "Dismiss all" without explaining what it means for the underlying issue

---

## File Index

```
context/frontend-v2-planning/
├── 01-product-audit.md          — V1 screen-by-screen audit and scores
├── 02-design-language.md        — Visual principles, emotional goals, aesthetic references
├── 03-design-system.md          — Complete token system (CSS custom properties)
├── 04-component-library.md      — Every component with states, variants, and accessibility
├── 05-information-architecture.md — Navigation, page structure, mobile patterns
├── 06-domain-ui-mapping.md      — Domain concept → UI translation table
├── 07-visualization-strategy.md — Library evaluation for lineage graph, sparklines
├── 08-frontend-stack-evaluation.md — MUI vs shadcn vs Mantine; final stack decision
├── 09-migration-roadmap.md      — 6-phase parallel migration plan
├── 10-wireframe-spec.md         — Textual wireframes for every screen
├── 11-performance-budget.md     — Bundle, render, and interaction targets
├── 12-accessibility-spec.md     — WCAG 2.1 AA, keyboard, screen reader, motion
└── FRONTEND_V2_MASTER_SPEC.md   — This document
```

---

## Implementation Entry Point

When beginning implementation, start at **Phase 0**:

1. Read `09-migration-roadmap.md` Phase 0 task list.
2. Read `03-design-system.md` — understand every token before touching a component.
3. Read `08-frontend-stack-evaluation.md` — understand why shadcn/ui, what Radix provides.
4. Install packages as listed in Phase 0.
5. Create `src/styles/tokens.css` from `03-design-system.md`.
6. Verify a single shadcn Button renders with dark tokens before proceeding to Phase 1.

Do not skip phases. Phase 0 and 1 are the foundation everything else stands on. A shortcut here creates design inconsistency debt that costs more to fix than it saved.
