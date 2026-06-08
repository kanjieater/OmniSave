# 08 — Frontend Stack Evaluation

Evaluation of UI component libraries and styling frameworks for OmniSave V2.

---

## Evaluation Criteria

| Criterion | Weight | Rationale |
|-----------|--------|-----------|
| Design system control | 5/5 | We have specific visual requirements. Cannot be blocked by library defaults. |
| Accessibility | 4/5 | Keyboard nav, screen reader, ARIA all required. |
| Performance | 4/5 | Dashboard must load fast. Visualization lazy-loaded. |
| TypeScript quality | 4/5 | Entire project is strict TypeScript. |
| Tailwind compatibility | 3/5 | Tailwind v4 is the preferred styling layer. |
| Bundle size | 3/5 | Target: <150KB initial JS. Component libs must be tree-shakeable. |
| Maintenance burden | 3/5 | Self-hosted or stable external library preferred. |
| Developer experience | 2/5 | Secondary — correctness over speed. |

---

## Component Library Candidates

### Option 1: Material UI (MUI) — Current

**Score: 2/5**

**Pros:**
- Already in use — zero migration for current components.
- Comprehensive component coverage.
- Active maintenance.

**Cons:**
- Material Design aesthetic is deeply embedded. Overriding it to achieve the OmniSave design language requires fighting the framework at every turn.
- Theme customization is extensive but fragile. Every component has overrides that interact with each other unpredictably.
- Bundle size: `@mui/material` base is ~330KB gzipped — before a single component is used. Unacceptably large.
- Tailwind incompatibility: MUI's `sx` prop and Emotion CSS-in-JS conflict with Tailwind class-based styling. Both paradigms end up in the bundle.
- Accessibility is good but built on MUI's own focus management that conflicts with custom focus behaviors.
- The existing UI's core problem is MUI aesthetics — rebuilding on MUI V2 doesn't resolve this.

**Verdict: REJECT. The V2 goal of a purpose-built design aesthetic cannot be achieved staying on MUI without massive override overhead.**

---

### Option 2: Joy UI (MUI's neutral sibling)

**Score: 2.5/5**

**Pros:**
- Same team as MUI, more neutral aesthetic baseline.
- CSS variables-based theming (compatible with our token system).
- Better TypeScript than MUI.

**Cons:**
- Still carries the MUI ecosystem's Emotion dependency.
- Smaller community, fewer components than MUI.
- Still requires significant visual overrides to hit our design language.
- Bundle size not substantially better than MUI.
- Less proven than MUI in production.

**Verdict: REJECT. Doesn't solve the core problems of MUI without the benefits.**

---

### Option 3: Mantine

**Score: 3/5**

**Pros:**
- Clean, customizable design.
- CSS variables-based theming. Direct token system compatibility.
- Comprehensive component coverage (including virtualized tables, date pickers, charts).
- Good TypeScript.
- Active maintenance.
- Better aesthetic baseline than MUI.

**Cons:**
- Still a "theme it to match us" rather than "own the components" model. Visual design is constrained by Mantine's component shapes.
- Bundle size: core is ~180KB gzipped, better than MUI but still significant.
- Tailwind conflict: Mantine uses its own CSS module system. Using Tailwind alongside requires careful isolation (component styles in Mantine, layout utilities in Tailwind — manageable but awkward).
- Dark mode theming exists but the defaults lean toward rounded, soft aesthetics that need overriding for our technical feel.
- Mantine's component aesthetic is clean but generic — it will still look like "a Mantine app" without heavy customization.

**Verdict: VIABLE FALLBACK. Better than MUI, but still doesn't give full design control. Best choice if team wants a more conservative migration.**

---

### Option 4: Radix Themes

**Score: 3.5/5**

**Pros:**
- Built on Radix primitives — the gold standard for accessible headless components.
- CSS variables-based, theme-aware.
- Opinionated but customizable.
- Good TypeScript.

**Cons:**
- Radix Themes is more opinionated than Radix Primitives alone — it imposes a visual system on top of the primitives.
- The Radix Themes design aesthetic (rounded, light, modern SaaS) conflicts with our technical/dark infrastructure aesthetic.
- Overriding the Radix Themes visual layer requires the same fight as MUI, just less of it.
- The `@radix-ui/themes` package brings in CSS that conflicts with Tailwind's reset.

**Verdict: REJECT as Themes. ADOPT as the primitive layer (use Radix Primitives without Radix Themes).**

---

### Option 5: shadcn/ui — RECOMMENDED

**Score: 5/5**

**Concept:** shadcn/ui is not a library — it's a collection of copy-and-own components built on Radix Primitives, styled with Tailwind CSS. You copy component source code into your project and own it completely.

