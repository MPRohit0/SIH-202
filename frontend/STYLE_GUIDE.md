# Frontend style guide (as built)

This describes the frontend **as it exists today**: a "Sentriq"-branded **UI shell**. Every
screen, component and style below is unchanged from the original prototype; only its data
source changed (see `README.md` and `API_USAGE.md`). Nothing here is a proposal. All values
were read from the source, and file references are relative to `frontend/`.

> **Heads-up on line numbers.** Most source files are minified: whole components sit on
> one physical line. `app/globals.css` is 27 lines long but 77 KB. A reference like
> `globals.css:11` points to a very long line. Search for the selector named next to it.

---

## 1. Styling approach

| Aspect | What is used |
|---|---|
| Framework | **Plain Vite 8 + React 19 SPA** (`vite.config.ts`, `index.html`, `src/main.tsx`). No Next.js, no vinext, no Cloudflare Workers plugin — those were removed; see `../docs/progress.md`. |
| Main styling method | **One global stylesheet**, `app/globals.css`, with hand-written BEM-ish class names (`.s-panel`, `.s-btn.primary`, `.map-stage`, …). Almost every colour is a literal hex value in that file (506 distinct values). |
| Tailwind | Tailwind CSS v4 is loaded (`@import "tailwindcss"`, `postcss.config.mjs`) and a `@theme inline` block maps shadcn tokens. It is used **only inside `components/ui/*`** (shadcn). App code uses no utility classes except `hidden` (buttons that stay on screen but are disabled use the `disabled` attribute, not this class). |
| Component library | **shadcn/ui, "new-york" style** (`components.json`), built on Radix. The vendored base CSS is `vendor/shadcn-tailwind-4.13.0.css`, and `tw-animate-css` is also imported. |
| How shadcn is themed | Through `[data-slot=…]` attribute selectors in `globals.css` (e.g. `[data-slot=tabs-trigger][data-state=active]`, `[data-slot=slider-thumb]`, `[data-slot=table-cell]`), plus `!important` overrides (`.s-nav`, `.s-select`). |
| Inline styles | Used only for dynamic positions: map pins and labels as `left/top %`, the pan/zoom `transform`, the swipe `clipPath`, and matrix-node positions. |
| Canvas / WebGL colours | Hard-coded in TSX: `terrain-map.tsx`, `terrain-3d.tsx`, `terrain-canvas.tsx`, `sph-lab.tsx` (see §2.6). |
| CSS modules / CSS-in-JS | None. |
| Theme | **Dark only.** There is no light mode and no theme toggle. `next-themes` is installed but unused. Toasts use `<Toaster theme="dark">`. |
| Icons | `lucide-react`. Stroke icons, usually sized 13–17 px inline and 21–29 px for section icons. |

### How the stylesheet cascades (important when editing)
`globals.css` was built up in patch layers, and **later rules override earlier ones**:

| Line | Layer |
|---|---|
| 1–3 | imports (tailwind, tw-animate, shadcn vendor) |
| 4 | `:root` **light** shadcn tokens. **Dead:** every one is overridden by line 6. |
| 5 | `@theme inline` mapping tokens to Tailwind (`--font-sans: Arial,Helvetica,sans-serif`) |
| 6 | `:root` **dark** tokens (the effective ones) + custom `--cyan`, `--quiet`, `--line` |
| 7 | base elements, typography helpers, buttons, badges, fields |
| 9 | `/* Public experience */` landing page |
| 11 | `/* Command centre */` workspace |
| 12 | 2D map. It first sets **light** map chrome (`#f7fbf1`, `#f8fbf5`), then a dark re-skin overrides it later on the same line. |
| 13–15, 17 | responsive media queries |
| 20–23 | `/* Readable presentation and workspace type scale. */` bumps most font sizes up. **These are the effective sizes.** |
| 25–27 | `/* SIH modelling architecture and scientific-boundary views */` (rem-based, uses CSS vars) |

When you look up a value, take the **last** matching rule for your viewport.

---

## 2. Colour palette (exact values)

### 2.1 Design tokens (effective `:root`, `globals.css:6`)

