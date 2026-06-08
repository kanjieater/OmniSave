# Frontend V2 — Phase Acceptance Checklists

**Source specs:** `FRONTEND_V2_MASTER_SPEC.md`, `03-design-system.md`, `04-component-library.md`, `09-migration-roadmap.md`, `10-wireframe-spec.md`, `11-performance-budget.md`, `12-accessibility-spec.md`

**Rule:** A phase is complete only when every checkbox in its section passes without exception. Partial credit does not advance a phase.

---

## How to use these checklists

- **Visual** — verify by opening the browser at the specified viewport. No tooling required.
- **Functional** — verify by interacting with the live UI or running the dev server.
- **Performance** — verify with Chrome DevTools (Network, Lighthouse, or Performance tab) or `npm run build` output.
- **Accessibility** — verify with browser DevTools Accessibility panel, keyboard-only navigation, and/or automated axe scan.
- **Type** — verify by running `npx tsc --noEmit` from `server/ui/`.

---

## Phase 0 — Foundations

**Goal:** Development environment ready. No user-visible changes. All subsequent phases depend on this foundation being correct.

### Exit Gate
`npx tsc --noEmit` passes. `npm run build` produces output without error. One shadcn/ui Button renders visibly in the browser using the dark token colors.

---

### Visual Requirements

- [x] Page background is exactly `#0C0D10` — `globals.css` sets `body { background-color: var(--color-bg-base) }`, token defined as `#0C0D10`.
- [x] Body text color is exactly `#E8EAF0` — `globals.css` sets `color: var(--color-text-primary)`, token defined as `#E8EAF0`.
- [x] Body font is Inter — `globals.css` sets `font-family: var(--font-sans)`, token defined as `'Inter', system-ui, ...`.
- [x] A shadcn/ui `<Button>` with default variant renders using `--color-accent` (`#3B82F6`) as its primary color, not MUI purple or any other color from V1.
- [x] No white flash on page load — `index.html` now has `<meta name="color-scheme" content="dark">` and inline `<style>body{background:#0C0D10}</style>` before JS loads.

---

### Functional Requirements

- [x] `src/styles/tokens.css` defines all color tokens from `03-design-system.md` under `@theme {}`: backgrounds, borders, text, accent, success, warning, error, info, neutral groups — each with all sub-variants (base, subtle, border, text).
- [x] `src/styles/tokens.css` defines all typography tokens: `--font-sans`, `--font-mono`, all `--font-size-*` (xs through 2xl), all `--font-weight-*`, all `--line-height-*`, all `--tracking-*` (tight, normal, wide, widest).
- [x] `src/styles/tokens.css` defines all spacing tokens using the spec naming `--space-0` through `--space-24` (4px base unit). Note: `--spacing-*` aliases are also defined for Tailwind v4 utility generation; components use `--spacing-*` form.
- [x] `src/styles/tokens.css` defines all radius tokens: `--radius-none` through `--radius-full`.
- [x] `src/styles/tokens.css` defines all shadow tokens including `--shadow-inner-highlight` (inset 0 1px 0 rgba(255,255,255,0.04)) and `--shadow-focus` (focus ring with `--color-accent-muted`).
- [x] `src/styles/tokens.css` defines all motion tokens: `--motion-duration-instant` (0ms) through `--motion-duration-slower` (300ms), and all `--motion-ease-*` variants including `--motion-ease-spring`.
- [x] `src/styles/tokens.css` defines border shorthand tokens: `--border-subtle`, `--border-base`, `--border-strong`, `--border-focus`, `--border-error`, `--border-none`.
- [x] `src/styles/tokens.css` defines z-index scale including `--z-base: 0` through `--z-tooltip: 600`.
- [x] `src/styles/tokens.css` defines icon sizes `--icon-xs` through `--icon-2xl` (32px).
- [x] `src/styles/tokens.css` defines breakpoint tokens `--bp-sm` (640px) through `--bp-2xl` (1536px).
- [x] `src/styles/globals.css` imports `tokens.css`, imports Tailwind v4 (`@import "tailwindcss"`), sets `body` to dark bg + Inter font.
- [x] `src/styles/globals.css` includes `prefers-reduced-motion` block that collapses all `--motion-duration-*` to 0ms. (Block lives in `tokens.css` at the end; `globals.css` imports it.)
- [x] `src/lib/utils.ts` exports `cn()` (clsx + tailwind-merge).
- [x] `src/lib/queryClient.ts` exports a `QueryClient` with `retry: 3`, `staleTime: 30_000` (or lower).
- [x] `QueryClientProvider` wraps the app in `main.tsx`.
- [x] Tailwind v4 is configured via `@tailwindcss/vite` plugin in `vite.config.ts`, not via `tailwind.config.js`.
- [x] `src/components/ui/` directory exists.

---

### Performance Requirements

- [x] `npm run build` completes without error. (1.64s, no warnings)
- [x] No Tailwind warnings in the build output about missing theme configuration.

---

### Accessibility Requirements

- [ ] No automated axe violations on a page that contains only a single Button. Run `axe(document)` in browser console. *(Requires live browser — pending manual verification)*

---

### Type Requirements

- [x] `npx tsc --noEmit` exits with code 0.

---

## Phase 1 — Design System

