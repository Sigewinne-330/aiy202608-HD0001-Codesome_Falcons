import { createI18n } from 'vue-i18n'
import zhCN from '@/locales/zh-CN'
import zhTW from '@/locales/zh-TW'
import en from '@/locales/en'
import { progressMessages } from '@/locales/progress'

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

const i18n = createI18n({
  legacy: false,
  locale: getInitialLocale(),
  fallbackLocale: 'zh-CN',
  messages: {
    'zh-CN': { ...zhCN, common: { ...zhCN.common, edit: '编辑' }, progress: { ...zhCN.progress, ...progressMessages['zh-CN'] } },
    'zh-TW': { ...zhTW, common: { ...zhTW.common, edit: '編輯' }, progress: { ...zhTW.progress, ...progressMessages['zh-TW'] } },
    en: { ...en, common: { ...en.common, edit: 'Edit' }, progress: { ...en.progress, ...progressMessages.en } },
  },
})

export default i18n