| Token | Value | Token | Value |
|---|---|---|---|
| `--background` | `#07121d` | `--foreground` | `#e4edf2` |
| `--card` | `#0d1c2a` | `--card-foreground` | `#e4edf2` |
| `--popover` | `#112333` | `--popover-foreground` | `#e4edf2` |
| `--primary` | `#70e2d1` | `--primary-foreground` | `#062421` |
| `--secondary` | `#172c3c` | `--secondary-foreground` | `#c2d5df` |
| `--muted` | `#152938` | `--muted-foreground` | `#849baa` |
| `--accent` | `#183344` | `--accent-foreground` | `#82e8d7` |
| `--destructive` | `#f28e8e` | `--border` | `#233747` |
| `--input` | `#263e50` | `--ring` | `#6ee2d1` |
| `--sidebar` | `#091722` | `--sidebar-foreground` | `#8ca3b3` |
| `--sidebar-primary` | `#70e2d1` | `--sidebar-primary-foreground` | `#082a26` |
| `--sidebar-accent` | `#123330` | `--sidebar-accent-foreground` | `#7ae6d5` |
| `--sidebar-border` | `#1d303e` | `--sidebar-ring` | `#70e2d1` |
| `--cyan` | `#78e6d6` | `--quiet` | `#8ba2b2` |
| `--line` | `#203443` | `--panel` | **used but never defined** (see issues) |
| `--radius` | `.65rem` | | |

The custom app CSS mostly **ignores these tokens** and repeats literal hex values. The tables
below list the literals that actually render.

### 2.2 Surfaces (darkest → lightest)

| Role | Value | Where |
|---|---|---|
| Page background | `#07121d` | `body`, `.landing` (plus radial `#10273355` glow at 76% 8%) |
| Input fill | `#081925` / `#091a28` (select) | `.num-input`, `.s-select` |
| Tabs list | `#081725` | `[data-slot=tabs-list]` |
| Map stage | `#081b28` | `.map-stage` |
| Sidebar | `#091722` | `.sentriq-sidebar [data-slot=sidebar-inner]` |
| Top bar | `#0a1824` | `.command-top` |
| Export option | `#0a1d29` | `.export-options button` |
| Panel / card | `#0c1d2b` | `.s-panel` |
| Map stage header | `#0c202d` | `.map-stage-top` |
| Dialog | `#0c1f2e` | `.s-dialog` |
| Inspector / strip | `#0d1e2c` | `.scenario-inspector`, `.command-strip` |
| Legacy panel (SPH lab) | `#0d202d` | `.panel` |
| Metric strip | `#0d2431ee` | `.map-metrics` |
| Ghost button | `#102332` (hover `#1a3444`) | `.s-btn.ghost`, `.btn.secondary` |
| 2D map canvas | `#102533` | `.terrain-map` (final override) |
| Active tab | `#1d3a49` | `[data-slot=tabs-trigger][data-state=active]` |
| Active nav item | `#12342f` | `.s-nav[data-active=true]` |
| Table row hover | `#15303d40` | `[data-slot=table-row]:hover` |

### 2.3 Borders
`#203949` (panel), `#284250` (inspector), `#29404f` (strip), `#294351` (map stage),
`#2a4253` (ghost button), `#2a4657` (dialog), `#284151` (inputs), `#233c4d` (tabs),
`#1c3444` (table rows), `#203544` (panel-title divider), `#203443` (`--line`, section rules).

### 2.4 Text

| Role | Value |
|---|---|
| Body default | `#e6edf3` |
| Brand word-mark | `#e8f2f5` |
| Strong / values | `#d1e6e9` (metric numbers), `#c8dae3` (empty-state title), `#b4cbd8`, `#b4c9d7` (table cells) |
| Body copy | `#91a9ba` |
| Fine print | `#8ba2b2` |
| Field label | `#9ab1c1` |
| Eyebrow / tiny index | `#7ca2ae` |
| Muted secondary | `#7493a9`, `#789daf`, `#7d9aad`, `#829eb1` (nav) |
| Headline accent span | `#82dfd2` (hero), `#849dac` (story h2), `#83d9cb` (action h2) |

### 2.5 Accent and status

