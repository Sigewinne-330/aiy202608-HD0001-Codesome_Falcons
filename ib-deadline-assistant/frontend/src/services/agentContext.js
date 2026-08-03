export const OPEN_AGENT_EVENT = 'ibuddy:open-agent'

export function openAgent(context = null) {
  window.dispatchEvent(new CustomEvent(OPEN_AGENT_EVENT, { detail: context }))
}

export function onOpenAgent(handler) {
  const listener = (event) => handler(event.detail || null)
  window.addEventListener(OPEN_AGENT_EVENT, listener)
  return () => window.removeEventListener(OPEN_AGENT_EVENT, listener)
}