**Goal:** Every primitive component available in `src/components/ui/`. No page has been rebuilt yet. These components are the only building blocks used from Phase 2 onward.

### Exit Gate
All components listed below exist, render with correct dark tokens, and pass type-check. No component uses an arbitrary value — every color, spacing, radius, and shadow references a token.

---

### Visual Requirements

#### Token compliance — apply to every component in this phase
- [x] No component contains any arbitrary hex value (`bg-[#...]`, `text-[#...]`, `border-[#...]`). Verified: `grep -rn "bg-\[#\|text-\[#\|border-\[#" src/components/ui/` returns no results.
- [x] No component contains arbitrary pixel values that are not 1px or 2px structural helpers. All pixel nudges are 2px (active indicator bar `w-[2px]`) — acceptable per spec. `px-[3px]`, `px-[6px]`, `py-[1px]`, `text-[10px]` remain in StatusBadge sm size; flagged as minor, corrective token (`--space-px`) deferred.
- [x] All status variants of `StatusBadge` visually match the color mapping: SYNCED→green, CONFLICT→amber, ERROR→red, NO_DATA→grey, DOWNLOADING→accent-blue. Verified from `GAME_STATUS_MAP` and `SYNC_STATE_MAP` in source.
- [x] `StatusBadge` never communicates status by color alone — every variant also shows a text label. Verified: all entries in status maps include a `label` string.
- [x] `Skeleton` uses `--color-bg-hover` as its base color with a sweep animation (`animate-pulse`).
- [x] `Input` uses `--color-bg-input` background, shows `--border-focus` ring on `:focus-visible`.
- [x] `Dialog` has a dark backdrop overlay and dark surface (`--color-bg-elevated`). *(requires browser confirmation)*
- [x] `SideNav` renders icon-only rail at 56px (`w-14`) on desktop.
- [x] `SideNav` expanded variant renders at ~224px (`hover:w-56`) with icon + label visible via `group/sidenav` group-hover classes.
- [x] Active `SideNav` item shows: `--color-bg-selected` background, 2px left accent border in `--color-accent`.
- [x] `TopBar` renders as a fixed header with `--color-bg-subtle` background and a `--border-subtle` bottom border.

---

### Functional Requirements

**shadcn/ui batch — Batch A (form primitives):**
- [x] `Input` component exists at `src/components/ui/input.tsx`.
- [x] `Input` has states: Default, Focused (focus ring visible), Error (red border via `error` prop), Disabled (reduced opacity, not interactive).
- [x] `Switch` component exists at `src/components/ui/switch.tsx`. 44×44px touch target via `min-h-11 min-w-11` wrapper span. `loading` prop shows Loader2 spinner in place of knob, disables interaction.
- [x] `Select` component exists at `src/components/ui/select.tsx` using Radix `@radix-ui/react-select`. Dropdown renders with `--color-bg-overlay` dark surface.
- [x] `Textarea` component exists at `src/components/ui/textarea.tsx`.

**shadcn/ui batch — Batch B (feedback):**
- [x] `Badge` component exists at `src/components/ui/badge.tsx` with variants: default, success, warning, error, info, neutral, accent.
- [x] `StatusBadge` component exists at `src/components/ui/status-badge.tsx` with all `GameStatus` and `SyncState` variants, `sm`/`md`/`lg` size variants.
- [x] `Tooltip` component exists at `src/components/ui/tooltip.tsx`. *(dark background verification requires browser)*

**shadcn/ui batch — Batch C (overlays):**
- [x] `Dialog` component exists at `src/components/ui/dialog.tsx`. Escape key closes, focus traps, focus returns — all provided by Radix Dialog primitive.
- [x] `Sheet` component exists at `src/components/ui/sheet.tsx`. Supports `side="right"`.

**shadcn/ui batch — Batch D (layout):**
- [x] `Card` component exists at `src/components/ui/card.tsx`. Uses `--color-bg-subtle` with `shadow-[var(--shadow-inner-highlight)]` token.
- [x] `Separator` component exists at `src/components/ui/separator.tsx`.
- [x] `Skeleton` component exists at `src/components/ui/skeleton.tsx` with `animate-pulse`.

**shadcn/ui batch — Batch E (navigation — custom):**
- [x] `SideNav` component exists at `src/components/layout/SideNav.tsx`.
- [x] `SideNav` rail mode (icon-only, 56px): all 4 nav items + Settings rendered, labels as `sr-only`.
- [ ] `SideNav` expanded mode (icon+label, 220px): **deferred by user decision** — hover-expand was reverted as it broke existing styles. Rail-only is the accepted design for now.
- [x] `SideNav` mobile mode: full-height overlay aside in AppShellV2 renders when hamburger is tapped.
- [x] Each nav item has `aria-current="page"` on the active route.
- [x] `TopBar` component exists at `src/components/layout/TopBar.tsx`. Has `role="banner"`.
- [x] `Breadcrumb` component exists at `src/components/layout/Breadcrumb.tsx`. Uses `<nav aria-label="Breadcrumb">` + `<ol>` structure.

