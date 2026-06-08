# 07 — Visualization Strategy

Research and recommendations for all data visualization needs in OmniSave.

---

## Visualization Requirements

| Visualization | Complexity | Interactivity | Data size |
|--------------|-----------|---------------|-----------|
| Snapshot lineage graph (DAG) | High | High (pan, zoom, click) | 5–200 nodes |
| Conflict resolution side-by-side | Low | Selection only | 2 nodes |
| Transaction timeline (state steps) | Low | None | 4–6 steps |
| Sync activity sparkline | Low | Hover tooltip | 14 data points |
| Device sync matrix | Low | None (static table) | 2–10 rows |

---

## Lineage Graph (DAG)

### Requirements

- Render a directed acyclic graph of snapshots connected by parent_sequence_num.
- Typical size: 5–50 nodes, max ~200.
- Nodes must be styled React components (not plain SVG circles) — they need state-aware styling (HEAD badge, conflict amber, etc.).
- Must support: pan, zoom, click on nodes to open detail panel.
- Must handle branch structures (conflict branches fork to the right of the canonical chain).
- Must work on touch (pinch-zoom, swipe-pan).
- Layout: top-to-bottom, newest at top. Canonical chain is the main vertical spine.

### Library Evaluation

#### React Flow

**Pros:**
- Purpose-built for node-edge graphs with React components as nodes.
- Built-in pan and zoom (`ReactFlowProvider`).
- Custom node renderers: just a React component — our `SnapshotNode` component drops in directly.
- Automatic DAG layout via `dagre` or `elk` integration.
- Excellent TypeScript support.
- Active maintenance, large community.
- MIT license.
- Touch support built-in.
- Performance: virtualized rendering for large graphs (>100 nodes).
- Minimap component available for orientation on large graphs.

**Cons:**
- Bundle size: ~230KB minified (before tree-shake). With proper code splitting this is acceptable.
- Opinionated edge rendering (but controllable via custom edge components).
- Default styling needs overriding to match design system — acceptable.

**Verdict: PRIMARY CHOICE for lineage graph.**

---

#### D3.js

**Pros:**
- Maximum flexibility.
- Excellent force-directed layouts.
- Widely understood.

**Cons:**
- Not React-native. Requires manual DOM management or a bridge layer (`useD3` hook), creating a split rendering model where React and D3 both touch the DOM — a maintenance hazard.
- No built-in node component system — all nodes are SVG shapes, requiring re-implementing our React component system in SVG.
- Pan/zoom must be implemented manually with `d3-zoom`.
- Touch support requires additional implementation.
- For a DAG with React-component nodes (which OmniSave needs), D3 is significantly more complex than React Flow with no proportional benefit.

**Verdict: NOT RECOMMENDED for lineage graph. Better suited for purely SVG visualizations (sparklines, activity charts).**

---

#### VisX (Airbnb)

**Pros:**
- Lower-level than React Flow. Composable SVG primitives.
- Good TypeScript support.
- Tree-shakeable.

**Cons:**
- No built-in pan/zoom for graphs.
- No custom HTML-node support (nodes are SVG only).
- Better suited for charts (bar, line, area) than interactive node-edge graphs.
- Less opinionated = more work for our use case.

**Verdict: NOT RECOMMENDED for lineage graph. Excellent for chart visualizations (sparklines, activity bars).**

---

#### Cytoscape.js

**Pros:**
- Mature graph library with excellent layout algorithms.
- Handles very large graphs (1000+ nodes).
- Rich interaction model.

**Cons:**
- Not React-native. Uses its own DOM rendering (canvas/SVG).
- Custom React components as nodes requires complex adapter code.
- API is not TypeScript-first.
- Large bundle: ~500KB.
- Visual style is defined in a CSS-like JSON format, not actual CSS custom properties.
- Overkill for our graph sizes (<200 nodes).

**Verdict: NOT RECOMMENDED. Only justified for graphs with >500 nodes where React Flow performance degrades.**

---

#### elkjs

**Pros:**
- Purely a layout algorithm, not a renderer.
- Excellent for DAG layout (Layered algorithm is ideal for lineage graphs).
- Can be used as a layout engine behind React Flow.

**Verdict: USE as React Flow's layout engine (via `@xyflow/react` + `elkjs` integration). Not a visualization library itself.**

---

### Lineage Graph Implementation Plan

**Stack:** React Flow (`@xyflow/react`) + ELK layout (`elkjs`)

