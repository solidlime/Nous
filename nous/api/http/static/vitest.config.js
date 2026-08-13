import { defineConfig } from 'vitest/config';

export default defineConfig({
  test: {
    environment: 'jsdom',
    environmentOptions: {
      jsdom: {
        console: true,
      },
    },
    globals: true,
    include: ['core/**/*.test.js'],
  },
});