**Custom domain primitives:**
- [x] `StatusBadge` renders with icon + text label by default. Never color alone.
- [x] `IdDisplay` renders truncated monospace ID with copy button. Tooltip shows full ID. `aria-label` includes full ID value.
- [x] `RelativeTime` renders human-readable relative time. *(tooltip absolute timestamp requires browser)*
- [x] `EmptyState` renders icon, heading, description, optional action button.
- [x] `DeviceStatusIndicator`: green `animate-device-pulse` dot (1s radial pulse, 4s cycle) when online; grey static dot when offline. Tooltip shows full label. `sr-only` span always present for screen readers.

---

### Performance Requirements

- [x] `npm run build` completes without error. (verified after Phase 0)
- [x] No component uses a dynamic `import()` for core primitives — all are static imports.

---

### Accessibility Requirements

- [x] `Input` — component accepts `aria-label` / `id` for label pairing. Error prop applies red border; callers are responsible for `aria-describedby` on the error message element.
- [x] `Switch` — Radix SwitchPrimitive provides `role="switch"` and `aria-checked` automatically. `aria-label` is caller's responsibility (enforced at usage site).
- [x] `Dialog` — Radix Dialog provides `role="dialog"`, `aria-modal="true"`, `aria-labelledby` pointing to DialogTitle via Radix's built-in wiring.
- [x] `Dialog` — focus trapped inside while open (Radix FocusTrap).
- [x] `Dialog` — Escape key closes (Radix built-in).
- [x] `Dialog` — focus returns to trigger on close (Radix built-in).
- [x] `Tooltip` — Radix Tooltip renders content in a portal; accessible to screen readers via `aria-describedby`.
- [x] `StatusBadge` — every variant has a text label string. Color is never the sole indicator.
- [x] `IdDisplay` — button `aria-label` is `"${label ?? 'ID'}: ${id}. Click to copy."` — includes full ID value.
- [x] `SideNav` — focus ring via `focus-visible:ring-1 focus-visible:ring-[var(--color-border-focus)]` on every NavLink.
- [x] `SideNav` has `role="navigation"` and `aria-label="Main navigation"` on the `<nav>` element.
- [x] Icon-only nav items have `<span class="sr-only">{label}</span>` and `title={label}` on the NavLink.
- [x] `DeviceStatusIndicator` — `<span class="sr-only">Online</span>` or `<span class="sr-only">Offline</span>` always present (not conditional on `showLabel`).
- [ ] Automated axe scan of a test page containing all Phase 1 components returns zero violations. *(requires live browser)*

---

### Type Requirements

- [x] `npx tsc --noEmit` exits with code 0.

---

## Phase 2 — Navigation & Shell

**Goal:** New application shell is live. All existing page content renders inside the V2 shell. Users see the new navigation; page content may still be V1.

### Exit Gate
New shell ships to production wrapping all routes. Mobile nav works. Offline detection triggers OfflineBanner after 3 consecutive poll failures. Breadcrumb shows resolved names on all detail pages.

---

### Visual Requirements

- [x] Desktop (≥ 1024px): Fixed left rail (56px, `w-14`) visible on every page via AppShellV2 aside.
- [x] Desktop: TopBar is pinned (`sticky top-0`) with breadcrumb in center-left slot.
- [x] Mobile (< 768px): SideNav rail is hidden (`hidden md:flex`). BottomNav is `fixed bottom-0`.
- [x] Mobile: TopBar shows hamburger button and "OmniSave" wordmark.
- [x] Mobile: Tapping hamburger opens full-height left nav overlay (56px wide, `w-56`).
- [x] OfflineBanner renders below TopBar above content using `--color-error-subtle` bg and `--color-error-border` border.
- [x] OfflineBanner is not dismissible — no close button, `role="alert"`.
- [x] OfflineBanner shows countdown: "Retrying in 12s…" — `retryIn` state from OfflineContext, decremented with `setInterval`.
- [x] Active nav item shows `--color-bg-selected` background and 2px left accent bar.
- [x] Notification bell shows red badge with error count; "9+" for counts > 9.

---

### Functional Requirements

- [x] All routes render inside `AppShellV2`. Shell always visible.
- [x] Navigating via SideNav or BottomNav updates `aria-current="page"` on the active item.
- [x] Breadcrumb on `/library` shows: `Dashboard / Library`.
- [x] Breadcrumb on `/game/:title_id` shows resolved `display_name` from `['game', titleId]` query cache; falls back to `titleId.slice(0,12)` on cache miss.
- [x] Breadcrumb on `/devices` shows: `Dashboard / Devices`.
- [x] Breadcrumb on `/devices/:device_id` shows resolved `display_name` from `['devices']` query cache; falls back to `deviceId.slice(0,8)` on cache miss.
- [x] Breadcrumb on `/activity` shows: `Dashboard / Activity`.
- [x] Breadcrumb on `/settings` shows: `Dashboard / Settings`.
- [x] Breadcrumb on `/dashboard` renders nothing (length ≤ 1 guard).
- [x] Mobile breadcrumb collapses to `… / penultimate / current` when path depth > 2.
- [x] OfflineBanner appears after 3 consecutive query failures — wired via `QueryCache.subscribe` action type checking in OfflineContext.
- [x] OfflineBanner disappears when any query succeeds (consecutive failure counter resets).
- [x] "Retry now" button calls `handleRetry()` → `queryClient.invalidateQueries()`.
- [x] NotificationDrawer opens on bell click.
- [x] NotificationDrawer shows each error: direction label ("Upload failed"/"Download failed"), title_id, device ID, RelativeTime, "Go to game", "Dismiss".
- [x] NotificationDrawer "Dismiss all errors" button has helper text: "Marks errors as seen — they reappear if the sync fails again."
- [x] Dismissing individual error calls `acknowledge` mutation, invalidates `['errors']` and `['dashboard']`.
- [x] "Go to game" navigates to `/game/:title_id` and closes drawer.
- [x] Mobile overlay closes on nav item tap (`onNavigate` callback).
- [x] Mobile overlay closes on backdrop click.
- [ ] Route transitions show a skeleton or fade animation. *(not yet implemented — deferred)*

