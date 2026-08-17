import { readonly, ref } from 'vue'

const notices = ref([])
let nextId = 1

export function dismissNotice(id) {
  notices.value = notices.value.filter((item) => item.id !== id)
}

export function notify(message, options = {}) {
  if (!message) return null
  const notice = {
    id: nextId++,
    message: String(message),
    type: options.type || 'info',
    title: options.title || '',
    actionLabel: options.actionLabel || '',
    action: typeof options.action === 'function' ? options.action : null,
  }
  notices.value = [...notices.value.slice(-3), notice]
  const timeout = Number(options.timeout ?? 4200)
  if (timeout > 0 && typeof window !== 'undefined') {
    window.setTimeout(() => dismissNotice(notice.id), timeout)
  }
  return notice.id
}

export function useFeedback() {
  return { notices: readonly(notices), notify, dismissNotice }
}
