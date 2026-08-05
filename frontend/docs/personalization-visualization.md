# Personalization visualization decision

The dashboard uses existing Vuetify primitives, semantic HTML tables, and one inline SVG trend chart. No chart dependency was added.

Decision evidence:

- Bundle maintenance: `package.json` has no new runtime or build dependency; the production build completes with the existing Vite/Vuetify toolchain.
- Accessibility: the trend SVG has a title and description, and the same values are rendered in a keyboard-readable table. The estimate/actual distinction uses labels and hatch pattern in addition to color.
- License: no third-party chart code or license was introduced.
- Maintenance: the chart is a bounded two-series, ten-point view with no interaction-specific state, so native SVG has lower maintenance surface than a new chart abstraction.
- Responsive behavior: the table remains horizontally scrollable and the chart has an explicit compact fallback on narrow screens; empty and sparse states are text-first.

Re-evaluate this decision if the dashboard requires more than two series, zooming, brushing, annotations, or 100+ points.