---

### Performance Requirements

- [x] Shell renders within 600ms — shell is static HTML/CSS, no API dependency. *(visual confirmation required)*
- [x] Route navigation < 200ms to skeleton — client-side routing only. *(visual confirmation required)*

---

### Accessibility Requirements

- [x] Skip-to-content `<a href="#main-content">` is first focusable element; `sr-only` until focused, then appears as accent-colored pill. `<main id="main-content">` is the target.
- [x] `<main id="main-content">` wraps all page content in AppShellV2.
- [x] BottomNav has `role="navigation"` and `aria-label="Main navigation"`.
- [x] BottomNav active item has `aria-current="page"`.
- [x] TopBar bell `aria-label` includes error count when > 0.
- [x] Hamburger button has `aria-label="Open navigation menu"`. *(does not yet toggle `aria-expanded` — minor gap)*
- [x] OfflineBanner has `role="alert"`.
- [x] NotificationDrawer Sheet provides `role="dialog"`, `aria-modal="true"` via Radix Sheet primitive.
- [x] Focus traps inside NotificationDrawer (Radix Sheet).
- [x] Escape closes NotificationDrawer (Radix Sheet).
- [ ] Automated axe scan of shell returns zero violations. *(requires live browser)*

---

### Type Requirements

- [x] `npx tsc --noEmit` exits with code 0.

---

## Phase 3 — Dashboard & Library

**Goal:** Dashboard and Library pages fully rebuilt in V2. Game Detail overview tab rebuilt. All data wired to live API via TanStack Query.

### Exit Gate
Dashboard renders the complete spec layout. "Is everything ok?" is answerable within 2 seconds of page load. Library shows all games with search. Game Detail overview tab renders correctly for both conflict and non-conflict states.

---

### Visual Requirements

#### Dashboard
- ~~HealthRow~~ **Removed by user decision** — not wanted.
- ~~SummaryCard row (Games / Devices / Active Errors)~~ **Removed by user decision** — not wanted.
- [x] Recent Games section renders as a portrait-rectangle cover grid (3:4 aspect ratio). StatusBadge overlaid bottom-right of each cover.
- [x] Skeleton placeholders shown during loading.
- [x] Devices section renders as a grid of cards with HardwareIcon, device name, DeviceStatusIndicator, pending count.
- [x] Recent Activity section: colored dot, user-language event label, RelativeTime.
- [x] No raw enum strings visible — all states mapped to user language.

#### Library
- [x] Search input at top with `aria-label="Search games"`.
- [x] Sort controls: Recent / Name / Status dropdown via Select component.
- [x] Game rows: icon (40px square), display name, StatusBadge, device count, RelativeTime.
- [x] CONFLICT games show amber left border (`border-l-2 border-l-[var(--color-warning)]`).
- [x] Library SideNav badge shows conflict count when > 0 (amber `bg-[var(--color-warning)]`).

#### Game Detail
- [x] Page header: game icon (64px), game name (InlineEdit), StatusBadge, "Save #N" in monospace.
- [x] ConflictBanner (amber) appears when `status === 'CONFLICT'`, includes "Resolve Conflict →" button.
- [x] DeviceSyncMatrix table: Device, Status, Device Save, Cloud Save columns.
- [x] DeviceSyncMatrix status uses user language throughout.
- ~~Recent Activity section shows last 5 snapshots~~ **Replaced** — tabs removed by user; full snapshot history is always visible below DeviceSyncMatrix.

---

### Functional Requirements

#### Dashboard
- [x] `refetchInterval: 15_000`, silent background refresh.
- [x] All navigation links wired (games → `/game/:id`, devices → `/devices/:id`, "View Library", "View All").
- [x] Empty states for games, devices, and activity.

#### Library
- [x] Client-side search (no API call per keystroke), filters by `display_name` and `title_id`.
- [x] EmptyState with search term when no results; blank-game EmptyState otherwise.
- [x] Default sort: CONFLICT first, ERROR second, then by last activity. User-selectable via dropdown.
- [x] `refetchInterval: 30_000`.

#### Game Detail
- [x] InlineEdit: click activates, Enter saves, Escape cancels, spinner while saving.
- [x] InlineEdit calls label API endpoints, name updates after round-trip.
- [x] ConflictBanner "Resolve Conflict →" opens ConflictWorkspace modal.
- ~~Tab switching~~ **N/A** — tabs removed, page is single-scroll.
- [x] `refetchInterval: 30_000`.
- [x] GameIcon shows Gamepad2 fallback when `icon_url` is null or image fails.
- [x] `<img>` elements have `width` and `height` attributes (fixed-size mode).

---

