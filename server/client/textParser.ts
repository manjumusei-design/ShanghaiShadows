import DOMPurify from 'dompurify'

const DEBUG = typeof localStorage !== 'undefined' ? localStorage.getItem('ssl_debug') === 'true' : false
const ALLOWED_TAGS = ['b', 'i', 'u', 'sem']
const ALLOWED_ATTR = ['type']
const KNOWN_SEMANTIC_VALUES = ['npc', 'item', 'exit']

DOMPurify.addHook('uponSanitizeAttribute', (node, data) => {
  if (
    data.attrName === 'type' &&
    node.tagName.toLowerCase() === 'sem' &&
    KNOWN_SEMANTIC_VALUES.includes(data.attrValue)
  ) {
    return
  }
  data.keepAttr = false
})
export function parseMessageText(text: string): string {
  const sanitized = DOMPurify.sanitize(text, {
    ALLOWED_TAGS,
    ALLOWED_ATTR,
  })
  if (DEBUG) console.log(`[DEBUG] parseMessageText: input="${text.substring(0, 80)}${text.length > 80 ? '...' : ''}" -> output="${sanitized.substring(0, 80)}${sanitized.length > 80 ? '...' : ''}"`)
  return sanitized
}
export function formatRoomTitle(title: string): string {
  return `<b><u>${title}</u></b>`
}
