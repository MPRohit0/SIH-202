'use client';
// design/target-state-preview only. Wraps any map, chart or 3D view so every
// visual carries a diagonal "PREVIEW" mark, in addition to the persistent
// PreviewBanner. Only ever rendered when source.isPreviewMode() is true --
// callers gate on that, this component does not check it itself, so it stays
// a plain, reusable wrapper.
import type {ReactNode} from 'react';
import './preview.css';

export default function PreviewWatermark({children, small = false}: {children: ReactNode; small?: boolean}) {
  return (
    <div className={'preview-watermark-host' + (small ? ' small' : '')}>
      {children}
      <div className="preview-watermark" aria-hidden="true"><span>PREVIEW</span></div>
    </div>
  );
}