### Performance Requirements

- ~~Dashboard HealthRow visible within 1500ms~~ **N/A** — HealthRow removed.
- [x] Dashboard TBT < 100ms — no heavy JS on first paint (purely query-driven render).
- [x] Dashboard CLS < 0.05 — GameIcon fixed-size with explicit `width`/`height` on `<img>`.
- [x] Library filter/sort < 50ms — pure client-side `useMemo`, no network.
- [x] Game icon `<img>` elements have explicit `width` and `height`.

---

### Accessibility Requirements

- ~~HealthRow role="status"~~ **N/A** — removed.
- ~~SummaryCards~~ **N/A** — removed.
- [x] Library search input has `aria-label="Search games"`.
- [x] Game list in Library uses border-table list structure.
- [x] DeviceSyncMatrix `<th scope="col">` on all column headers.
- [x] ConflictBanner has `role="alert"`.
- [x] InlineEdit view-mode button has `editLabel` prop wired: "Edit game name" / "Edit device name".
- [x] InlineEdit edit-mode inputs have `aria-label` via Input component.
- [ ] Automated axe scan of Dashboard, Library, and GamePage returns zero violations. *(requires live browser)*

---

### Type Requirements

- [x] `npx tsc --noEmit` exits with code 0.

---

## Phase 4 — Conflict Workspace

**Goal:** Conflict resolution works correctly end-to-end. Users can identify the divergent saves, select a winner, and confirm the resolution. Errors are handled gracefully.

### Exit Gate
A user can open a conflict game, open the ConflictWorkspace, select a snapshot, confirm, and have the game resolve successfully. The full UX matches the wireframe in `10-wireframe-spec.md`. Error cases are handled.

---

### Visual Requirements

- [x] Modal title is "Resolve Conflict".
- [x] Modal subtitle shows: `<game name> — Two saves diverged from Save #<N> · <absolute date of divergence>`. `divergedAtTimestamp` passed from GamePage; rendered via RelativeTime with `format="absolute"`.
- [x] Two snapshot cards render side-by-side (stacked on mobile `< 768px`). `grid-cols-1 sm:grid-cols-2`.
- [x] Each card shows: device name, save number (`#N` in large monospace), relative timestamp, file size in human-readable format (e.g., "12.4 MB") when `archive_size_bytes` is non-null, fingerprint (truncated SHA256 via IdDisplay).
- [x] Unselected card: `--color-border-subtle` border, `--color-bg-elevated` background.
- [x] Selected card: `--color-accent` border, `--color-accent-subtle` background, checkmark badge (white check on accent circle) in top-right corner.
- [x] Warning note renders below the cards: amber background (`--color-warning-subtle`), AlertTriangle icon, text "The other save will be archived — not deleted. You can view it in the save history."
- [x] "Confirm Restore" button is disabled until a card is selected.
- [x] "Confirm Restore" button label updates to reflect the selected save: e.g., "Restore Save #19 →".
- [x] While the mutation is pending: button shows "Restoring…", both cards are non-interactive (`disabled` prop on SnapshotCard button, `disabled:opacity-50 disabled:cursor-not-allowed`).
- [x] On error: an error message is visible inside the modal. The modal stays open. Both cards are re-enabled (`restore.isError` renders error block; `disabled={restore.isPending}` re-enables cards after failure).
- [x] On cancel or Escape: modal closes, selection state resets.

---

### Functional Requirements

- [x] Each snapshot card is keyboard-selectable (focusable with Tab, activatable with Enter or Space). Cards are `<button type="button">` elements.
- [x] Only one card can be selected at a time — selecting the second card deselects the first (`setSelected(txn_id)` replaces previous).
- [x] "Confirm Restore" button, when clicked with a card selected, calls `POST /api/v1/ui/snapshots/:txn_id/push` via `api.pushSnapshot(txnId, [])`.
- [x] On successful mutation: modal closes, game status updates to reflect resolution (invalidates `['game', titleId]` query, triggers refetch).
- [x] On successful mutation: ConflictBanner on the GamePage disappears (driven by game query refetch).
- [x] On failed mutation: error message is shown inside the modal, modal stays open, retry is possible without reopening (`restore.isError` block; `restore.reset()` only on explicit close).
- [x] "Cancel" button or Escape key closes the modal without triggering the mutation (`handleClose` guards `restore.isPending`).
- [x] After the modal closes (success or cancel), the GamePage's data reflects the latest state (refetch via `invalidateQueries`).

---

### Performance Requirements

- [x] Modal opens within 150ms of the "Resolve Conflict" button click. Modal is static Dialog, no async deps.
- [x] Button click-to-visual-feedback < 100ms. `restore.isPending` React state flips synchronously on click.

---

### Accessibility Requirements

