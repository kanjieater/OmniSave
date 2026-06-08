# 03 — Design System

All values are defined as CSS custom properties. No arbitrary values permitted in component code. Every spacing, color, radius, shadow, or timing value must reference a token.

---

## Token Naming Convention

```
--{category}-{subcategory}-{variant}

Examples:
--color-bg-base
--color-text-primary
--space-4
--radius-md
--shadow-overlay
--motion-duration-fast
--font-size-sm
--font-weight-semibold
```

Tokens are defined in a single `:root` block in `tokens.css`. Components import via CSS custom properties only — never hardcode hex, px, or ms values.

---

## Color Tokens

```css
:root {
  /* === BACKGROUNDS === */
  --color-bg-base:         #0C0D10;
  --color-bg-subtle:       #111318;
  --color-bg-elevated:     #191C23;
  --color-bg-overlay:      #1F2330;
  --color-bg-hover:        #242838;
  --color-bg-selected:     #1E2540;
  --color-bg-input:        #0F1115;

  /* === BORDERS === */
  --color-border-subtle:   #1E2028;
  --color-border-base:     #2A2D38;
  --color-border-strong:   #3D4255;
  --color-border-focus:    #3B82F6;
  --color-border-error:    #991B1B;

  /* === TEXT === */
  --color-text-primary:    #E8EAF0;
  --color-text-secondary:  #9198AC;
  --color-text-muted:      #585E72;
  --color-text-disabled:   #3A3F52;
  --color-text-inverse:    #0C0D10;
  --color-text-link:       #60A5FA;
  --color-text-code:       #A5B4FC;

  /* === ACCENT (blue-teal) === */
  --color-accent:          #3B82F6;
  --color-accent-hover:    #2563EB;
  --color-accent-subtle:   #1E3A5F;
  --color-accent-muted:    rgba(59, 130, 246, 0.15);

  /* === SEMANTIC: SUCCESS === */
  --color-success:         #22C55E;
  --color-success-subtle:  #0F2A1A;
  --color-success-border:  #166534;
  --color-success-text:    #4ADE80;

  /* === SEMANTIC: WARNING === */
  --color-warning:         #EAB308;
  --color-warning-subtle:  #2A1F06;
  --color-warning-border:  #854D0E;
  --color-warning-text:    #FCD34D;

  /* === SEMANTIC: ERROR === */
  --color-error:           #EF4444;
  --color-error-subtle:    #2A0A0A;
  --color-error-border:    #991B1B;
  --color-error-text:      #FCA5A5;

  /* === SEMANTIC: INFO === */
  --color-info:            #60A5FA;
  --color-info-subtle:     #0F1F35;
  --color-info-border:     #1D4ED8;
  --color-info-text:       #93C5FD;

  /* === SEMANTIC: NEUTRAL === */
  --color-neutral:         #6B7280;
  --color-neutral-subtle:  #1A1C22;
  --color-neutral-border:  #374151;
  --color-neutral-text:    #9CA3AF;
}
```

---

## Typography Tokens

```css
:root {
  /* === FONT FAMILIES === */
  --font-sans:  'Inter', system-ui, -apple-system, sans-serif;
  --font-mono:  'JetBrains Mono', 'Cascadia Code', 'Fira Code', ui-monospace, monospace;

  /* === FONT SIZES === */
  --font-size-xs:    0.6875rem;   /* 11px */
  --font-size-sm:    0.8125rem;   /* 13px */
  --font-size-base:  0.9375rem;   /* 15px */
  --font-size-md:    1.0625rem;   /* 17px */
  --font-size-lg:    1.25rem;     /* 20px */
  --font-size-xl:    1.5rem;      /* 24px */
  --font-size-2xl:   2rem;        /* 32px */

  /* === FONT WEIGHTS === */
  --font-weight-normal:    400;
  --font-weight-medium:    500;
  --font-weight-semibold:  600;
  --font-weight-bold:      700;

  /* === LINE HEIGHTS === */
  --line-height-tight:   1.0;
  --line-height-snug:    1.25;
  --line-height-normal:  1.4;
  --line-height-relaxed: 1.6;

  /* === LETTER SPACING === */
  --tracking-tight:   -0.01em;
  --tracking-normal:   0em;
  --tracking-wide:     0.04em;
  --tracking-widest:   0.08em;   /* uppercase labels */
}
```

