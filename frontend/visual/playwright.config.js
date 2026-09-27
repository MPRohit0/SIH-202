import {defineConfig} from '@playwright/test';

export default defineConfig({
  testDir: './tests',
  snapshotPathTemplate: '{testDir}/__screenshots__/{arg}{ext}',
  fullyParallel: true,
  reporter: 'list',
  use: {
    baseURL: 'http://127.0.0.1:5173',
    browserName: 'chromium',
    viewport: {width: 1440, height: 900},
    reducedMotion: 'reduce',
    launchOptions: {
      args: ['--use-angle=swiftshader', '--enable-unsafe-swiftshader'],
    },
  },
  webServer: {
    command: 'npm run dev -- --host 127.0.0.1',
    cwd: '..',
    url: 'http://127.0.0.1:5173',
    reuseExistingServer: !process.env.CI,
    timeout: 30_000,
  },
});
