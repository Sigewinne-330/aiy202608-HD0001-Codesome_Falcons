export const ROLE_CARD_CHANGED_EVENT = 'ibuddy:role-card-changed'

const ROLE_CARD_AVATARS = {
  nahida: `${import.meta.env.BASE_URL || '/'}role-cards/nahida.png`,
  furina: `${import.meta.env.BASE_URL || '/'}role-cards/furina.png`,
}

const ROLE_CARD_ICONS = {
  'friendly-warm-guy': 'mdi-account-heart-outline',
  'tech-geek': 'mdi-laptop',
  'sweet-high-school-girl': 'mdi-flower-outline',
}

const ROLE_CARD_NAMES = {
  nahida: '纳西妲',
  furina: '芙宁娜',
}

export function roleCardAvatarUrl(slug) {
  return ROLE_CARD_AVATARS[slug] || ''
}

export function roleCardIcon(slug) {
  return ROLE_CARD_ICONS[slug] || 'mdi-creation-outline'
}

export function roleCardName(slug) {
  return ROLE_CARD_NAMES[slug] || ''
}

export function messageRoleCardSlug(message, fallbackSlug = '') {
  return message?.metadata?.role_card?.slug || fallbackSlug || ''
}

export function notifyRoleCardChanged(roleCard) {
  window.dispatchEvent(new CustomEvent(ROLE_CARD_CHANGED_EVENT, {
    detail: { roleCard: roleCard || null },
  }))
}

export function onRoleCardChanged(handler) {
  const listener = (event) => handler(event.detail?.roleCard || null)
  window.addEventListener(ROLE_CARD_CHANGED_EVENT, listener)
  return () => window.removeEventListener(ROLE_CARD_CHANGED_EVENT, listener)
}