---

## Spacing Tokens

4px base unit. All spacing is a multiple of 4.

```css
:root {
  --space-0:   0px;
  --space-1:   4px;
  --space-2:   8px;
  --space-3:   12px;
  --space-4:   16px;
  --space-5:   20px;
  --space-6:   24px;
  --space-8:   32px;
  --space-10:  40px;
  --space-12:  48px;
  --space-16:  64px;
  --space-20:  80px;
  --space-24:  96px;
}
```

**Usage rules:**
- Component internal padding: `--space-3` to `--space-4`
- Between related items: `--space-2`
- Between sections: `--space-6` to `--space-8`
- Page padding (horizontal): `--space-6` on desktop, `--space-4` on tablet, `--space-3` on mobile
- Never use `--space-0` for visual spacing — only for resets

---

## Radius Tokens

```css
:root {
  --radius-none:  0px;
  --radius-sm:    3px;    /* inputs, badges, code spans */
  --radius-md:    6px;    /* cards, panels, buttons */
  --radius-lg:    10px;   /* modals, command palette */
  --radius-xl:    16px;   /* reserved for illustration/decorative */
  --radius-full:  9999px; /* pills, avatar indicators */
}
```

**Component→radius mapping:**
- Navigation items: `--radius-sm`
- Buttons: `--radius-md`
- Cards, panels: `--radius-md`
- Input fields: `--radius-sm`
- Status badges/chips: `--radius-full`
- Modals: `--radius-lg`
- Tooltips: `--radius-sm`

---

## Shadow Tokens

```css
:root {
  /* Subtle — used at Level 1 surfaces only */
  --shadow-none:    none;
  --shadow-xs:      0 1px 2px rgba(0, 0, 0, 0.3);
  --shadow-sm:      0 1px 4px rgba(0, 0, 0, 0.4);

  /* Overlay — used at Level 3+ (popovers, dropdowns) */
  --shadow-md:      0 4px 16px rgba(0, 0, 0, 0.5);

  /* Modal — used at Level 4 */
  --shadow-lg:      0 8px 32px rgba(0, 0, 0, 0.6);

  /* Inner highlight — simulates top-edge light catch */
  --shadow-inner-highlight: inset 0 1px 0 rgba(255, 255, 255, 0.04);

  /* Focus ring — accent-colored outline */
  --shadow-focus:   0 0 0 2px var(--color-accent-muted);
}
```

**Rules:**
- Never use `--shadow-md` or `--shadow-lg` at Level 1 surfaces.
- Always pair elevated surfaces with `--shadow-inner-highlight`.
- Focus rings always use `--shadow-focus` (never custom outline colors).

---

## Border Tokens

```css
:root {
  --border-subtle:  1px solid var(--color-border-subtle);
  --border-base:    1px solid var(--color-border-base);
  --border-strong:  1px solid var(--color-border-strong);
  --border-focus:   1px solid var(--color-border-focus);
  --border-error:   1px solid var(--color-border-error);
  --border-none:    none;
}
```

---

## Motion Tokens

```css
:root {
  /* === DURATIONS === */
  --motion-duration-instant:  0ms;
  --motion-duration-fast:     80ms;
  --motion-duration-normal:   150ms;
  --motion-duration-slow:     200ms;
  --motion-duration-slower:   300ms;

  /* === EASING === */
  --motion-ease-linear:     linear;
  --motion-ease-out:        cubic-bezier(0, 0, 0.2, 1);
  --motion-ease-in:         cubic-bezier(0.4, 0, 1, 1);
  --motion-ease-in-out:     cubic-bezier(0.4, 0, 0.2, 1);
  --motion-ease-spring:     cubic-bezier(0.34, 1.56, 0.64, 1);
}

/* Reduced motion override — collapse all animations */
@media (prefers-reduced-motion: reduce) {
  :root {
    --motion-duration-fast:    0ms;
    --motion-duration-normal:  0ms;
    --motion-duration-slow:    0ms;
    --motion-duration-slower:  0ms;
  }
}
```

