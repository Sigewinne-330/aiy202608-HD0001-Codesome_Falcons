import { createVuetify } from 'vuetify'
import 'vuetify/styles'
import { zhHans, zhHant, en } from 'vuetify/locale'

const vuetify = createVuetify({
  theme: {
    defaultTheme: 'light',
    themes: {
      light: {
        colors: {
          primary: '#1565C0',
          secondary: '#26A69A',
          accent: '#FF7043',
          error: '#E53935',
          warning: '#FB8C00',
          success: '#43A047',
          background: '#F5F7FA',
          surface: '#FFFFFF',
        }
      }
    }
  },
  locale: {
    locale: 'zhHans',
    fallback: 'en',
    messages: { zhHans, zhHant, en },
  },
  defaults: {
    VCard: {
      elevation: 2,
      rounded: 'lg',
    },
    VBtn: {
      rounded: 'lg',
    },
  }
})

export default vuetify
