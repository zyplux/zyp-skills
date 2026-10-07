import type { ViteUserConfig } from 'vitest/config';

export default {
  test: {
    coverage: {
      enabled: true,
      provider: 'istanbul',
      thresholds: {
        branches: 90,
        functions: 90,
        lines: 90,
        statements: 90,
      },
    },
    passWithNoTests: true,
  },
} satisfies ViteUserConfig;