**Token → interaction mapping:**
- Row hover background: `--motion-duration-fast` + `--motion-ease-linear`
- Status badge change: `--motion-duration-fast` + `--motion-ease-linear`
- Modal appear: `--motion-duration-slow` + `--motion-ease-out`
- Panel slide: `--motion-duration-slow` + `--motion-ease-in-out`
- Page fade: `--motion-duration-normal` + `--motion-ease-out`
- Spring (notification, command palette): `--motion-ease-spring` + `--motion-duration-slow`

---

## Icon System

**Library:** Lucide Icons (MIT, tree-shakeable, consistent 24px grid, 2px stroke)

**Size scale:**
```
--icon-xs:  12px   /* inline metadata icons */
--icon-sm:  14px   /* button icons, status dots */
--icon-md:  16px   /* navigation, table actions */
--icon-lg:  20px   /* page section icons */
--icon-xl:  24px   /* empty state, modal headers */
--icon-2xl: 32px   /* illustration-weight icons */
```

**Color rules:**
- Default: `--color-text-secondary`
- Interactive (hover): `--color-text-primary`
- Active / selected: `--color-accent`
- Error state: `--color-error`
- Success state: `--color-success`
- Disabled: `--color-text-disabled`

**Icon set used (OmniSave-specific):**
```
Navigation:    LayoutDashboard, Monitor, Activity, Settings
Actions:       Upload, Download, RefreshCw, Trash2, Edit2, Copy, ExternalLink
Status:        CheckCircle2, AlertTriangle, XCircle, Clock, Loader2
Snapshot:      GitCommit, GitBranch, GitMerge, History
Device:        Gamepad2, Monitor, Laptop, Smartphone
Conflict:      GitFork, AlertOctagon
Network:       Wifi, WifiOff, Server
Auth:          Lock, Key, Eye, EyeOff
Misc:          ChevronRight, ChevronDown, X, Search, Bell, BellDot
```

---

## Z-Index Scale

```css
:root {
  --z-base:         0;
  --z-raised:       10;    /* sticky headers */
  --z-dropdown:     100;   /* dropdowns, popovers */
  --z-sticky:       200;   /* sidebar, fixed nav */
  --z-overlay:      300;   /* backdrop for modals */
  --z-modal:        400;   /* modal dialog */
  --z-notification: 500;   /* toast, notification drawer */
  --z-tooltip:      600;   /* tooltips (always on top) */
}
```

---

## Breakpoints

```css
:root {
  --bp-sm:   640px;    /* mobile landscape / small tablet */
  --bp-md:   768px;    /* tablet portrait */
  --bp-lg:   1024px;   /* tablet landscape / small desktop */
  --bp-xl:   1280px;   /* standard desktop */
  --bp-2xl:  1536px;   /* wide desktop */
}
```

**Design targets by breakpoint:**
- `< 640px`: Mobile. Single column. Bottom navigation. Full-width panels.
- `640–1024px`: Tablet. Collapsible sidebar. Two-column layouts where appropriate.
- `> 1024px`: Desktop. Fixed sidebar. Dense multi-column layouts.

---

## Utility Classes (Tailwind v4 layer)

These utility classes are built on the token system via Tailwind v4's CSS-first configuration. They are the only allowed escape hatch from component-level CSS.

```
bg-base, bg-subtle, bg-elevated, bg-overlay, bg-hover, bg-selected
text-primary, text-secondary, text-muted, text-disabled
border-subtle, border-base, border-strong
font-sans, font-mono
rounded-sm, rounded-md, rounded-lg, rounded-full
shadow-xs, shadow-sm, shadow-md, shadow-focus
```

**Banned:** arbitrary values like `bg-[#ff0000]`, `p-[13px]`, `rounded-[7px]`. All such values must be extracted to a token.
