# OCLAST interface conventions

Use a familiar desktop analysis workspace: saved projects on the left, an
unobstructed field viewer in the center, and measurements on the right. Both
panels collapse. Warm neutral surfaces, a charcoal image canvas, and one muted
burgundy accent give microscopy data priority. Color in the microscopy image
must not compete with decorative interface gradients.

The connected segmented-control treatment and outline/ghost/primary button
variants follow the public 21st.dev shadcn examples:

- https://21st.dev/@shadcn/components/toggle-group/toggle-group-with-text
- https://21st.dev/@shadcn/components/button
- https://21st.dev/@shadcn/components/input/grouped-with-button

These are design-pattern adaptations, not a claim that the full 21st.dev registry
or Radix library is installed. The local primitives in `src/components/ui.jsx`
implement the same conventional visual structure with native React/HTML controls,
including radio-group arrow/Home/End navigation. No account, external font,
remote component script, or runtime component CDN is required. Lucide icons are
bundled from the existing dependency. Retain an accessible name for icon-only
controls, visible focus rings, reduced-motion support, and concise status text.

## Hierarchy

- Header: application identity, local execution status, open-image action.
- Project cards: source name, dimensions, and concise saved/job status.
- Analysis heading: active source, storage footprint, analysis/save actions.
- Four compact metric cards: count, mean area, mean circularity, analysis time.
- Layer segmented control: original, counted objects, foreground probability.
- Viewer toolbar: zoom, actual image fit, 1:1, and review actions.
- Inspector: exports, morphology distributions, selection, searchable object list.

Use bundled fonts with system fallbacks so the packaged application stays useful offline. Selection
and analysis status need text or shape cues in addition to color.

The refined visual direction follows the user's supplied rounded dashboard
references: a soft rounded application shell, pill controls, pastel summary
cards and small circular graphics. Outfit is bundled from Google Fonts under
the SIL Open Font License (`public/fonts/OFL-Outfit.txt`); it provides geometric,
circular typography offline without assuming a Euclid Circular licence. The
cell-inspired mark and metric illustrations are original SVGs. Circularity's
ring uses the measured value; other metric glyphs are decorative, not data charts.