| Role | Text | Background | Border |
|---|---|---|---|
| **Primary button** | `#082521` | `#78e3d1` (hover `#a2f1e4`) | `#78e3d1` |
| Link (`.s-link`) | `#82ddce` (hover `#c2fff3`) | — | — |
| Logo | `#75e1cd` | — | — |
| Focus outline | — | — | `2px solid #70e2d1`, offset 4px |
| Selection | white | `#70e2d144` | — |
| Live dot | — | `#82e6c4`, glow `#81e5c442` | — |
| Offline dot | — | `#e0b47b` | — |
| Slider | track `#244050`, range `#6edfcf`, thumb `#8aeddc` with `3px #112e34` border | | |
| Badge · neutral | `#9db6c6` | `#1730408c` | `#345060` |
| Badge · ready | `#7ae3bb` | `#123a3180` | `#285849` |
| Badge · amber | `#deb77c` | `#3e321e80` | `#615135` |
| Badge · danger | `#e5aaa0` | `#422526` | `#653c3b` |
| Notice · info | `#a2c4ce` | `#12303b66` | `#284852` |
| Notice · warning | `#cab28e` | `#372e1d66` | `#4e422e` |
| Confidence box | `#b5b28b` / `#9da88e` | `#2e332080` | `#46513d` |
| Query result | `#7dcab8` / `#a4ecdc` | `#12363288` | `#2a554b` |
| Global error toast | `#f0d1a7` | `#3d3021` | — |
| Inline legend swatches | `.cyan #7cddd2`, `.amber #e0b77e`, `.gray #7392a3` | | |

### 2.6 Map and data-visualisation colours (hard-coded in TSX)

**2D flood raster**, `app/terrain-map.tsx:9`. There are five classes, drawn at alpha 225/255. The same colours are reused for every layer, and only the class breaks change:

| Class | RGB | Hex | Depth (m) | Velocity (m/s) | Arrival (min) |
|---|---|---|---|---|---|
| 1 | 157,245,223 | `#9df5df` | 0.3–1 | 0–0.5 | 0–5 |
| 2 | 67,222,212 | `#43ded4` | 1–3 | 0.5–1 | 5–15 |
| 3 | 29,198,229 | `#1dc6e5` | 3–10 | 1–2 | 15–30 |
| 4 | 31,140,239 | `#1f8cef` | 10–20 | 2–5 | 30–60 |
| 5 | 68,86,238 | `#4456ee` | > 20 | > 5 | > 60 |

The legend ramp is `.color-ramp { linear-gradient(90deg,#9df5df,#43ded4,#1dc6e5,#1f8cef,#4456ee) }`.
The raster canvas uses `mix-blend-mode: screen`.

**3D water**, `app/sentriq/terrain-3d.tsx:21`, uses **3 classes** at opacity 0.87: `>20 m #279ce4`,
`>3 m #3dd7e7`, and `≥0.3 m #72f2d7`. The particle overlay uses `#9bfff5`.
**Software 3D fallback**, `app/sentriq/terrain-canvas.tsx:11`: `>20 m #39a7dfe8`, `>3 m #50dce4ee`,
`else #8cedd6e8`.

| Map element | Values |
|---|---|
| Exposure point (2D) | fill `#ffd69a`, border `1.5px #654d32`, halo `#f8d7a814` |
| Observed / imported polygons (2D) | `#fcbb55`, fill-opacity 0.4, stroke 0.08 |
| Inflow pin (2D) | `#c5ede0` fill, `#155e4a` icon, `3px #3d796d` border |
| Inflow marker (3D) | box `#f2ba7b` (emissive `#8b4e15`), stem `#78efe0`, cap `#9effed` |
| Hillshade image filter | `saturate(.65) hue-rotate(38deg) brightness(.7) contrast(1.15)` |
| Elevation fallback ramp (2D) | `rgb(25+60t, 42+70t, 39+67t)`, t = normalised elevation |
| 3D terrain vertex colour | `rgb(.11+.19t, .21+.24t, .24+.23t)`. Bands every 120 m are darkened ×0.68. |
| 3D lights | hemisphere `#9acee0`/`#071421` ×2.5; sun `#d8f2ff` ×3.4; rim `#1c788b` ×2 |
| 3D ground grid | `#18323c` / `#0f2935`. Block sides `#183242`. |
| Map grid overlay | `#b3cdad09` lines at 16.66% × 20% |
| SPH lab canvas | bg `#122f31`, grid `#345150`, walls `#addcc9`, particles `#50e0d4`, compressed (ρ>1100) `#2e9bfa`, text `#daeeea` |

