import type { Config } from 'eslint/config';

import { zyplux } from '@zyplux/eslint-config';

const config: Config[] = zyplux({ tsconfigRootDir: import.meta.dirname });

export default config;
