import MarkdownIt from 'markdown-it'
import katex from 'katex'
import 'katex/dist/katex.min.css'

export {
  consumeChatStream,
  creditLabel,
  estimateTokens,
  extractTaskPayload,
  responseErrorMessage,
  tokensToCredits,
} from './chatCore.js'

const markdown = new MarkdownIt({
  html: false,
  breaks: true,
  linkify: true,
})

const defaultLinkOpen = markdown.renderer.rules.link_open
  || ((tokens, index, options, _env, self) => self.renderToken(tokens, index, options))

markdown.renderer.rules.link_open = (tokens, index, options, env, self) => {
  const token = tokens[index]
  token.attrSet('target', '_blank')
  token.attrSet('rel', 'noopener noreferrer')
  return defaultLinkOpen(tokens, index, options, env, self)
}

function renderFormula(tex, displayMode) {
  try {
    return katex.renderToString(tex.trim(), {
      displayMode,
      throwOnError: false,
      strict: 'ignore',
      trust: false,
    })
  } catch {
    return null
  }
}

function protectMath(source) {
  const formulas = []
  const replaceFormula = (displayMode) => (match, tex) => {
    const rendered = renderFormula(tex, displayMode)
    if (!rendered) return match
    const token = `IBUDDY${displayMode ? 'BLOCK' : 'INLINE'}MATH${formulas.length}TOKEN`
    formulas.push({ token, rendered, displayMode })
    return displayMode ? `\n${token}\n` : token
  }

  let text = source
    .replace(/\$\$([\s\S]+?)\$\$/g, replaceFormula(true))
    .replace(/\\\[([\s\S]+?)\\\]/g, replaceFormula(true))
    .replace(/\\\(([\s\S]+?)\\\)/g, replaceFormula(false))
    .replace(/(?<!\\)\$([^$\n]+?)\$/g, replaceFormula(false))

  return { text, formulas }
}

export function renderChatMarkdown(value) {
  const source = String(value || '')
  try {
    const withoutTaskPayload = source.replace(/```json[\s\S]*?```\s*$/, '').trim()
    const normalized = (withoutTaskPayload || source)
      .replace(/^(\s*\d+[.)])\s*\n/gm, '$1 ')
    const { text, formulas } = protectMath(normalized)
    let rendered = markdown.render(text)

    for (const formula of formulas) {
      if (formula.displayMode) {
        rendered = rendered.replace(`<p>${formula.token}</p>`, formula.rendered)
      }
      rendered = rendered.replaceAll(formula.token, formula.rendered)
    }
    return rendered
  } catch {
    return markdown.utils.escapeHtml(source)
  }
}