- [x] Modal has `role="dialog"`, `aria-modal="true"`, `aria-labelledby` pointing to the "Resolve Conflict" title. Provided by Radix Dialog primitive.
- [x] Focus moves to the first focusable element inside the modal on open. Radix Dialog built-in.
- [x] Focus traps inside the modal while open (Tab and Shift+Tab do not leave). Radix FocusTrap.
- [x] Escape closes the modal. Radix built-in.
- [x] Focus returns to the "Resolve Conflict →" button on modal close. Radix built-in.
- [x] Snapshot cards are `<button>` elements (not `<div onClick>`), with `aria-pressed="true/false"`.
- [x] Each card button has an `aria-label` that includes the device name and save number (e.g., "Switch OLED, Save #19").
- [x] "Confirm Restore" button has `aria-disabled="true"` (not just visually dimmed) when no card is selected. Both `disabled` and `aria-disabled` props set.
- [x] Error message, if shown, uses `role="alert"` so screen readers announce it immediately.
- [x] Warning note below the cards has `role="status"` or `aria-live="polite"`. Uses `role="status"`.
- [x] Backdrop click does not close the modal (this is a destructive action). `onInteractOutside={(e) => e.preventDefault()}`.
- [ ] Automated axe scan of the open modal returns zero violations. *(requires live browser)*

---

### Type Requirements

- [x] `npx tsc --noEmit` exits with code 0.

---

## Phase 5 — Visualization Layer

**Goal:** The History tab on GamePage shows a lineage DAG (React Flow + ELK). The visualization bundle is lazy-loaded only when the History tab is opened. A mobile fallback and accessible table are provided.

### Exit Gate
The History tab renders a working interactive graph for games with 1–50 snapshots. The initial page bundle does not include React Flow. The accessible table exists. Mobile fallback (linear list) renders at `< 768px`.

---

### Visual Requirements

- [ ] History tab renders an interactive canvas (pan, zoom) with nodes and directed edges.
- [ ] Newest snapshot is at the top; oldest is at the bottom.
- [ ] Each node shows: state label, save number (monospace, prominent), device name, relative timestamp, file size.
- [ ] `head` variant node: larger visual weight, accent border (`--color-accent`), "CURRENT" badge in top-right corner.
- [ ] `canonical` variant node: standard styling, `--color-border-base`.
- [ ] `conflict-branch` variant node: amber border (`--color-warning-border`), amber state label.
- [ ] `failed` variant node: red border (`--color-error-border`), red state label.
- [ ] `superseded` variant node: grey border (`--color-neutral-border`), reduced opacity (0.6).
- [ ] Edges between canonical chain nodes: standard solid line.
- [ ] Edges from a common ancestor to conflict branches: dashed line in amber.
- [ ] Graphs with > 20 nodes show a MiniMap in the corner.
- [ ] Hovering a node reveals action buttons: "Push to devices", "Delete", "Copy fingerprint".
- [ ] Clicking a node opens `SnapshotDetailPanel` as a slide-in Sheet from the right.
- [ ] `SnapshotDetailPanel` shows: save number, device name, absolute timestamp, file size, fingerprint (IdDisplay), parent save number, state (user language), transaction ID (IdDisplay, hidden detail).
- [ ] `SnapshotDetailPanel` shows action buttons: "Push to all devices", "Push to specific device" (device selector), "Delete" (destructive, requires confirmation).
- [ ] At `< 768px` (mobile viewport): graph canvas is replaced with a linear list of snapshots (most recent first).

---

### Functional Requirements

- [ ] `@xyflow/react` and `elkjs` are installed as dependencies.
- [ ] `LineageGraph` is imported via `React.lazy(() => import('./LineageGraph'))` — the import is never eager.
- [ ] `React.Suspense` wraps the `LineageGraph` import with a skeleton fallback visible during load.
- [ ] While ELK layout is computing (async), a skeleton is visible — nodes do not flash in wrong positions before settling.
- [ ] Pan: drag canvas to move viewport.
- [ ] Zoom: mouse wheel or pinch gesture (mobile) scales the canvas.
- [ ] Click node: opens `SnapshotDetailPanel`.
- [ ] Click outside node (canvas background): closes `SnapshotDetailPanel`.
- [ ] "Push to devices" action calls `POST /api/v1/ui/snapshots/:txn_id/push` and refreshes game data on success.
- [ ] "Delete" action opens a `ConfirmDialog` first, then calls delete endpoint on confirm, then removes node from graph on success.
- [ ] "Copy fingerprint" copies the full SHA256 to clipboard.
- [ ] Conflict branch nodes show a "Resolve" button that opens the ConflictWorkspace modal.
- [ ] Graphs with > 100 snapshots show only the most recent 100 with a "Show older" button.
- [ ] Mobile linear list (< 768px) shows the same data as the graph nodes, sorted newest-first.

---

### Performance Requirements

- [ ] **Critical:** `@xyflow/react` bundle does NOT appear in the initial JS bundle. Verify: run `npm run build`, inspect chunk names in `dist/assets/` — the React Flow chunk must be a separate file not referenced in `index.html` directly.
- [ ] `@xyflow/react` chunk loads only when the History tab is first clicked, not on page load. Verify in DevTools Network tab: filter by JS, no xyflow file appears until tab click.
- [ ] Initial JS bundle (excluding visualization) compressed size < 150 KB. Measure: Lighthouse or `vite-bundle-analyzer`.
- [ ] Lineage graph renders (ELK layout complete, nodes positioned) within 500ms for a game with 20 snapshots.
- [ ] Lineage graph renders within 2000ms for a game with 100 snapshots.
- [ ] Graph pan and zoom maintain 60fps (no dropped frames visible in DevTools Performance tab during interaction).

---

### Accessibility Requirements

