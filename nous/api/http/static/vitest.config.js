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
    include: ['core/**/*.test.js', 'chat/**/*.test.js', 'features/**/*.test.js', 'components/**/*.test.js'],
    coverage: {
      provider: 'v8',
      include: ['core/**/*.js', 'chat/**/*.js', 'features/**/*.js', 'components/**/*.js'],
      exclude: ['**/*.test.js', 'vitest.config.js'],
    },
  },
});
