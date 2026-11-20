import { readdirSync } from 'node:fs';
import { resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { defineConfig } from 'vite';

const frontend = fileURLToPath(new URL('.', import.meta.url));
const root = resolve(frontend, '..');
const entries = resolve(frontend, 'entries');
const input = Object.fromEntries(readdirSync(entries)
  .filter((filename) => /\.(?:mjs|css)$/.test(filename))
  .map((filename) => [filename.replace(/\.[^.]+$/, ''), resolve(entries, filename)]));

export default defineConfig({
  root,
  base: '/assets/build/',
  publicDir: false,
  build: {
    outDir: resolve(frontend, 'dist'),
    emptyOutDir: false,
    manifest: true,
    sourcemap: false,
    target: ['chrome109', 'edge109', 'firefox115', 'safari16.4'],
    cssMinify: false,
    modulePreload: { polyfill: false },
    rollupOptions: {
      input,
      output: {
        entryFileNames: '[name]-[hash:12].js',
        chunkFileNames: '[name]-[hash:12].js',
        assetFileNames: '[name]-[hash:12][extname]',
      },
    },
  },
});
