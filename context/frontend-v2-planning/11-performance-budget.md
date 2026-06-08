# 11 — Performance Budget

Concrete, measurable targets. These are gates, not aspirations — a phase is not done until the metrics pass.

---

## Measurement Environment

All measurements on:
- Simulated 4G throttle (25 Mbps down, 6 Mbps up, 40ms RTT)
- Simulated 4x CPU slowdown (DevTools Performance throttle)
- Viewport: 1280×800 desktop, 375×812 mobile
- Browser: Chromium (latest stable)
- Tool: Lighthouse CI + Chrome DevTools

Local network measurements (server on LAN):
- No throttle. Measurements are for JS execution and render performance only.

---

## Bundle Size Targets

### Initial Bundle (what loads on first visit)

| Asset | Target | Measurement |
|-------|--------|-------------|
| JavaScript (compressed) | < 150 KB | Lighthouse "Reduce JavaScript" audit |
| CSS (compressed) | < 20 KB | Lighthouse |
| HTML | < 5 KB | — |
| Fonts (Inter variable subset, latin) | < 80 KB | Network panel |
| Fonts (JetBrains Mono subset, latin) | < 30 KB | Network panel |
| Game icons (first paint) | 0 KB (lazy) | — |
| **Total initial transfer** | **< 285 KB** | |

### Lazy Bundles

| Bundle | Trigger | Target |
|--------|---------|--------|
| `@xyflow/react` + `elkjs` | History tab click | < 280 KB compressed |
| `ConflictWorkspace` | Conflict resolve click | < 10 KB |
| `SnapshotDetailPanel` | Graph node click | < 5 KB |

### Current V1 Bundle (baseline)

MUI alone contributes ~330 KB compressed. Total V1 initial bundle is estimated at ~500–600 KB.
V2 target represents a ~70% reduction.

---

## Rendering Performance Targets

### Largest Contentful Paint (LCP)

| Scenario | Target |
|----------|--------|
| Dashboard (first load, empty cache) | < 1.5s |
| Dashboard (warm cache, TanStack Query hit) | < 300ms |
| Library page navigation | < 400ms |
| Game Detail navigation | < 400ms |

### First Contentful Paint (FCP)

| Scenario | Target |
|----------|--------|
| Auth page | < 800ms |
| Dashboard (shell visible) | < 600ms |

### Total Blocking Time (TBT)

| Scenario | Target |
|----------|--------|
| Dashboard initial load | < 100ms |
| Library filter/sort interaction | < 50ms |

### Cumulative Layout Shift (CLS)

| Scenario | Target |
|----------|--------|
| Dashboard load | < 0.05 |
| Page navigation | < 0.01 |
| Image load (game icons) | < 0.05 (width/height reserved on img elements) |

---

## Interaction Latency Targets

These are measured from user input to visual response (not to API completion).

| Interaction | Target |
|-------------|--------|
| Row hover highlight | < 50ms (synchronous CSS) |
| Button click visual response | < 100ms |
| Navigation (client-side route change) | < 200ms (skeleton visible) |
| InlineEdit field focus | < 100ms |
| Toggle switch visual toggle | Immediate (optimistic, before API call) |
| Modal open | < 150ms (first paint) |
| Notification drawer slide-in | < 200ms |
| Dashboard poll (background refresh) | Silent, no visible rerender jank |
| Lineage graph initial render (20 nodes) | < 500ms |
| Lineage graph initial render (100 nodes) | < 2000ms |

---

## Mobile Performance Targets

All Lighthouse mobile scores measured at 375px, 4x CPU throttle, 4G network.

| Metric | Target |
|--------|--------|
| Performance score | > 85 |
| Accessibility score | > 95 |
| LCP | < 2.5s |
| TBT | < 200ms |
| CLS | < 0.1 |

**Touch interaction targets:**
- Minimum touch target size: 44×44px (all buttons, toggles, row actions)
- Tap response (visual feedback): < 100ms
- Scroll frame rate: 60fps (no jank during DataTable scrolling)

---

## API Response Expectations

These are not frontend targets — they document what the frontend assumes from the API. If the API is slower, the frontend shows skeleton states; these targets do not change.

| Endpoint | Expected p95 |
|----------|-------------|
| GET /dashboard | < 100ms |
| GET /library | < 100ms |
| GET /games/:id | < 50ms |
| GET /devices | < 50ms |
| GET /activity | < 100ms |
| POST /snapshots/:id/push | < 500ms |
| POST /errors/:id/acknowledge | < 50ms |

---

## Polling Performance Contract

TanStack Query manages polling. These are the refetch intervals and their network cost:

| Query | Interval | Payload estimate |
|-------|----------|-----------------|
| Dashboard | 15s | < 5 KB JSON |
| Activity | 30s | < 10 KB JSON (200 events) |
| Errors (background) | 30s | < 2 KB JSON |
| Game detail (on screen) | 0 (on-demand) | — |
| Devices | 0 (on-demand) | — |

Network cost of all polling combined: ~(5 + 10 + 2) KB / 30s ≈ 570 B/s. Negligible on home LAN.

---

## Font Loading Strategy

1. **Self-host** Inter and JetBrains Mono via `@fontsource` npm packages.
2. **Subset** to latin characters only (reduces Inter variable from ~200KB to ~80KB).
3. **Preload** the primary Inter wax weight (400–600) in `<head>`.
4. **`font-display: swap`** to prevent invisible text during load.
5. **No FOUT** for monospace: JetBrains Mono is only used for code/ID displays — system monospace fallback is visually acceptable and prevents CLS.

---

## Image Loading Strategy

Game icons (from RomM):
1. `<img width="48" height="48">` — always set explicit dimensions to reserve layout space (prevents CLS).
2. `loading="lazy"` — only load visible viewport icons.
3. Fallback: if icon URL returns 404 or times out, render `Gamepad2` icon from lucide-react instead.
4. Cache: browser caches RomM icon URLs naturally. No additional caching needed.

---

## Code Splitting Strategy

```
chunk: main (dashboard, library, devices, settings) — target: < 120 KB JS
chunk: game-history (lineage graph) — target: < 280 KB JS, lazy
chunk: icons (lucide-react subset) — tree-shaken, included in main

// Dynamic imports:
const LineageGraph = React.lazy(() => import('./components/game/LineageGraph'));
const ConflictWorkspace = React.lazy(() => import('./components/game/ConflictWorkspace'));
```

Vite automatically chunks `node_modules` into a vendor chunk. The vendor chunk should not include `@xyflow/react` (lazy). Verify with `vite-bundle-visualizer` after Phase 5.

---

## Performance Monitoring

Track these metrics over time using Lighthouse CI in the build pipeline:
- LCP, FCP, TBT, CLS on dashboard route.
- Total JS bundle size.
- Alert if any metric regresses by more than 10%.
