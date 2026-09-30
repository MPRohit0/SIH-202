// Preview mode only (VITE_DATA_MODE=preview): swaps in the wording from
// ui_text_preview.json where the default text describes the real-mode data
// (e.g. "one direct solver run") and would be wrong for the demo scenario.
// Runs once at startup, before the app first renders; default mode is untouched.
import uiText from './ui_text.json';
import overrides from './ui_text_preview.json';
import {isPreviewMode} from '../data/source';

function merge(target: Record<string, unknown>, patch: Record<string, unknown>) {
  for (const [k, v] of Object.entries(patch)) {
    if (v && typeof v === 'object' && !Array.isArray(v) && target[k] && typeof target[k] === 'object') merge(target[k] as Record<string, unknown>, v as Record<string, unknown>);
    else target[k] = v;
  }
}

if (isPreviewMode()) merge(uiText as unknown as Record<string, unknown>, overrides as unknown as Record<string, unknown>);