> The KML export, GEE script and HTML report generators these three rows used to describe were removed along with
> the rest of the data layer (see `API_USAGE.md` and `../docs/progress.md`); their colours no longer exist anywhere
> in the codebase.

> `docs/handoff_contract.md` §6 says the colours in `contracts/styles.json` should come from this
> guide. Its depth breaks are `[0.3, 0.5, 2, 5]` m and its arrival breaks are
> `[900, 1800, 3600, 7200]` s. Neither matches the breaks above (see API_USAGE.md, Issues).

---

## 3. Typography

| Item | Value |
|---|---|
| Family | `Arial, Helvetica, sans-serif` everywhere (`body`, `--font-sans`). **No web fonts are loaded.** `monospace` is used for the SPH lab canvas text and a few labels (`.downstream-item>span`, `font:9px monospace`). |
| Base size | `14px` on `body` |
| Weights | 400, **500** (headings, most emphasis), 600 (buttons, eyebrow, brand), 700 (rare) |
| Headline tracking | tight negative letter-spacing: hero `-2.8px`, h2 `-0.6px` to `-1.3px` |
| Label tracking | eyebrows and badges are uppercase-looking with `1px`–`1.8px` letter-spacing |

Effective sizes on desktop (after the "readable" layer at line 20):

| Element | Size |
|---|---|
| Hero h1 (landing) | `clamp(42px, 4.1vw, 62px)`, 64px at ≥1550 px |
| Story section h2 | 36px (32 / 28 px at smaller breakpoints) |
| Workspace page h1 (`.workspace-title h1`) | 27px (23px mobile) |
| Global h2 | 22px; panel h2 18px; panel-title h2 16px |
| h3 | 16px |
| Metric value (`.mini-metric strong`) | 22px (impact metrics 25–30 px) |
| Body copy | 15px landing and 13–14 px workspace, line-height 1.9 |
| Buttons / links | 13px |
| Table cell / head | 12px / 11px (head is uppercase, 1px tracking) |
| Field label / input | 12px / 14px |
| Fine print / eyebrow / badge | 12px / 10px / 10px |

Many rules still set **5–8 px** text: `.scene-caption` 4–6 px, `.brand-s small` 5.5–6.5 px,
`.map-bottom` 7px, `.dam-pin b` 7px, and `.s-badge` 6–7 px in several breakpoints. Treat these as defects, not
as part of the scale.

---

## 4. Spacing scale

There is **no formal spacing scale**. Values are ad-hoc pixels, usually 1 px apart. The most frequent values are:

| Use | Common values (px) |
|---|---|
| `gap` | 10 · 15 · 8 · 18 · 7 · 20 · 12 · 14 · 13 · 9 · 23 · 25 |
| `padding` | 20 · 17 · 21 · 22 · 23 · 12 · 15 · 16 · 30 |
| Panel padding | `.s-panel` 23px (20px ≤600 px); `.panel-title` 19px 22px |
| Page padding | `.command-content` 31px 29px 0; landing sections `104px 0`, side padding `5%` |
| Field vertical rhythm | `.s-field` margin 14px 0; `.s-range` 22px 0 12px |

If you add new code, use **4 · 8 · 12 · 16 · 20 · 24 · 32** px. That is close to what already exists.

Container widths: workspace `max-width: 1800px`; landing nav and hero `1480px`; landing sections `1332px`;
dialog `720px`.

---

## 5. Border radii

| Radius | Used for |
|---|---|
| `2px`–`3px` | legend swatches, colour ramp, map-tool hover |
| `4px` | `.s-badge`, swipe handle |
| `5px` | inputs, `.num-input`, search box, `.s-nav`, map tools and menus, query/confidence boxes, export tiles |
| `6px` | `.s-btn`, `.s-notice`, `.command-strip`, `.depth-legend`, `.rapid-answer` |
| `7px` | `.map-stage`, `.scenario-inspector`, `.panel`, `.upload-target` |
| `8px` | `.s-panel`, `.hero-control`, `.impact-landing-grid` |
| `50%` | dots, avatar, pins, step markers |
| shadcn tokens | `--radius-sm` = `.65rem − 4px`, `--radius-md` = `.65rem − 2px`, `--radius-lg` = `.65rem` (≈10.4 px). These apply only inside `components/ui`. |

