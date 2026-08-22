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

  getMatches(category: keyof CompletionsData, prefix: string): string[] {
    const pool = this.data[category] || []
    if (!prefix) return pool.slice(0, 20)
    const lower = prefix.toLowerCase()
    return pool.filter(item => item.toLowerCase().startsWith(lower)).slice(0, 20)
  }

  tab(input: string, shiftKey: boolean): { newInput: string; suggestions: string[]; activeIndex: number } {
    const { slotIndex, category, prefix, verbUsed, valueStart, parts } = this.getSlotInfo(input)
    if (input !== this.lastOutput) {
      this.cycleIndex = -1
      this.commonExtended = false
      this.filteredCache = []
    }
    const previousCache = this.filteredCache
    const matches = this.getMatches(category, prefix)
    this.filteredCache = matches

    if (matches.length === 0) {
      if (this.cycleIndex >= 0 && previousCache.length > 1) {
        const cached = previousCache
        this.filteredCache = cached
        const maxIdx = cached.length - 1
        if (shiftKey) {
          this.cycleIndex = this.cycleIndex <= 0 ? maxIdx : this.cycleIndex - 1
        } else {
          this.cycleIndex = this.cycleIndex >= maxIdx ? 0 : this.cycleIndex + 1
        }
        const selected = cached[this.cycleIndex]
        return this.emit(this.replaceSlotValue(input, selected, verbUsed, parts, valueStart), cached, this.cycleIndex)
      }
      this.cycleIndex = -1
      return this.emit(input, [], -1)
    }

    const grammar = this.data.grammar[verbUsed]
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
        return this.emit(this.replaceSlotValue(input, selected, verbUsed, parts, valueStart), cached, this.cycleIndex)
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
    return this.emit(this.replaceSlotValue(input, selected, verbUsed, parts, valueStart), matches, this.cycleIndex)
  }

  private emit(newInput: string, suggestions: string[], activeIndex: number): { newInput: string; suggestions: string[]; activeIndex: number } {
    this.lastOutput = newInput
    return { newInput, suggestions, activeIndex }
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

  selectSuggestion(input: string, suggestion: string): string {
    const { slotIndex, verbUsed } = this.getSlotInfo(input)
    const grammar = this.data.grammar[verbUsed]
    const isGrammarSlot = grammar && slotIndex < grammar.length
    const sep = isGrammarSlot ? grammar[slotIndex].separator : ' '
    const result = this.replaceLastWord(input, suggestion, sep, verbUsed)
    this.cycleIndex = -1
    this.filteredCache = []
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
  }

  getSuggestions(): string[] {
    return this.filteredCache
  }

  getSuggestionCategory(input: string): string {
    const { category } = this.getSlotInfo(input)
    return category
  }
}
