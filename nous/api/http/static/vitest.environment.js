/* jsdom DOM, but transform tests in SSR mode.
   Vitest's builtin jsdom environment forces transformMode "web", which makes
   Vite externalize Node builtins. The test harness reads the shipped modules
   with fs/path (load-core.js), so web mode turns every such import into an
   empty stub ("fileURLToPath is not a function") and the whole suite fails
   before running. SSR mode keeps the builtins while still giving tests a DOM. */
import { builtinEnvironments } from 'vitest/environments';

export default { ...builtinEnvironments.jsdom, transformMode: 'ssr' };