**Architecture:**
```
LineageGraph component
├── useLineageLayout hook — transforms snapshot data into React Flow nodes/edges
│   └── Calls ELK layout algorithm (Layered, TOP_TO_BOTTOM direction)
├── ReactFlow — renders pan/zoom canvas
│   ├── SnapshotNode (custom node) — our component
│   └── LineageEdge (custom edge) — styled connector lines
└── SnapshotDetailPanel — slides in on node click
```

**Node positioning:**
- ELK Layered algorithm produces clean DAG layouts.
- `rankdir: 'TB'` (top to bottom).
- Conflict branches are automatically placed to the right of the canonical chain by ELK.

**Performance:**
- React Flow virtualizes nodes outside the viewport.
- For <50 nodes (typical): no performance concern.
- For 50–200 nodes: enable `nodesDraggable={false}` and `nodesConnectable={false}` to reduce overhead.

**Minimap:** Include `MiniMap` component (React Flow built-in) for graphs with >20 nodes.

---

## Transaction Timeline (State Steps)

### Requirements

- Show 4–6 state steps in order: Upload → Processing → Ready → Delivered.
- Each step: label, timestamp, status (pending/active/complete/failed).
- Static (no interactivity).
- No library needed — pure CSS/SVG.

### Implementation

Plain React component using CSS flexbox/grid. No library.

```
● ─── ● ─── ◌ ─── ◌
│     │
Upload  Processing  Ready    Delivered
2h ago  2h ago      —        —
```

Step states:
- Complete: filled green circle
- Active: filled accent circle with spinner
- Pending: open circle, grey
- Failed: X circle, red

---

## Sync Activity Sparkline

### Requirements

- 14 data points (events per day).
- 120px × 32px display.
- No axes. Tooltip on hover.
- No library — native SVG is appropriate.

### Implementation

Custom SVG component using VisX `@visx/shape` Bar or plain SVG rects. Minimal implementation:

```tsx
// 14 bars, each (8px wide, variable height, 2px gap)
// Max height 28px (with 4px padding)
// Color: --color-accent at 60% opacity, hover: 100%
// Tooltip on bar hover: "N events on May 28"
```

Alternative: purely CSS with flexbox + `height` set from data. No library at all.

**Verdict: Native SVG with no library. Total implementation: ~60 lines.**

---

## Conflict Resolution Side-by-Side

### Requirements

- Show two snapshot "cards" side-by-side.
- Selection interaction (click to choose).
- No graph rendering needed.
- Pure React + CSS.

### Implementation

Two `SnapshotCard` components in a CSS Grid layout. No visualization library.

```
grid-template-columns: 1fr 1fr (desktop)
grid-template-columns: 1fr (mobile, stacked)
```

Selected card gets: accent border, scale(1.02), checkmark in top-right corner.

---

## Device Sync Matrix

### Requirements

- Tabular data: 2–10 rows, 4 columns.
- No visualization — it's a table.
- No library.

### Implementation

HTML `<table>` styled with design tokens. `DeviceSyncMatrix` component.

---

## Library Recommendations Summary

| Use case | Library | Bundle cost |
|----------|---------|------------|
| Lineage DAG graph | `@xyflow/react` + `elkjs` | ~280KB (lazy loaded) |
| Activity sparklines | Native SVG (no library) | 0KB |
| Transaction timeline | Native React (no library) | 0KB |
| Conflict side-by-side | Native React (no library) | 0KB |
| Device sync matrix | Native HTML table (no library) | 0KB |

**Total visualization library cost: ~280KB, lazy-loaded on `/library/:game/history` route only.**

The lineage graph should be loaded on demand via dynamic import (`React.lazy`) since it is only needed on the History sub-page. It must not be part of the initial bundle.

---

## React Flow Integration Notes

### Version

Use `@xyflow/react` (v12+, the React-specific package, successor to `reactflow`). Not the legacy `reactflow` package.

### License

React Flow is MIT. The paid features (background customization, additional controls) are in `@xyflow/react` Pro. We only need the base package.

### Custom node type

```tsx
// Registered as a custom node type
const nodeTypes = {
  snapshot: SnapshotNode,
};
```

`SnapshotNode` receives: `data.snapshot` (our Snapshot type), `data.isHead`, `data.isConflict`. It renders using our design system tokens (not React Flow defaults).

### Edge styling

Custom edges using SVG path. Color:
- Canonical chain: `--color-border-strong`
- Conflict branch: `--color-warning-border`
- Edge width: 1.5px

### Fit view on load

```tsx
<ReactFlow onInit={(instance) => instance.fitView({ padding: 0.2 })} />
```

### Accessibility caveat

React Flow graph is not screen-reader accessible (SVG canvas). Provide an accessible summary table fallback below the graph: "12 snapshots — most recent: #42 on Switch OLED, 3h ago."
