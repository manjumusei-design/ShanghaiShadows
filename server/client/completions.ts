export type CompletionCategory = string

export type MatchPolicy = 'prefix' | 'prefix_then_substring'

export interface CompletionsData {
  [key: string]: unknown
  verbs: string[]
  npcs: string[]
  items: string[]
  exits: string[]
  topics: string[]
  players: string[]
  take_items?: string[]
  inventory_items?: string[]
  ask_topics?: Record<string, string[]>
  match_policy?: Record<string, MatchPolicy>
  grammar: Record<string, CommandSlot[]>
}

export interface CommandSlot {
  category: CompletionCategory
  separator: string
  context?: {
    collection: keyof CompletionsData
    source_slot: number
  }
}

function normalizeNpcName(value: string): string {
  return value
    .toLowerCase()
    .replace(/\b(the|a|an)\b/g, ' ')
    .replace(/[^a-z0-9 ]/g, ' ')
    .replace(/\s+/g, ' ')
    .trim()
}

function commonPrefix(candidates: string[], typed: string): string {
  const lower = typed.toLowerCase()
  let prefix = candidates[0].toLowerCase()
  for (const candidate of candidates.slice(1)) {
    const lowerCandidate = candidate.toLowerCase()
    let i = 0
    while (i < prefix.length && i < lowerCandidate.length && prefix[i] === lowerCandidate[i]) {
      i += 1
    }
    prefix = prefix.slice(0, i)
  }
  if (prefix.length <= lower.length) return lower
  return prefix
}

function getVerbPrefix(input: string, grammar: Record<string, CommandSlot[]>): string {
  const lower = input.trim().toLowerCase()
  const first = lower.split(' ')[0]
  const candidates = Object.keys(grammar).filter((verb) => verb === first || verb.startsWith(first + ' '))
  let best = first
  for (const verb of candidates) {
    if (verb === first) continue
    const separators = grammar[verb].map((slot) => slot.separator.trim()).filter(Boolean)
    let pos = verb.length
    let matched = true
    for (const sep of separators) {
      const idx = lower.indexOf(' ' + sep, pos)
      if (idx === -1) {
        matched = false
        break
      }
      pos = idx + sep.length
    }
    if (matched) {
      best = verb
      break
    }
  }
  return best
}

export class CompletionsEngine {
  private data: CompletionsData = { verbs: [], npcs: [], items: [], exits: [], topics: [], players: [], grammar: {} }
  private cycleIndex = -1
  private commonExtended = false
  private filteredCache: string[] = []
  private lastOutput = ''
  private cycleKey = ''

  updateCompletions(data: CompletionsData): void {
    this.data = data
    this.filteredCache = []
    this.cycleIndex = -1
    this.commonExtended = false
    this.lastOutput = ''
    this.cycleKey = ''
  }

