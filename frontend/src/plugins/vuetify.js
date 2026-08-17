import { createVuetify } from 'vuetify'
import 'vuetify/styles'
import { zhHans, zhHant, en } from 'vuetify/locale'
import { getInitialThemeName } from '@/services/theme'

const vuetify = createVuetify({
  theme: {
    defaultTheme: getInitialThemeName(),
    themes: {
      ibuddyLight: {
        dark: false,
        colors: {
          primary: '#0F766E',
          'primary-darken-1': '#0B5F59',
          secondary: '#45635D',
          accent: '#2563EB',
          error: '#C23A4B',
          warning: '#B7791F',
          success: '#16845B',
          info: '#2563EB',
          background: '#F7F8F7',
          surface: '#FFFFFF',
          'surface-variant': '#EFF3F1',
          'on-background': '#17201D',
          'on-surface': '#17201D',
          'on-surface-variant': '#5F6B66',
        }
      },
      ibuddyDark: {
        dark: true,
        colors: {
          primary: '#2DD4BF',
          'primary-darken-1': '#1CB5A4',
          secondary: '#9DB7AF',
          accent: '#60A5FA',
          error: '#FB7185',
          warning: '#F5B94C',
          success: '#4ADE80',
          info: '#60A5FA',
          background: '#0F1412',
          surface: '#151C19',
          'surface-variant': '#1A2420',
          'on-background': '#F3F7F5',
          'on-surface': '#F3F7F5',
          'on-surface-variant': '#A9B5B0',
        },
      },
    }
  },
  locale: {
    locale: 'zhHans',
    fallback: 'en',
    messages: { zhHans, zhHant, en },
  },
  defaults: {
    VCard: {
      elevation: 0,
      rounded: 'lg',
    },
    VBtn: {
      rounded: 'lg',
      elevation: 0,
    },
    VTextField: {
      variant: 'outlined',
      density: 'comfortable',
      hideDetails: 'auto',
    },
    VTextarea: {
      variant: 'outlined',
      density: 'comfortable',
      hideDetails: 'auto',
    },
    VSelect: {
      variant: 'outlined',
      density: 'comfortable',
      hideDetails: 'auto',
    },
  }
})

export default vuetify
