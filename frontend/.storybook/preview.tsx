import type { Preview } from '@storybook/tanstack-react'
import '../src/index.css'

const preview: Preview = {
  parameters: {
    controls: {
      matchers: {
        color: /(background|color)$/i,
        date: /Date$/i,
      },
    },

    a11y: {
      // 'todo' - show a11y violations in the test UI only
      // 'error' - fail CI on a11y violations
      // 'off' - skip a11y checks entirely
      test: 'todo',
    },

    backgrounds: {
      default: 'dark',
      values: [
        { name: 'dark', value: 'oklch(0.145 0 0)' },
        { name: 'light', value: 'oklch(1 0 0)' },
      ],
    },
  },
  decorators: [
    (Story) => {
      document.documentElement.classList.add('dark')
      return Story()
    },
  ],
}

export default preview
