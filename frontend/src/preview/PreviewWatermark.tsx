'use client';
// design/target-state-preview only. Used to wrap maps/charts/3D views. It no
// longer draws a diagonal "PREVIEW" watermark -- the demo brief asks every
// screen to look like a finished product, with only the single top
// PreviewBanner saying the data is simulated -- so this is now a plain
// pass-through. Kept (not deleted) so its ~8 call sites in app.tsx don't all
// need editing; if a call site is removed later this component can go too.
import type {ReactNode} from 'react';

export default function PreviewWatermark({children}: {children: ReactNode; small?: boolean}) {
  return <>{children}</>;
}
