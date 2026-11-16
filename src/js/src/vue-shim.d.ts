// Typed ESLint reads the project with plain TypeScript, which can't open a .vue file. This stands in for it
// there; `vue-tsc` (npm run typecheck) resolves the real component and its props first, so they stay checked.
declare module '*.vue' {
  import type { Component } from 'vue'
  const component: Component
  export default component
}
