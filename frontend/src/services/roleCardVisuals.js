import i18n from '@/i18n'

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
  if (slug) {
    const key = `roleCards.${slug}`
    if (i18n.global.te(key)) return i18n.global.t(key)
  }
  return ROLE_CARD_NAMES[slug] || ''
}

/**
 * 角色卡显示名（跟随界面语言）。
 * 后端返回的 card.name 固定为中文，这里按 slug 查 i18n；
 * 未收录的 slug（用户自定义卡）回退到后端原始 name。
 */
export function roleCardDisplayName(card) {
  if (!card) return ''
  const slug = card.slug
  if (slug) {
    const key = `roleCards.${slug}`
    if (i18n.global.te(key)) return i18n.global.t(key)
  }
  return card.name || ''
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