---

## 6. Shadows and effects

The UI is almost flat, with only a few glows:

| Value | Where |
|---|---|
| `0 3px 18px #58d7c009` | primary button |
| `0 0 10px #81e5c442` | live dot glow |
| `0 0 0 1px #81d9cd` | slider thumb ring |
| `0 0 0 5px #bbe7d916` | inflow pin halo |
| `0 0 0 3px #f8d7a814` | exposure-dot halo |
| `0 0 6px #70dad966`, `0 0 17px #67c5b844`, `0 0 25px #74dcc3aa` | particle decoration, matrix nodes (selected) |
| `0 3px 15px #0002`, `0 4px 15px #0002`, `0 4px 20px #0002`, `0 8px 22px #0003`, `0 25px 50px #0002` | floating map tools and menus, cards |
| `-10px 12px 0 #0e2432, -11px 13px 0 #2a4958, -21px 24px 0 #0b1d2a, -22px 25px 0 #243e4d` | stacked-cards effect (landing) |
| `backdrop-filter: blur(8px / 10px)` | map chips, depth legend |
| Motion | only `transition: background .2s, color .2s, border-color .2s` on buttons and links. No keyframes. `prefers-reduced-motion` disables all transitions and smooth scroll. |

---

## 7. Layout structure

### 7.1 Routes
- `/` → landing page (`src/main.tsx` → `SentriqApp` with `initialView='home'`).
- `/{view}` for `dashboard | simulation | library | compare | lab | impact | data | monitoring | exports | sites | settings`.
  Any other value renders a plain "404" div (`src/main.tsx`) — there is no server, so this returns HTTP 200; a
  production host needs an SPA fallback to `index.html` for all of these paths.
- **Everything is one client component**, `app/sentriq/app.tsx`. Navigation calls `history.pushState` and switches a
  `view` state, so the router does not re-render the page.

### 7.2 Landing page (`app/sentriq/landing.tsx`)
A single long scrolling page. `.landing-nav` (89 px) → `.hero` (copy left, Three.js terrain right,
`.hero-control` overlay bar at the bottom) → `.mission-strip` → story sections 01–07 (`.risk-section`,
`.data-story`, `.physics-story`, `.rapid-story`, `.impact-story`, `.action-story`) → `.landing-footer`.

### 7.3 Command centre (all other views)
```
SidebarProvider (--sidebar-width: 222px)
├── Sidebar.sentriq-sidebar      brand · "COMMAND CENTRE" nav (9 items) · active-site card · settings · SIH badge
└── .command-app
    ├── header.command-top (66px)   trigger · breadcrumb · connection label · "SQ" avatar (opens methodology dialog)
    └── main.command-content (max 1800px, padding 31/29)
        ├── .workspace-title        eyebrow + h1 + status badge + "Add new site"
        ├── <view body>             (below)
        └── footer.command-footer
```

View bodies (all in `app/sentriq/app.tsx`):

| View | Line | Grid |
|---|---|---|
| dashboard / simulation | 48 | `.command-strip` + `.map-workspace` (`1fr 282px`: `.map-stage` with 3D/2D tabs, map, `.map-metrics` ×4, `.playback` \| `.scenario-inspector`). Dashboard adds `.dashboard-bottom` (`1.2fr 1fr`). |
| library | 49 | `.library-feature` (`1.15fr 1fr`: copy + `.scenario-matrix`) → `.table-toolbar` → scenario table → saved-runs table |
| compare | 50 | `.model-compare-grid` (`1fr 1fr`: SPH, Delft3D cards) → agreement panel |
| lab | 51 | warning notice → `<SPHLab>` → `.concept-compare` |
| impact | 52 | notice → `.impact-metrics` ×4 → `.impact-map-layout` (`1.3fr 1fr`: map \| downstream list) → spread panel |
| monitoring | 53 | `.monitoring-grid` (`1fr 300px`: swipe map \| GEE controls) |
| exports | 54 | `.export-layout` (`1fr 1fr`: format list \| manifest) |
| sites | 55 | `.onboarding-steps` (6) → `.onboarding-layout` (`1fr 315px`) |
| data | 56 | `.data-layout` (`1.5fr 1fr`: dataset registry \| manual ingestion) |
| settings | 57 | `.settings-grid` (`1fr 1fr`) → `.architecture-flow` (6 columns) |

