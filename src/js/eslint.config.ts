import js from '@eslint/js'
import { defineConfig } from 'eslint/config'
import prettier from 'eslint-config-prettier'
import pluginVue from 'eslint-plugin-vue'
import globals from 'globals'
import tseslint from 'typescript-eslint'
import vueParser from 'vue-eslint-parser'

export default [
  { ignores: ['coverage/**', 'dist/**', 'src/api/schema.d.ts'] }, // dist is the build output; schema.d.ts is generated
  js.configs.recommended,
  ...pluginVue.configs['flat/recommended'],
  {
    languageOptions: {
      ecmaVersion: 'latest',
      sourceType: 'module',
      globals: globals.browser,
    },
    rules: {
      'no-unused-vars': ['error', { argsIgnorePattern: '^_', caughtErrors: 'none' }],
      complexity: ['error', 7],
      eqeqeq: ['error', 'always', { null: 'ignore' }],
      'no-var': 'error',
      'prefer-const': 'error',
      'no-shadow': 'error',
      'no-console': ['error', { allow: ['warn', 'error'] }],
      'vue/no-undef-components': ['error', { ignorePatterns: ['^router-', '^RouterView$', '^RouterLink$'] }],
      'vue/no-unused-refs': 'error',
      'vue/define-macros-order': ['error', { order: ['defineProps', 'defineEmits', 'defineModel'] }],
      // Stop the big components and composables regrowing: split before they pass this
      'max-lines': ['error', { max: 600, skipBlankLines: true, skipComments: true }],
    },
  },
  {
    // Tests read top to bottom: long files and long cases are fine
    files: ['src/__tests__/**'],
    rules: { complexity: 'off', 'max-lines': 'off' },
  },
  {
    files: ['src/__tests__/**', 'vite.config.ts', 'eslint.config.ts'],
    // vite.config.ts runs Vitest with `globals: true`
    languageOptions: { globals: { ...globals.browser, ...globals.node, ...globals.vitest } },
  },
  ...defineConfig({
    // TypeScript: the strictest preset, type-aware. No `any`, no unsafe member access, no floating
    // promises. It is why the typed client reads server JSON in exactly one place (api/json.ts).
    files: ['src/**/*.ts'],
    extends: [...tseslint.configs.strictTypeChecked, ...tseslint.configs.stylisticTypeChecked],
    languageOptions: { parserOptions: { projectService: true, tsconfigRootDir: import.meta.dirname } },
    rules: {
      'no-unused-vars': 'off', // @typescript-eslint/no-unused-vars replaces it
      '@typescript-eslint/no-unused-vars': ['error', { argsIgnorePattern: '^_', caughtErrors: 'none' }],
      '@typescript-eslint/consistent-type-imports': 'error',
    },
  }),
  ...defineConfig({
    // The tooling configs aren't part of the app's TypeScript project (they have their own tsconfig.node.json,
    // checked by `npm run typecheck`), so they get the strict rules that don't need type information.
    files: ['*.config.ts'],
    extends: [...tseslint.configs.strict, ...tseslint.configs.stylistic],
    rules: { '@typescript-eslint/consistent-type-imports': 'error' },
  }),
  ...defineConfig({
    // Every component is <script setup lang="ts">: the same strict, type-aware rules as .ts files.
    files: ['**/*.vue'],
    extends: [...tseslint.configs.strictTypeChecked, ...tseslint.configs.stylisticTypeChecked],
    languageOptions: {
      parser: vueParser,
      parserOptions: {
        parser: tseslint.parser,
        projectService: true,
        tsconfigRootDir: import.meta.dirname,
        extraFileExtensions: ['.vue'],
      },
    },
    rules: {
      'no-unused-vars': 'off',
      '@typescript-eslint/no-unused-vars': ['error', { argsIgnorePattern: '^_', caughtErrors: 'none' }],
      '@typescript-eslint/consistent-type-imports': 'error',
    },
  }),
  // Layout is Prettier's job: turn off the stylistic rules that would fight it
  prettier,
]
