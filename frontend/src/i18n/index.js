import { createI18n } from 'vue-i18n'
import zhCN from '@/locales/zh-CN'
import zhTW from '@/locales/zh-TW'
import en from '@/locales/en'
import { progressMessages } from '@/locales/progress'
import { redesignMessages } from '@/locales/redesign'

export const SUPPORTED_LOCALES = ['zh-CN', 'zh-TW', 'en']

export const LOCALE_NAMES = {
  'zh-CN': '简体中文',
  'zh-TW': '繁體中文',
  en: 'English',
}

/** Vuetify 内置 locale 映射 */
export const VUETIFY_LOCALE_MAP = {
  'zh-CN': 'zhHans',
  'zh-TW': 'zhHant',
  en: 'en',
}

const STORAGE_KEY = 'ibuddy_locale'

export function getInitialLocale() {
  if (typeof window !== 'undefined') {
    const saved = window.localStorage.getItem(STORAGE_KEY)
    if (saved && SUPPORTED_LOCALES.includes(saved)) return saved
    const nav = window.navigator.language || 'zh-CN'
    if (nav.toLowerCase().startsWith('zh-tw') || nav.toLowerCase().startsWith('zh-hk') || nav.toLowerCase().startsWith('zh-hant')) return 'zh-TW'
    if (nav.toLowerCase().startsWith('zh')) return 'zh-CN'
    return 'en'
  }
  return 'zh-CN'
}

export function setLocale(locale) {
  const target = SUPPORTED_LOCALES.includes(locale) ? locale : 'zh-CN'
  i18n.global.locale.value = target
  if (typeof window !== 'undefined') {
    window.localStorage.setItem(STORAGE_KEY, target)
    document.documentElement.lang = target
  }
  return target
}

function localeMessages(base, locale, editLabel) {
  const redesign = redesignMessages[locale]
  return {
    ...base,
    common: { ...base.common, edit: editLabel, ...redesign.common },
    chat: { ...base.chat, ...redesign.chat },
    calendar: { ...base.calendar, ...redesign.calendar },
    urgent: { ...base.urgent, ...redesign.urgent },
    tasks: { ...base.tasks, ...redesign.tasks },
    deadlines: { ...base.deadlines, ...redesign.deadlines },
    billing: { ...base.billing, ...redesign.billing },
    plan: { ...base.plan, ...redesign.plan },
    reminders: { ...base.reminders, ...redesign.reminders },
    personalization: redesign.personalization,
    progress: { ...base.progress, ...progressMessages[locale] },
  }
}

const initialLocale = getInitialLocale()
if (typeof document !== 'undefined') document.documentElement.lang = initialLocale

const i18n = createI18n({
  legacy: false,
  locale: initialLocale,
  fallbackLocale: 'zh-CN',
  messages: {
    'zh-CN': localeMessages(zhCN, 'zh-CN', '编辑'),
    'zh-TW': localeMessages(zhTW, 'zh-TW', '編輯'),
    en: localeMessages(en, 'en', 'Edit'),
  },
})

export default i18n