### 7.4 Breakpoints
`min-width:1550px`, `max-width:1450px`, `1150px`, `900px`, `600px`, `520px` in CSS, plus `768px` from
`hooks/use-mobile.ts`, which the shadcn sidebar uses to switch to a sheet. At ≤900 px most two-column grids
collapse to one column and `.map-workspace` stacks the inspector under the map.

### 7.5 Map height
`.map-stage>.terrain-three` is 450 px (420 at ≤1150, 410 at ≤900, 340–360 at ≤600).
`.terrain-map` has min-height 400–440 px. The impact map is 490 px.

---

## 8. Reusable components

### 8.1 App components

| Component | File | Purpose | Props |
|---|---|---|---|
| `SentriqApp` (default) | `app/sentriq/app.tsx:22` | The whole application: state, data loading, all views, workers, uploads, exports. | `initialView?: string` (default `'home'`) |
| `Logo` | `app/sentriq/app.tsx:60` | Hexagon + mountains SVG logo (sidebar). | none |
| `MiniMetric` | `app/sentriq/app.tsx:61` | Label / big value / unit tile (`.mini-metric`). | `label`, `value` (preformatted string), `unit` (all `any`) |
| `Landing` (default) | `app/sentriq/landing.tsx:7` | Public landing page. | `grid, result, cache, severity, rapid(v), queryMs, frame, playing, setFrame, setPlaying, go(view), summary{area,depth,velocity,peak}, wet[], pop, bracket` (typed `any`). `playing` and `pop` are accepted but unused. |
| `Brand` | `app/sentriq/landing.tsx:22` | Logo variant for the landing header and footer. It duplicates `Logo` with a slightly different path. | none |
| `SelectField` | `app/sentriq/ui.tsx:6` | Labelled shadcn `Select`. | `value`, `onChange(v)`, `options: [value,label][]`, `label?` |
| `Num` | `app/sentriq/ui.tsx:7` | Labelled numeric input with a unit suffix. It keeps a draft string and clamps to `[min,max]` on blur. | `label`, `value`, `onChange(n)`, `min=0`, `max=10000`, `step=1`, `unit?` |
| `Range` | `app/sentriq/ui.tsx:8` | Labelled slider with a value readout and min/max labels. | `label`, `value`, `onChange(n)`, `min=25`, `max=100`, `step=1`, `unit='%'` |
| `Badge` | `app/sentriq/ui.tsx:9` | Status pill (`.s-badge`). `ready` adds a check icon. | `children`, `tone: 'neutral' \| 'ready' \| 'amber' \| 'danger'` (default `neutral`) |
| `Empty` | `app/sentriq/ui.tsx:10` | Empty-state block. | `title`, `children`, `icon?` (lucide component) |
| `SourceLink` | `app/sentriq/ui.tsx:11` | External link with an arrow icon, `target=_blank`. | `href`, `children` |
| `TerrainMap` | `app/terrain-map.tsx:6` | 2D map: hillshade image (or elevation canvas), flood raster canvas, observed polygons SVG, exposure dots, inflow pin, pan/zoom, hover inspector, legend, layer menu, click-to-pick inflow cell. | `grid: Grid`, `result: Result \| null`, `frame: number`, `layer: string` (`'max'` or `'time'`), `valueKind?: 'depth'\|'velocity'\|'arrival'`, `wetMask?: number[]`, `assets: any[]` (`{lon,lat,name}`), `observed?: FeatureCollection`, `onSource?(i)`, `sourceIndex?`, `picking?`, `styles?: any` (contract §6 shape from `source.getStyles()`; legend labels read "Awaiting style classes" until it arrives — see API_USAGE.md) |
| `WavesMini`, `ElevationCanvas` | `app/terrain-map.tsx:31-32` | Pin icon, and the fallback elevation raster when the grid has no hillshade. | `ElevationCanvas{grid}` |
| `Terrain3D` (default) | `app/sentriq/terrain-3d.tsx:8` | Three.js DEM mesh cropped around `grid.sourceIndex`, with water quads, inflow marker and orbit controls. Falls back to `TerrainCanvas` if WebGL fails. | `grid`, `result`, `frame=24`, `mode='terrain'` (`'particles'` adds points), `className=''`, `wire=false` |
| `TerrainCanvas` (default) | `app/sentriq/terrain-canvas.tsx:4` | 2D-canvas painter's-algorithm 3D fallback. Drag rotates, wheel zooms. | `grid`, `result`, `frame`, `reset: number` (increment it to reset the camera) |
| `SPHLab` (default) | `app/sph-lab.tsx:4` | 204-particle 2D WCSPH dam-break toy on a 760×250 canvas. Runs for 5 s of simulated time. | none |

