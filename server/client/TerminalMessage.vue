<template>
  <span class="terminal-message" @click="skipReveal">
    <span v-html="renderedHtml"></span><span v-if="isRevealing" class="terminal-cursor" aria-hidden="true">▌</span>
  </span>
</template>

<script lang="ts">
import { computed, defineComponent, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { parseMessageText } from '@/core/textParser'

const REVEAL_TYPES = new Set(['room', 'npc', 'social', 'ambient', 'npc_ambient'])
const BASE_DELAY_MS = 18
const PAUSE_AFTER_COMMA_MS = 70
const PAUSE_AFTER_SENTENCE_MS = 120
const PAUSE_AFTER_PARAGRAPH_MS = 160
const INSTANT_TEXT_STORAGE_KEY = 'ss_instant_text'

type Token =
  | { kind: 'tag'; value: string }
  | { kind: 'text'; value: string }

function decodeText(text: string): string {
  if (typeof document === 'undefined') return text
  const area = document.createElement('textarea')
  area.innerHTML = text
  return area.value
}

function tokenize(html: string): Token[] {
  const tokens: Token[] = []
  const tagPattern = /<[^>]*>/g
  let cursor = 0
  for (const match of html.matchAll(tagPattern)) {
    const index = match.index ?? cursor
    if (index > cursor) {
      for (const value of Array.from(decodeText(html.slice(cursor, index)))) {
        tokens.push({ kind: 'text', value })
      }
    }
    tokens.push({ kind: 'tag', value: match[0] })
    cursor = index + match[0].length
  }
  if (cursor < html.length) {
    for (const value of Array.from(decodeText(html.slice(cursor)))) {
      tokens.push({ kind: 'text', value })
    }
  }
  return tokens
}

function escapeText(text: string): string {
  return text
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;')
}

function tagName(tag: string): string | null {
  const match = tag.match(/^<\s*\/?\s*([a-z0-9]+)/i)
  return match ? match[1].toLowerCase() : null
}

function isClosingTag(tag: string): boolean {
  return /^<\s*\//.test(tag)
}

function isSelfClosingTag(tag: string): boolean {
  return /\/\s*>$/.test(tag)
}

function buildPrefix(tokens: Token[], visibleCount: number, totalText: number): string {
  if (visibleCount >= totalText) {
    return tokens.map(token => token.value).join('')
  }

  let output = ''
  let revealed = 0
  const openTags: string[] = []

  for (const token of tokens) {
    if (token.kind === 'tag') {
      if (revealed > visibleCount) break
      output += token.value
      const name = tagName(token.value)
      if (name && !isSelfClosingTag(token.value)) {
        if (isClosingTag(token.value)) {
          const index = openTags.lastIndexOf(name)
          if (index >= 0) openTags.splice(index, 1)
        } else {
          openTags.push(name)
        }
      }
      continue
    }
    if (revealed >= visibleCount) break
    output += escapeText(token.value)
    revealed += 1
  }

  for (let index = openTags.length - 1; index >= 0; index -= 1) {
    output += `</${openTags[index]}>`
  }
  return output
}

function prefersReducedMotion(): boolean {
  if (typeof window === 'undefined' || typeof window.matchMedia !== 'function') return false
  try {
    return window.matchMedia('(prefers-reduced-motion: reduce)').matches
  } catch {
    return false
  }
}

function instantTextPreference(): boolean {
  try {
    return typeof localStorage !== 'undefined' && localStorage.getItem(INSTANT_TEXT_STORAGE_KEY) === 'true'
  } catch {
    return false
  }
}

export default defineComponent({
  name: 'TerminalMessage',
  props: {
    text: { type: String, required: true },
    type: { type: String, required: true },
    instantText: { type: Boolean, default: false },
  },
  emits: {
    'reveal-state': (active: boolean) => typeof active === 'boolean',
    'reveal-progress': (count: number) => typeof count === 'number',
  },
  setup(props, { emit, expose }) {
    const isRevealing = ref(false)
    const visibleCount = ref(0)
    const reducedMotion = ref(false)
    let timer: number | null = null
    let mounted = false

    const safeHtml = computed(() => parseMessageText(props.text))
    const tokens = computed(() => tokenize(safeHtml.value))
    const visibleChars = computed(() => tokens.value
      .filter(token => token.kind === 'text')
      .map(token => token.value))
    const renderedHtml = computed(() => buildPrefix(tokens.value, visibleCount.value, visibleChars.value.length))

    const clearTimer = () => {
      if (timer !== null) {
        window.clearTimeout(timer)
        timer = null
      }
    }

    const completeReveal = () => {
      clearTimer()
      visibleCount.value = visibleChars.value.length
      if (isRevealing.value) {
        isRevealing.value = false
        emit('reveal-state', false)
      }
    }

    const delayAfter = (index: number): number => {
      const current = visibleChars.value[index]
      if (current === '\n' && visibleChars.value[index - 1] === '\n') return PAUSE_AFTER_PARAGRAPH_MS
      if (current === ',' || current === ';') return PAUSE_AFTER_COMMA_MS
      if ('.?!。！？'.includes(current)) return PAUSE_AFTER_SENTENCE_MS
      return BASE_DELAY_MS
    }

    const scheduleNext = () => {
      if (!isRevealing.value) return
      clearTimer()
      const currentIndex = visibleCount.value - 1
      timer = window.setTimeout(() => {
        visibleCount.value += 1
        emit('reveal-progress', visibleCount.value)
        if (visibleCount.value >= visibleChars.value.length) {
          completeReveal()
          return
        }
        scheduleNext()
      }, delayAfter(currentIndex))
    }

    const startReveal = () => {
      clearTimer()
      visibleCount.value = 0
      const immediate = !REVEAL_TYPES.has(props.type)
        || props.instantText
        || instantTextPreference()
        || reducedMotion.value
        || visibleChars.value.length === 0
      if (immediate) {
        isRevealing.value = false
        visibleCount.value = visibleChars.value.length
        emit('reveal-state', false)
        return
      }
      isRevealing.value = true
      emit('reveal-state', true)
      scheduleNext()
    }

    const skipReveal = () => {
      if (isRevealing.value) completeReveal()
    }

    onMounted(() => {
      mounted = true
      reducedMotion.value = prefersReducedMotion()
      startReveal()
    })

    watch(() => [props.text, props.type, props.instantText], () => {
      if (mounted) startReveal()
    })

    onBeforeUnmount(clearTimer)
    expose({ isRevealing, skipReveal })

    return { isRevealing, renderedHtml, skipReveal }
  },
})
</script>

<style scoped>
.terminal-cursor {
  display: inline-block;
  margin-left: 1px;
  animation: terminal-cursor-blink 800ms steps(1) infinite;
}

@keyframes terminal-cursor-blink {
  0%, 49% { opacity: 1; }
  50%, 100% { opacity: 0; }
}

@media (prefers-reduced-motion: reduce) {
  .terminal-cursor { animation: none; }
}
</style>
