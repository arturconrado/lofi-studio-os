import { defineConfig } from 'vitest/config';
import preact from '@preact/preset-vite';

// Built into web/app and served by FastAPI under /static/app; /studio/* returns its index.html.
export default defineConfig({
  plugins: [preact()],
  base: '/static/app/',
  build: { outDir: '../web/app', emptyOutDir: true, sourcemap: false, target: 'es2020' },
  server: { proxy: { '/api': 'http://127.0.0.1:8000', '/static/program-player.html': 'http://127.0.0.1:8000' } },
  test: { environment: 'jsdom', globals: false },
});
