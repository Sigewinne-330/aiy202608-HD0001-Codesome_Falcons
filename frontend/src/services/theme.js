import { computed, readonly, ref } from 'vue'

const STORAGE_KEY = 'ibuddy.themeMode'
const VALID_MODES = new Set(['system', 'light', 'dark'])

function storedMode() {
  if (typeof window === 'undefined') return 'system'
  const value = window.localStorage.getItem(STORAGE_KEY)
  return VALID_MODES.has(value) ? value : 'system'
}

const mode = ref(storedMode())
const systemDark = ref(typeof window !== 'undefined' && window.matchMedia?.('(prefers-color-scheme: dark)').matches)
const resolved = computed(() => mode.value === 'system' ? (systemDark.value ? 'dark' : 'light') : mode.value)

let mediaQuery = null
let vuetifyTheme = null

function applyTheme() {
  const name = resolved.value === 'dark' ? 'ibuddyDark' : 'ibuddyLight'
  if (vuetifyTheme) vuetifyTheme.change(name)
  if (typeof document !== 'undefined') {
    document.documentElement.dataset.theme = resolved.value
    document.documentElement.style.colorScheme = resolved.value
  }
}

function onSystemThemeChange(event) {
  systemDark.value = event.matches
  if (mode.value === 'system') applyTheme()
}

export function getInitialThemeName() {
  const current = mode.value === 'system'
    ? (typeof window !== 'undefined' && window.matchMedia?.('(prefers-color-scheme: dark)').matches ? 'dark' : 'light')
    : mode.value
  return current === 'dark' ? 'ibuddyDark' : 'ibuddyLight'
}

export function initializeTheme(theme) {
  vuetifyTheme = theme
  if (typeof window !== 'undefined' && !mediaQuery) {
    mediaQuery = window.matchMedia('(prefers-color-scheme: dark)')
    systemDark.value = mediaQuery.matches
    mediaQuery.addEventListener?.('change', onSystemThemeChange)
  }
  applyTheme()
  return () => {
    mediaQuery?.removeEventListener?.('change', onSystemThemeChange)
    mediaQuery = null
    vuetifyTheme = null
  }
}

export function setThemeMode(value) {
  const target = VALID_MODES.has(value) ? value : 'system'
  mode.value = target
  if (typeof window !== 'undefined') window.localStorage.setItem(STORAGE_KEY, target)
  applyTheme()
}

export function cycleThemeMode() {
  const order = ['system', 'light', 'dark']
  setThemeMode(order[(order.indexOf(mode.value) + 1) % order.length])
}

export function useAppTheme() {
  return {
    mode: readonly(mode),
    resolved: readonly(resolved),
    setThemeMode,
    cycleThemeMode,
  }
}
