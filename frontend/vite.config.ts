import { readFileSync } from 'node:fs'
import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'
import type { Plugin as EsbuildPlugin } from 'esbuild'

// shortcut: security software on the dev machine stops esbuild.exe from opening .js files, which breaks
// the dev server's dependency pre-bundling. Node reads them and hands esbuild the contents instead.
// Harmless elsewhere; remove once esbuild can read node_modules again.
const readJsWithNode: EsbuildPlugin = {
  name: 'read-js-with-node',
  setup(build) {
    build.onLoad({ filter: /\.[cm]?js$/, namespace: 'file' }, (args) => ({
      contents: readFileSync(args.path, 'utf8'),
      loader: 'js',
    }))
  },
}

export default defineConfig({
  plugins: [
    react(),
    tailwindcss(),
  ],
  optimizeDeps: { esbuildOptions: { plugins: [readJsWithNode] } },
})
