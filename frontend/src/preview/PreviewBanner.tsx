'use client';
// design/target-state-preview only. Mounted once at the top of the app, and
// only when source.isPreviewMode() is true, so it never renders (and its
// stylesheet is never imported) in default mode. See frontend/README.md
// "Preview mode". This banner is the ONE place preview mode says its data is
// simulated -- everything else in the UI is presented as a finished product
// (see docs/demo_script.md).
import {Sparkles} from 'lucide-react';
import './preview.css';

export default function PreviewBanner() {
  return (
    <div className="preview-banner" role="status">
      <Sparkles size={14} />
      <span>Demo mode — simulated data</span>
    </div>
  );
}
