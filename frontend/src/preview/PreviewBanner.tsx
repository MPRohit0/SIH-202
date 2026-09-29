'use client';
// design/target-state-preview only. Mounted once at the top of the app, and
// only when source.isPreviewMode() is true, so it never renders (and its
// stylesheet is never imported) in default mode. See frontend/README.md
// "Preview mode".
import {AlertTriangle} from 'lucide-react';
import './preview.css';

export default function PreviewBanner() {
  return (
    <div className="preview-banner" role="status">
      <AlertTriangle size={14} />
      <span>TARGET-STATE PREVIEW — illustrative values, not model output</span>
    </div>
  );
}
