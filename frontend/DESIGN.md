# OCLAST interface conventions

OCLAST is an offline, image-level osteoclast mask-review workspace for local lab users. This surface is Operate: find an image, run inference, inspect masks, correct detections, and export measurements. Do not introduce experiment, treatment, well-size, calibration, or biological-classification assumptions.

## Identity and tokens

Preserve the user's rounded dashboard references: Outfit geometric circular type, pill controls, pastel measurement cards, original cell mark and circular metric graphics. Outfit is bundled under SIL OFL (`public/fonts/OFL-Outfit.txt`); no Euclid Circular licence is assumed. Circularity's ring encodes the measured value; other glyphs are decorative and hidden from assistive technology.

`src/workspace.css` owns the workspace theme. Ground #eeedf1, surface white, ink #302b37, secondary ink #665d6e, accent #825493, edge #e6e0eb. Measurement fills: mint #edf7f2, pink #f9edf6, sand #f9f5e9, lilac #f0ecf9. Charcoal #302f35 reserves visual space for microscopy. Dark primary actions; quiet borders; shadows only on floating menus. Use tabular numerals for measurements. Secondary text stays readable; 11px is reserved for compact metadata and axes, with 12–14px controls/body and 18–25px headings/values.

## Workspace hierarchy

- Header: OCLAST and paper-repository link, actual runtime device, keyboard help, Open image.
- Left: saved images, dimensions/status/count, optional search once there are more than three projects. No storage-path disclosure is shown.
- Center: active image, saved/undo/export controls, four compact image summaries, display-layer pills, viewer.
- Right: Measurements/Tiles pills. Selected cell area and circularity appear first, using the same pink/sand cards. No position or detection-origin prose.
- Measurements: compact KDEs with explicit focused/full range and outside-view count; searchable measurement table with scoped sticky headers.
- Explore objects: cell gallery first, optional Plot view, shared selection presets. Statistics and explanatory copy use disclosures. Keep actual thumbnails and mask toggles accessible without traversing plot controls.
- Tiles: continuous vertical library, lazy images, original and mask overlay; pressed state is programmatically exposed.
- Exports are grouped next to the active image, not buried beneath inspector charts.

Both desktop panels collapse, with Focus image as a quick route. Below 1050px, switch between Images, Viewer and Inspect as full-width panes rather than overlapping drawers. Below 600px, primary controls and mask/range controls have 44px minimum touch height. Keep selected details visible before scrollable content; galleries/tables own their scroll area and must retain meaningful minimum height.

The image viewer is a named, focusable region. Arrows pan (Shift for larger steps), +/− zoom, F/0 fit, 1 native pixels, Enter inspects the center. Drawing uses Enter to add a vertex, Backspace to undo one, Ctrl+Enter to save, Escape to cancel. Drafts survive sidebar resizing. Pointer and keyboard paths share operations. Visible focus, status announcements, disabled/loading/error/empty states and reduced-motion support are required.

## Reference provenance

The design-taste app direction is framed-sheet, seed 1088387651, retaining the existing palette and type. The user's pastel cards, circular graphics and rounded shell are explicit brief choices. They are retained without copying marketing-page decoration into the work surface.

Workflow inspiration comes from official [Benchling Analysis](https://help.benchling.com/hc/en-us/articles/36096516002317-Analyze-data-with-Benchling-Analysis) and [QuPath viewing guidance](https://qupath.readthedocs.io/en/stable/docs/starting/viewing.html): clear active context, image-first review, linked objects and measurements. No experimental features or external assets were copied.

Spacing, neutral surfaces and consistent controls were informed by Airtable and Linear references in [VoltAgent Awesome DESIGN.md](https://github.com/voltagent/awesome-design-md), snapshot 3b605329240ce735b510037cca322f1831fdd7f8. Those are third-party observations, not official brand specifications. OCLAST keeps its own identity and assets.

The controls in `src/components/ui.jsx` adapt the retrieved [21st.dev shadcn Toggle Group](https://21st.dev/@shadcn/components/toggle-group) (demo 253) and official [shadcn Button](https://ui.shadcn.com/docs/components/button). The actual Radix Toggle Group and Slot primitives are bundled, with class-variance-authority for button variants and clsx for class composition. The source is adapted to JavaScript and OCLAST's existing CSS tokens rather than applying a replacement theme. Single-value mode groups activate with keyboard focus, including arrow/Home/End navigation; re-clicking an active mode retains it. Cells/Plot uses the same primitive as display layers and inspector modes.

Alignment: pane headers share a 64px desktop height; controls use a 36px desktop rhythm and 44px phone rhythm. Icons use 16px dimensions and do not shrink. Inspector headings, selected cards, explorer, distribution plots and table columns share a 16px inset. The summary labels occupy consistent line heights and the timing card avoids repeating GPU text already visible in the application header. Descriptive plot captions remain concise so adjacent plots align.

Lucide and Outfit remain bundled. No account, external font, remote script, runtime registry or CDN is required. The application is not a full shadcn scaffold: components.json and a wholesale theme migration are unnecessary for these adapted primitives.
