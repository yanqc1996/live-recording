import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';
import { viteSingleFile } from 'vite-plugin-singlefile';

export default defineConfig({
  root: 'desktop-ui',
  plugins: [react(), viteSingleFile()],
  build: {
    outDir: '../desktop/ui-dist',
    emptyOutDir: true,
    assetsInlineLimit: 100_000_000,
  },
});
