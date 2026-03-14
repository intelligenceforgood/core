# Accessibility Audit — TIFAP Sprint 6

**Date:** Sprint 6 Final
**Scope:** Keyboard navigation, screen reader support, color contrast on TIFAP pages

## Pages Audited

| Page                     | Keyboard Nav | Screen Reader | Color Contrast | Status |
| ------------------------ | ------------ | ------------- | -------------- | ------ |
| Impact Dashboard         | Pass         | Pass          | Pass           | OK     |
| Impact Taxonomy          | Pass         | Pass          | Pass           | OK     |
| Impact Geography         | Pass         | Pass          | Pass           | OK     |
| Entity Explorer          | Pass         | Pass          | Pass           | OK     |
| Indicator Registry       | Pass         | Pass          | Pass           | OK     |
| Network Graph            | Partial      | Partial       | Pass           | Note 1 |
| Campaign List            | Pass         | Pass          | Pass           | OK     |
| Campaign Detail          | Pass         | Pass          | Pass           | OK     |
| Report Builder           | Pass         | Pass          | Pass           | OK     |
| Report Library           | Pass         | Pass          | Pass           | OK     |
| Campaign Alerts (mobile) | Pass         | Pass          | Pass           | OK     |

## Notes

1. **Network Graph (Partial):** Force-directed graph visualization is inherently challenging for screen readers. The graph data is available in tabular form via the entity/indicator list views. Graph nodes are not individually focusable via keyboard — this is a known limitation of canvas/SVG-based graph renderers.

## Tailwind CSS Approach

- All pages use semantic HTML (`<header>`, `<nav>`, `<main>`, `<section>`, `<article>`)
- Interactive elements use native `<button>` and `<a>` tags (keyboard-focusable by default)
- Color contrast ratios meet WCAG AA (4.5:1 for text, 3:1 for large text) using slate/sky color palette
- Badge components use `variant` prop which maps to accessible color combinations
- Mobile navigation uses `aria-label` on hamburger toggle, `role="navigation"` on sidebar
- Charts use Recharts `<Tooltip>` which renders in DOM (screen reader accessible)

## Recommendations

1. Add `aria-label` attributes to KPI cards for screen reader context
2. Add a "Skip to main content" link for keyboard users
3. Consider tabular alternative view toggle for Network Graph page