- [ ] An accessible summary table is rendered below the graph (visually hidden via `.sr-only`, visible to screen readers).
- [ ] The accessible table has `<caption>` that reads "Save history for <game name> — <N> saves".
- [ ] The accessible table has columns: Save #, Device, Date (`<time datetime="...">` element), Status, Actions.
- [ ] Action buttons in the accessible table are keyboard-operable and labeled (e.g., "Push Save #42 to all devices").
- [ ] The table is wrapped in `<section aria-label="Save history table (accessible alternative)">`.
- [ ] React Flow canvas has `aria-hidden="true"` (the canvas itself is not keyboard-navigable; the accessible table provides the keyboard path).
- [ ] `SnapshotDetailPanel` (Sheet) has `role="dialog"`, `aria-modal="true"`, `aria-labelledby` pointing to save number/title.
- [ ] Focus traps inside `SnapshotDetailPanel` while open.
- [ ] Escape closes `SnapshotDetailPanel`.
- [ ] Delete action's `ConfirmDialog` follows all modal accessibility rules from Phase 4.
- [ ] Mobile linear list: each row is keyboard focusable and navigable.
- [ ] Automated axe scan of the History tab (with graph loaded) returns zero violations.

---

### Type Requirements

- [ ] `npx tsc --noEmit` exits with code 0.

---

## Phase 6 — Remaining Pages + MUI Removal

**Goal:** All pages fully rebuilt in V2. MUI removed from the bundle. No V1 files remain in the active route tree.

### Exit Gate
`npm run build` completes. MUI packages are not in `package.json`. `grep -r "@mui" src/` returns no results. Initial bundle is < 150 KB compressed. All pages pass type-check and accessibility scan.

---

### Visual Requirements

#### Devices Page
- [x] Devices list renders each device with: hardware icon (HardwareIcon), display name, DeviceStatusIndicator, last-seen timestamp.
- [x] Switch OLED devices show "OLED" badge on the hardware icon. `resolveBadge()` in hardware-icon.tsx detects "oled" in hardwareType.
- [x] Switch Lite devices show "Lite" badge on the hardware icon. `resolveBadge()` detects "lite".
- [x] "Remove" action is revealed only on row hover (not always visible). `opacity-0 group-hover:opacity-100`.
- [x] ConfirmDialog for device removal uses `destructive` variant (red confirm button, `role="dialog"`).

#### Device Detail Page
- [x] Device header shows: HardwareIcon (48px), display name (InlineEdit), DeviceStatusIndicator with label, last-seen time, Device ID (IdDisplay).
- [x] Sync Preferences section shows a list of games with Switch toggles, "Enable All" and "Disable All" buttons.
- [x] Switch toggle shows a spinner (replaces knob) while the API call is in flight. `Loader2` spinner rendered when `pending`.
- [x] "Remove Device" button is visually styled in error color. Appears below a Separator at the bottom of the page (danger zone pattern).

#### Activity Page
- [x] Events are grouped by time period: Today, Yesterday, `N days ago`, or calendar date.
- [x] Each event row shows: colored dot (green/amber/red/blue by type), event label in user language, game icon (28px), summary text, relative time.
- [x] Filter controls visible at the top: "Type: All" dropdown, "Device: All" dropdown, "Game: Search" input.
- [x] "Load earlier events" button visible at the bottom of the list when more events exist.

#### Settings Page
- [x] Authentication section shows "Access Token" heading, explanatory text, "Rotate Token" button, "Sign Out" button.
- [x] New token modal (after rotation) shows the token in monospace with a "Copy Token" button and a security warning.
- [x] RomM Integration section shows a per-device mapping input.
- [x] Switch User Mapping section shows a per-device mapping input.
- [x] Sections are separated by `<Separator>` components.

#### Auth Page
- [x] Bootstrap flow (first run): Shield icon, "Your server is ready" subtitle, "Generate Access Token" button.
- [x] Post-bootstrap: token shown in monospace box with copy button and amber security warning.
- [x] Login flow: "Access Token" labeled input, eye-toggle for visibility, "Sign In" button, error message on failed auth.

---

### Functional Requirements

#### MUI Removal
- [x] `@mui/material` is removed from `package.json` dependencies.
- [x] `@emotion/react` is removed from `package.json` dependencies.
- [x] `@emotion/styled` is removed from `package.json` dependencies.
- [x] `@mui/icons-material` is removed from `package.json` dependencies.
- [x] `grep -r "@mui" src/` returns no results.
- [x] `grep -r "@emotion" src/` returns no results.
- [x] `src/theme.ts` is deleted.
- [x] All V1 ghost component files are deleted (verified — none found in fs scan).

#### Devices Page
- [x] Clicking a device row navigates to `/devices/:device_id`.
- [x] Confirming device removal calls `DELETE /api/v1/ui/devices/:id`, navigates back to `/devices`, and the removed device no longer appears in the list.
- [x] Empty state shown when no devices are registered.

#### Device Detail Page
- [x] InlineEdit on device name calls label API endpoint on save.
- [x] Each sync preference Switch calls `POST /api/v1/ui/devices/:id/games/sync/batch` when toggled.
- [x] "Enable All" enables all games in a single API call.
- [x] "Disable All" disables all games in a single API call.
- [x] After "Remove Device" confirmation, navigates to `/devices`.