  private getSlotInfo(input: string): { slotIndex: number; category: CompletionCategory; prefix: string; verbUsed: string; valueStart: number; parts: string[] } {
    const trimmed = input.trim()
    const verb = getVerbPrefix(trimmed, this.data.grammar)
    const grammar = this.data.grammar[verb]

    if (!grammar) {
      const firstWord = trimmed.split(' ')[0].toLowerCase()
      const prefix = trimmed.includes(' ') ? trimmed.split(' ').pop() || firstWord : firstWord
      const verbish = this.data.verbs.some((candidate) => {
        const head = candidate.split(' ')[0].toLowerCase()
        return head === firstWord || head.startsWith(firstWord)
      })
      if (!verbish) {
        return { slotIndex: 0, category: '', prefix: '', verbUsed: firstWord, valueStart: 0, parts: [] }
      }
      return { slotIndex: 0, category: 'verbs', prefix, verbUsed: firstWord, valueStart: 0, parts: [] }
    }

    let afterVerb = trimmed.slice(verb.split(' ')[0].length).trim()
    const verbTail = verb.split(' ').slice(1)
    for (const word of verbTail) {
      if (afterVerb.toLowerCase().startsWith(word + ' ')) {
        afterVerb = afterVerb.slice(word.length).trim()
      } else if (afterVerb.toLowerCase() === word) {
        afterVerb = ''
      }
    }
    if (!afterVerb && !input.endsWith(' ') && trimmed.toLowerCase() !== verb) {
      return { slotIndex: 0, category: 'verbs', prefix: trimmed, verbUsed: verb, valueStart: 0, parts: [] }
    }

    const parts = afterVerb.split(' ').filter(p => p.length > 0)
    if (parts.length === 0) {
      return { slotIndex: 0, category: grammar[0].category, prefix: '', verbUsed: verb, valueStart: 0, parts: [] }
    }

    let consumed = 0
    let lastSlotStart = 0
    for (let i = 0; i < grammar.length; i++) {
      const slot = grammar[i]
      const slotStart = consumed
      lastSlotStart = slotStart
      const nextSep = slot.separator.trim()

      if (consumed >= parts.length) {
        return { slotIndex: i, category: slot.category, prefix: '', verbUsed: verb, valueStart: slotStart, parts }
      }

      if (nextSep && parts[consumed].toLowerCase() === nextSep.toLowerCase()) {
        consumed++
        if (consumed >= parts.length) {
          const nextCat = i + 1 < grammar.length ? grammar[i + 1].category : slot.category
          return { slotIndex: i + 1, category: nextCat, prefix: '', verbUsed: verb, valueStart: consumed, parts }
        }
        continue
      }

      consumed++
      while (consumed < parts.length && !(nextSep && parts[consumed].toLowerCase() === nextSep.toLowerCase())) {
        consumed++
      }
      if (consumed >= parts.length) {
        return { slotIndex: i, category: slot.category, prefix: parts.slice(slotStart).join(' '), verbUsed: verb, valueStart: slotStart, parts }
      }
      consumed++
      if (consumed >= parts.length) {
        const nextCat = i + 1 < grammar.length ? grammar[i + 1].category : slot.category
        return { slotIndex: i + 1, category: nextCat, prefix: '', verbUsed: verb, valueStart: consumed, parts }
      }
    }

    const lastSlot = grammar[grammar.length - 1]
    const lastPrefix = parts.length > 0 ? parts.slice(lastSlotStart).join(' ') : ''
    return {
      slotIndex: grammar.length,
      category: lastSlot ? lastSlot.category : 'verbs',
      prefix: lastPrefix,
      verbUsed: verb,
      valueStart: lastSlotStart,
      parts,
    }
  }

  private getContextValue(parts: string[], grammar: CommandSlot[], sourceSlot: number): string {
    let start = 0
    for (let index = 0; index <= sourceSlot; index++) {
      const separator = grammar[index]?.separator.trim()
      const separatorIndex = separator
        ? parts.findIndex((part, candidateIndex) => candidateIndex >= start && part.toLowerCase() === separator.toLowerCase())
        : -1
      const end = separatorIndex === -1 ? parts.length : separatorIndex
      if (index === sourceSlot) return parts.slice(start, end).join(' ').toLowerCase()
      if (separatorIndex === -1) return ''
      start = separatorIndex + 1
    }
    return ''
  }

  private policyFor(category: CompletionCategory): MatchPolicy {
    return this.data.match_policy?.[category] === 'prefix_then_substring' ? 'prefix_then_substring' : 'prefix'
  }

  private matchPool(pool: string[], category: CompletionCategory, prefix: string): string[] {
    if (!prefix) return pool.slice()
    const lower = category === 'npcs' ? normalizeNpcName(prefix) : prefix.toLowerCase()
    const starts = pool.filter(item => {
      const candidate = category === 'npcs' ? normalizeNpcName(item) : item.toLowerCase()
      return candidate.startsWith(lower)
    })
    if (starts.length > 0 || this.policyFor(category) !== 'prefix_then_substring') return starts
    return pool.filter(item => {
      const candidate = category === 'npcs' ? normalizeNpcName(item) : item.toLowerCase()
      return candidate.includes(lower)
    })
  }