**Pros:**
- **Zero abstraction layer.** Components live in `src/components/ui/`. You own the source. No dependency version conflicts, no fighting the framework.
- **Built on Radix Primitives.** Every interactive component (Dialog, DropdownMenu, Select, Tooltip, Switch, etc.) uses Radix for accessibility — focus management, keyboard navigation, ARIA attributes — all handled correctly by default.
- **Tailwind v4 native.** shadcn/ui v2 is built specifically for Tailwind v4 with CSS-first configuration. Our token system maps directly to Tailwind CSS custom properties.
- **CSS variable tokens.** shadcn uses `--background`, `--foreground`, `--primary`, etc. as CSS variables. We replace these with our own token values. Zero override fights.
- **Full TypeScript.** Every component has correct TypeScript props.
- **Bundle size:** Only the components you copy are in your bundle. No runtime library overhead. No tree-shaking required — what's not there can't be loaded.
- **Aesthetic neutrality.** The default shadcn aesthetic is intentionally neutral — easy to push in any direction. Our dark technical design is well within the range of what shadcn handles cleanly.
- **Active development.** CLI tooling for adding components, block system for page templates.

**Cons:**
- No version pinning for components (you own the code — updates are manual). For a single-maintainer project this is acceptable.
- New components not in shadcn require building from Radix Primitives manually. This is expected and matches the design philosophy.
- Copy-and-own means you're responsible for accessibility correctness in custom components. With Radix primitives as the base, this risk is low.

**Verdict: RECOMMENDED PRIMARY CHOICE.**

---

### Tailwind Evaluation

**Version: Tailwind CSS v4**

Tailwind v4 introduces CSS-first configuration — the entire design system is defined in a CSS file (`@theme` block) that generates utility classes automatically. This is ideal for our token-first approach.

```css
/* tokens.css */
@theme {
  --color-bg-base: #0C0D10;
  --color-text-primary: #E8EAF0;
  --color-accent: #3B82F6;
  --font-sans: 'Inter', system-ui, sans-serif;
  --font-mono: 'JetBrains Mono', monospace;
  --spacing-1: 4px;
  /* ... all tokens from 03-design-system.md ... */
}
```

Tailwind v4 then generates classes like `bg-bg-base`, `text-text-primary`, `text-accent`, etc. directly from these token definitions.

**Tailwind v4 advantages over v3:**
- No `tailwind.config.js` — configuration is in CSS, co-located with design tokens.
- Native cascade layers (`@layer`) for predictable specificity.
- Container queries built-in (`@container`).
- CSS variables first-class — `var(--color-accent)` and `bg-accent` resolve to the same value.
- Faster (Rust-based engine).

---

## Final Stack Recommendation

```
UI Framework:        React 19 + TypeScript (strict)
Build:               Vite 6
Component Library:   shadcn/ui v2 (copy-and-own, Radix-based)
Primitive Layer:     @radix-ui/* (Dialog, DropdownMenu, Select, Tooltip, Switch, etc.)
Styling:             Tailwind CSS v4
Icons:               lucide-react (tree-shakeable, 2px stroke, 24px grid)
Animation:           tailwindcss-animate (shadcn dependency, lightweight)
State:               TanStack Query v5 (server state, polling, cache)
Routing:             React Router v7 (or TanStack Router v1 — either is compatible)
Visualization:       @xyflow/react + elkjs (lazy-loaded, lineage graph only)
Tables:              @tanstack/react-table (headless, renders via shadcn DataTable)
Virtual lists:       @tanstack/react-virtual (events page, large snapshot lists)
Fonts:               Inter (variable, self-hosted via fontsource)
Monospace font:      JetBrains Mono (subset: latin, self-hosted)
```

---

## Why TanStack Query over SWR or custom polling

The current `usePolling` hook is a manual implementation that manages failure counting, backoff, and error state. TanStack Query provides:

- Automatic stale-while-revalidate (cached data shown immediately on route return).
- Background refetch on window focus.
- Configurable retry with exponential backoff.
- Devtools for inspecting cache state.
- Mutation with optimistic updates and rollback.
- `suspense` mode for clean loading states.

This replaces `usePolling`, `SyncStateContext`, and the manual error tracking with a battle-tested, properly typed solution. The circuit breaker (offline detection after 3 failures) becomes a TanStack Query `onError` handler that sets a global `isOffline` state atom.

---

## Migration Note: MUI → shadcn/ui

Migration is not a lift-and-shift. Components are rebuilt, not ported. The approach:
1. shadcn/ui components are added to `src/components/ui/` alongside existing MUI components.
2. Pages are rebuilt one at a time. New page = new components.
3. Old MUI components are deleted as pages migrate.
4. MUI is removed from package.json when the last page migrates.

This means V2 is built in parallel with V1, not as a big-bang rewrite. See `09-migration-roadmap.md` for phasing.

---

## Package Size Impact

| Package | Current | V2 |
|---------|---------|-----|
| @mui/material | ~330KB gzipped | removed |
| @emotion/react | ~15KB | removed |
| tailwindcss | not present | ~7KB runtime |
| shadcn/ui | not present | 0KB (source owned) |
| @radix-ui/* | not present | ~40KB (used primitives only) |
| @xyflow/react | not present | ~230KB (lazy) |
| lucide-react | not present | ~2KB per icon (tree-shaken) |
| @tanstack/react-query | not present | ~15KB |
| @tanstack/react-table | not present | ~10KB |

**Net impact:** Initial bundle decreases by ~280KB (removing MUI + Emotion). Visualization adds ~230KB on demand.
