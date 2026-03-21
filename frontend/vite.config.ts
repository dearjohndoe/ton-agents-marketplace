import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import { nodePolyfills } from 'vite-plugin-node-polyfills'

export default defineConfig({
  base: '/ton-agents-marketplace/',
  plugins: [
    react(),
    nodePolyfills(), // provides Buffer, global, process for @ton/core
  ],
})