  getMatches(category: CompletionCategory, prefix: string, context?: CommandSlot['context'], parts: string[] = [], grammar: CommandSlot[] = []): string[] {
    let pool = (this.data[category] as string[] | undefined) || []
    if (context) {
      const collection = this.data[context.collection]
      const sourceValue = this.getContextValue(parts, grammar, context.source_slot)
      pool = collection && !Array.isArray(collection) && typeof collection === 'object'
        ? collection[sourceValue]
          || Object.entries(collection).find(([key]) => normalizeNpcName(key) === normalizeNpcName(sourceValue))?.[1]
          || []
        : []
    }
    return this.matchPool(pool, category, prefix)
  }

  tab(input: string, shiftKey: boolean): { newInput: string; suggestions: string[]; activeIndex: number; noMatches: boolean } {
    const { slotIndex, category, prefix, verbUsed, valueStart, parts } = this.getSlotInfo(input)
    if (input !== this.lastOutput) {
      this.cycleIndex = -1
      this.commonExtended = false
      this.filteredCache = []
      this.cycleKey = ''
    }
    const grammar = this.data.grammar[verbUsed]
    const slot = grammar?.[slotIndex]
    const slotSeparator = slot?.separator.trim() ? slot.separator : ''
    const cycleKey = this.getCycleKey(verbUsed, slotIndex, parts, valueStart)
    const continuesCycle = input === this.lastOutput && this.cycleKey === cycleKey && this.filteredCache.length > 0
    const previousCache = continuesCycle ? this.filteredCache : []
    const matches = continuesCycle ? previousCache : this.getMatches(category, prefix, slot?.context, parts, grammar)
    if (!continuesCycle) {
      this.filteredCache = matches
      this.cycleKey = cycleKey
    }
    const exactGrammarVerb = Boolean(grammar) && input.trim().toLowerCase() === verbUsed.toLowerCase() && !input.endsWith(' ')

    if (exactGrammarVerb) {
      this.cycleIndex = -1
      this.commonExtended = true
      return this.emit(`${input} `, matches, -1)
    }

    if (matches.length === 0) {
      this.cycleIndex = -1
      return this.emit(input, [], -1, true)
    }

    const isGrammarSlot = grammar && slotIndex < grammar.length
    const sep = isGrammarSlot ? grammar[slotIndex].separator : ' '

    if (matches.length === 1) {
      const currentValue = parts.slice(valueStart).join(' ').toLowerCase()
      if (this.cycleIndex >= 0 && previousCache.length > 1 && matches[0] === currentValue) {
        const cached = previousCache
        this.filteredCache = cached
        const maxIdx = cached.length - 1
        if (shiftKey) {
          this.cycleIndex = this.cycleIndex <= 0 ? maxIdx : this.cycleIndex - 1
        } else {
          this.cycleIndex = this.cycleIndex >= maxIdx ? 0 : this.cycleIndex + 1
        }
        const selected = cached[this.cycleIndex]
        return this.emit(this.replaceSlotCandidate(input, selected, verbUsed, parts, valueStart, slotSeparator), cached, this.cycleIndex)
      }
      this.cycleIndex = -1
      this.commonExtended = false
      const newInput = this.replaceSlotValue(input, matches[0], verbUsed, parts, valueStart) + (isGrammarSlot ? sep : ' ')
      return this.emit(newInput, [], -1)
    }

    if (this.cycleIndex === -1 && !this.commonExtended && !shiftKey) {
      const shared = commonPrefix(matches, prefix)
      if (shared) {
        this.commonExtended = true
        const newInput = shared === prefix ? input : this.replaceSlotValue(input, shared, verbUsed, parts, valueStart)
        return this.emit(newInput, matches, -1)
      }
    }

    this.commonExtended = false
    const maxIdx = matches.length - 1
    if (shiftKey) {
      this.cycleIndex = this.cycleIndex <= 0 ? maxIdx : this.cycleIndex - 1
    } else {
      this.cycleIndex = this.cycleIndex >= maxIdx ? 0 : this.cycleIndex + 1
    }

    const selected = matches[this.cycleIndex]
    return this.emit(this.replaceSlotCandidate(input, selected, verbUsed, parts, valueStart, slotSeparator), matches, this.cycleIndex)
  }

