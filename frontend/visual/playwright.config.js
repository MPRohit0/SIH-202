import {defineConfig} from '@playwright/test';

// Two projects share this config: 'default' is the existing app against the
// live/mock API seam (VITE_USE_MOCKS, unset VITE_DATA_MODE) on :5173, and its
// snapshot path and baselines are untouched by design/target-state-preview.
// 'preview' runs the same specs against a second dev server with
// VITE_DATA_MODE=preview on :5174, so its screenshots land in their own
// __screenshots__/preview/ directory and never overwrite the default
// baselines. Run one project at a time with `--project=default` /
// `--project=preview`, or both (the default when no --project is given).
export default defineConfig({
  testDir: './tests',
  snapshotPathTemplate: '{testDir}/__screenshots__/{arg}{ext}',
  fullyParallel: true,
  reporter: 'list',
  use: {
    browserName: 'chromium',
    viewport: {width: 1440, height: 900},
    reducedMotion: 'reduce',
    launchOptions: {
      args: ['--use-angle=swiftshader', '--enable-unsafe-swiftshader'],
    },
  },
  projects: [
    {
      name: 'default',
      use: {baseURL: 'http://127.0.0.1:5173'},
    },
    {
      name: 'preview',
      use: {baseURL: 'http://127.0.0.1:5174'},
      snapshotPathTemplate: '{testDir}/__screenshots__/preview/{arg}{ext}',
    },
  ],
  webServer: [
    {
      command: 'npm run dev -- --host 127.0.0.1',
      cwd: '..',
      url: 'http://127.0.0.1:5173',
      reuseExistingServer: !process.env.CI,
      timeout: 30_000,
      // design/target-state-preview: preview is now the branch default
      // (frontend/.env.development sets VITE_DATA_MODE=preview for every
      // `npm run dev`), so the 'default' project must pin 'live' explicitly
      // here to keep testing the live/mock seam and its existing baselines.
      // Process env passed to a child process overrides values from .env
      // files (Vite only falls back to .env when a var isn't already set).
      env: {VITE_DATA_MODE: 'live'},
    },
    {
      command: 'npm run dev -- --host 127.0.0.1 --port 5174',
      cwd: '..',
      url: 'http://127.0.0.1:5174',
      reuseExistingServer: !process.env.CI,
      timeout: 30_000,
      env: {VITE_DATA_MODE: 'preview'},
    },
  ],
});
