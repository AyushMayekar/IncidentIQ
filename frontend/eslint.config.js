import js from '@eslint/js'
import globals from 'globals'
import reactHooks from 'eslint-plugin-react-hooks'
import reactRefresh from 'eslint-plugin-react-refresh'
import tseslint from 'typescript-eslint'
import { defineConfig, globalIgnores } from 'eslint/config'

export default defineConfig([
  globalIgnores(['dist']),
  {
    files: ['**/*.{ts,tsx}'],
    extends: [
      js.configs.recommended,
      tseslint.configs.recommended,
      reactHooks.configs.flat.recommended,
      reactRefresh.configs.vite,
    ],
    rules: {
      // Pure helpers live beside the components that use them; HMR quality is
      // not worth splitting every small file.
      'react-refresh/only-export-components': [
        'error',
        {
          allowExportNames: [
            'useToast',
            'SEVERITY_LABEL',
            'STATUS_LABEL',
            'formatDate',
            'statusCounts',
            'Pill',
            'Stat',
            'Fact',
            'SEVERITIES',
            'STATUSES',
          ],
        },
      ],
    },
    languageOptions: {
      globals: globals.browser,
    },
  },
])