### 8.2 shadcn/ui primitives actually used

| Component | File | Used where |
|---|---|---|
| `Sidebar`, `SidebarProvider`, `SidebarHeader`, `SidebarContent`, `SidebarFooter`, `SidebarMenu`, `SidebarMenuItem`, `SidebarMenuButton` (`isActive`), `SidebarTrigger` | `components/ui/sidebar.tsx` | command-centre shell |
| `Tabs`, `TabsList`, `TabsTrigger` | `components/ui/tabs.tsx` | 3D/2D toggle, Rapid/Physics toggle |
| `Switch` (`checked`, `onCheckedChange`) | `components/ui/switch.tsx` | map layer menu, exposure toggle |
| `Table`, `TableHeader`, `TableBody`, `TableRow`, `TableHead`, `TableCell` | `components/ui/table.tsx` | library, saved runs |
| `Dialog`, `DialogContent`, `DialogTitle`, `DialogDescription` | `components/ui/dialog.tsx` | methodology dialog |
| `Progress` (`value`) | `components/ui/progress.tsx` | job progress |
| `Slider` (`value[]`, `min`, `max`, `step`, `onValueChange`) | `components/ui/slider.tsx` | `Range`, playback, swipe |
| `Select`, `SelectTrigger`, `SelectValue`, `SelectContent`, `SelectItem` | `components/ui/select.tsx` | `SelectField` |
| `Toaster`, `toast` | `sonner` (package, not `components/ui/sonner.tsx`) | all notifications |

The props are the standard shadcn/Radix ones. See each file.

### 8.3 shadcn/ui primitives present but unused
`accordion, alert, alert-dialog, aspect-ratio, attachment, avatar, badge, breadcrumb, bubble, button,
button-group, calendar, card, carousel, chart, checkbox, collapsible, combobox, command, context-menu,
direction, drawer, dropdown-menu, empty, field, form, hover-card, input, input-group, input-otp, item, kbd,
label, marker, menubar, message, message-scroller, native-select, navigation-menu, pagination, popover,
radio-group, resizable, scroll-area, separator, sheet (used internally by sidebar), skeleton, sonner, spinner,
textarea, toggle, toggle-group, tooltip`, all in `components/ui/`. Note that the app's own `Badge` and `Empty`
(in `app/sentriq/ui.tsx`) have the same names as the shadcn `badge.tsx` and `empty.tsx`. Import the right one.

### 8.4 Recurring CSS "components" (class recipes)
`.s-btn` + `.primary | .ghost | .text` (+ `.full`), `.s-link`, `.s-badge` + tone, `.s-panel` (+ `.no-padding`),
`.panel-title`, `.s-notice` (+ `.warning`), `.s-empty`, `.s-field`, `.num-input`, `.s-range`, `.two-fields`,
`.eyebrow`, `.tiny-index`, `.body-copy`, `.fine-print`, `.live-dot`, `.offline-dot`, `.mini-metric`,
`.upload-target`, `.layer-pills`, `.confidence-box`. The legacy `.panel`, `.panel-heading`, `.btn.primary`,
`.btn.secondary` and `.footnote` are used only by `SPHLab`.
