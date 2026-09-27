# Frontend session rules

Before changing frontend code, read `STYLE_GUIDE.md` and follow it.

## Preserve the existing UI

- Preserve the existing visual design exactly. Do not redesign, restyle, or make visual changes unless explicitly asked.
- Treat `STYLE_GUIDE.md` as the source of truth for the existing palette, typography, spacing, layout, components, and visual details.
- Reuse existing components wherever possible.
- When new UI is needed, copy the structure and classes of the closest existing component, then adapt only what the new UI requires.
- Do not add UI libraries.
- Do not change global styles, the theme, or shared CSS without asking first.
- Limit changes to the data layer unless explicitly asked to change the UI.

## Verify every change

- Run the Playwright visual tests after every change.
- The screenshot harness is in `visual/`. With the frontend server running, capture all screens with `cd visual && npm run shots -- shot <label>`.
- Compare the new screenshots with a baseline using `cd visual && npm run shots -- diff <baseline-label> <new-label>`.
- Check the affected screens against the existing visual design and investigate unexpected visual differences before finishing.
