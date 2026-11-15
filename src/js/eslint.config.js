import js from '@eslint/js'
import prettier from 'eslint-config-prettier'
import pluginVue from 'eslint-plugin-vue'
import globals from 'globals'

export default [
  { ignores: ['coverage/**', 'dist/**'] }, // dist is the build output
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
      complexity: ['error', 10],
      eqeqeq: ['error', 'always', { null: 'ignore' }],
      'no-var': 'error',
      'prefer-const': 'error',
      'no-shadow': 'error',
      'no-console': ['error', { allow: ['warn', 'error'] }],
      'vue/no-undef-components': ['error', { ignorePatterns: ['^router-', '^RouterView$', '^RouterLink$'] }],
      'vue/no-unused-refs': 'error',
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
    files: ['src/__tests__/**', 'vite.config.js', 'eslint.config.js'],
    // vite.config.js runs Vitest with `globals: true`
    languageOptions: { globals: { ...globals.browser, ...globals.node, ...globals.vitest } },
  },
  // Layout is Prettier's job: turn off the stylistic rules that would fight it
  prettier,
]