  private emit(newInput: string, suggestions: string[], activeIndex: number, noMatches = false): { newInput: string; suggestions: string[]; activeIndex: number; noMatches: boolean } {
    this.lastOutput = newInput
    return { newInput, suggestions, activeIndex, noMatches }
  }

  private replaceSlotValue(input: string, replacement: string, verbUsed: string, parts: string[], valueStart: number): string {
    const trimmed = input.trim()
    const lowerTrimmed = trimmed.toLowerCase()
    let verbText = ''
    if (lowerTrimmed.startsWith(verbUsed.toLowerCase())) {
      verbText = trimmed.slice(0, verbUsed.length)
    } else {
      verbText = trimmed.split(' ')[0]
    }
    const preserved = parts.slice(0, valueStart)
    const tail = preserved.length > 0 ? ' ' + preserved.join(' ') + ' ' : ' '
    return verbText + tail + replacement
  }

  private replaceSlotCandidate(input: string, replacement: string, verbUsed: string, parts: string[], valueStart: number, separator: string): string {
    return this.replaceSlotValue(input, replacement, verbUsed, parts, valueStart) + separator
  }

  private getCycleKey(verbUsed: string, slotIndex: number, parts: string[], valueStart: number): string {
    return `${verbUsed.toLowerCase()}|${slotIndex}|${parts.slice(0, valueStart).join(' ').toLowerCase()}`
  }

  selectSuggestion(input: string, suggestion: string): string {
    const { slotIndex, category, verbUsed, valueStart, parts } = this.getSlotInfo(input)
    const grammar = this.data.grammar[verbUsed]
    const isGrammarSlot = grammar && slotIndex < grammar.length
    const sep = isGrammarSlot ? grammar[slotIndex].separator : ' '
    if (isGrammarSlot) {
      const slot = grammar[slotIndex]
      const candidates = this.getMatches(category, '', slot.context, parts, grammar)
      const result = this.replaceSlotCandidate(input, suggestion, verbUsed, parts, valueStart, sep)
      this.filteredCache = candidates
      this.cycleKey = this.getCycleKey(verbUsed, slotIndex, parts, valueStart)
      this.cycleIndex = candidates.indexOf(suggestion)
      this.commonExtended = true
      this.lastOutput = result
      return result
    }
    const result = this.replaceLastWord(input, suggestion, sep, verbUsed)
    this.cycleIndex = -1
    this.filteredCache = []
    this.cycleKey = ''
    return result
  }

  private replaceLastWord(input: string, replacement: string, suffix: string, verbUsed: string): string {
    const trimmedInput = input.trim()
    const lowerTrimmed = trimmedInput.toLowerCase()
    const verbText = lowerTrimmed.startsWith(verbUsed.toLowerCase()) ? verbUsed : trimmedInput.split(' ')[0]
    const remainder = input.slice(verbText.length)
    const trimmed = remainder.trim()
    const lastSpace = trimmed.lastIndexOf(' ')
    if (lastSpace === -1) {
      if (verbText && (trimmedInput !== verbText || input.endsWith(' '))) {
        return verbText + ' ' + replacement + suffix
      }
      return replacement + suffix
    }
    const before = trimmed.slice(0, lastSpace)
    const lastWord = trimmed.slice(lastSpace + 1)
    const lowerSep = suffix.trim().toLowerCase()
    if (lastWord.toLowerCase() === lowerSep) {
      return verbText + ' ' + before + ' ' + lastWord + ' ' + replacement
    }
    return verbText + ' ' + before + ' ' + replacement + suffix
  }

  resetCycle(): void {
    this.cycleIndex = -1
    this.commonExtended = false
    this.filteredCache = []
    this.lastOutput = ''
    this.cycleKey = ''
  }

  getSuggestions(): string[] {
    return this.filteredCache
  }

  getSuggestionCategory(input: string): string {
    const { category } = this.getSlotInfo(input)
    return category
  }
}