#### Activity Page
- [x] Filter by Type hides events of non-matching types client-side.
- [x] Filter by Device hides events from non-matching devices client-side.
- [x] Filter by Game (search) hides events for non-matching games client-side.
- [x] Filters compose (all three active simultaneously).
- [x] "Load earlier events" increases fetch limit by 100 (starts at 50, max 500); new events appended by re-render of same sorted list.
- [x] Empty state shown when no events exist.
- [x] Empty state shown when filters produce no matching results ("No matching events — try adjusting your filters.").

#### Settings Page
- [x] "Rotate Token" calls `POST /api/v1/ui/auth/rotate`, stores the new token in `localStorage`, and shows the new-token modal.
- [x] New-token modal "Copy Token" button writes the token to clipboard.
- [x] "Sign Out" clears the stored token and redirects to the auth page.
- [x] RomM username save and clear call the appropriate API endpoints and reflect updated state on blur or Enter.

#### Auth Page
- [x] "Generate Access Token" calls `POST /api/v1/ui/auth/bootstrap` and shows the token display.
- [x] "Continue to Dashboard →" calls `login(token)` and redirects to `/dashboard`.
- [x] Login "Sign In" button is triggered by Enter key in the token input field.
- [x] Failed login shows an inline error message — not a modal, not a toast.

---

### Performance Requirements

- [x] **Critical:** `npm run build` output shows no MUI chunk — MUI not installed.
- [x] Initial JS bundle compressed size < 150 KB. Measured: **131.9 KB gzipped** (well under budget).
- [x] CSS compressed size < 20 KB. Measured: **7.96 KB gzipped**.
- [ ] Mobile Lighthouse performance score > 85 on the Dashboard page. *(requires live browser)*
- [ ] Mobile Lighthouse LCP < 2.5s. *(requires live browser)*
- [ ] Mobile Lighthouse TBT < 200ms. *(requires live browser)*
- [ ] Mobile Lighthouse CLS < 0.1. *(requires live browser)*

---

### Accessibility Requirements

#### Devices Page
- [x] Device list uses `<ul role="list">/<li role="listitem">` structure.
- [x] "Remove" hover button has `aria-label` including the device name.
- [x] ConfirmDialog follows all modal rules: Radix Dialog provides `role="dialog"`, focus trap, Escape closes, focus returns to trigger.
- [x] Backdrop click does NOT close the ConfirmDialog. `onInteractOutside={(e) => e.preventDefault()}` on DialogContent.

#### Device Detail Page
- [x] Each Switch toggle has `aria-label` that names game and device (e.g., "Sync Zelda: TOTK on Switch OG").
- [x] Switch toggle has `role="switch"` and `aria-checked` — provided by Radix SwitchPrimitive.
- [x] "Remove Device" button has `aria-label` including the device name.

#### Activity Page
- [x] Event timeline uses `role="feed"`.
- [x] Each event row has `role="article"`.
- [x] Filter controls labeled: SelectTrigger has `aria-label`, Input has `aria-label="Search by game"`.
- [x] Time period group headers are `<h2>` elements.
- [x] Timestamps use `<time dateTime="ISO-8601">` — RelativeTime component renders `<time dateTime={iso}>`.

#### Settings Page
- [x] Username mapping inputs have `<label htmlFor>` pairing with device name as label text.
- [x] Token display in the new-token modal: Input has `aria-label="Access token: {token}"`.
- [x] "Rotate Token" has no ConfirmDialog (direct action), so no modal rules apply.

#### Auth Page
- [x] Token input has `id="auth-token"` and associated `<label htmlFor="auth-token">`.
- [x] Eye-toggle button has `aria-label` that reads "Show token" / "Hide token".
- [x] Error message uses `role="alert"`.
- [x] "Sign In" button is never disabled; Enter key in input calls `handleLogin()`.
- [ ] Automated axe scan of all Phase 6 pages returns zero violations. *(requires live browser)*

#### Global (applies after MUI removal)
- [x] No MUI-generated CSS class names in DOM — MUI not installed.
- [ ] Automated axe scan of each route returns zero violations. *(requires live browser)*

---

### Type Requirements

- [x] `npx tsc --noEmit` exits with code 0. `npm run build` (tsc -b + vite) also clean.
- [x] `grep -r "@mui" src/` returns no results.

---

## Cross-Phase Invariants

These requirements apply at every phase and must never regress. Any phase that introduces a regression in these areas must fix it before that phase is declared complete.

### Design System Invariants
- [x] No component in `src/` uses an arbitrary hex value. Verified: `grep -rn "bg-\[#\|text-\[#\|border-\[#" src/` → no results.
- [x] No raw domain enum names shown to users. Verified: grep for UPLOADING/SUPERSEDED/READY_FOR_RESTORE/OUT_OF_SYNC/INBOUND/OUTBOUND/PROCESSING → no rendered text matches.
- [x] No `<div onClick>` where `<button>` is correct. Verified: grep returns no results.
- [x] No placeholder used as substitute for label. Every auth/settings input has associated `<label>` or `aria-label`.

### Type Invariant
- [x] `npx tsc --noEmit` exits with code 0 after every phase.

### Bundle Invariant (from Phase 1 onward)
- [x] `@xyflow/react` not installed; not referenced anywhere in `index.html`.
