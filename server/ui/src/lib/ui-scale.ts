// Mirror of CSS --ui-scale for Lucide `size` props (integers, can't read CSS vars).
// Change UI_SCALE here + --ui-scale in tokens.css together when testing density presets.
export const UI_SCALE = 1.25

const s = (base: number): number => Math.round(base * UI_SCALE)

export const ICON_XS   = s(10)  // 12 — switch thumb spinner
export const ICON_TINY  = s(12)  // 15 — chevrons, breadcrumb separators
export const ICON_SM   = s(13)  // 16 — small inline action icons (upload/download/trash)
export const ICON_BASE = s(16)  // 20 — standard content icons (external-link, alert)
export const ICON_NAV  = s(18)  // 22 — nav icons, close X, bell
export const ICON_MD   = s(20)  // 25 — bottom nav icons
export const ICON_LG   = s(28)  // 35 — empty state icons
