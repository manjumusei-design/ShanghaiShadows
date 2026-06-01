import shlex
from dataclasses import dataclass
from typing import List, Optional


@dataclass
class Command: 
    verb: str
    direct_obj: Optional[str] = None
    indirect_obj: Optional[str] = None
    preposition: Optional[str] = None]
    raw: str = ""


ARTICLES = {"the", "a", "an"}
PREPOSITIONS = {"to", "at", "on", "with", "in", "from", "about"}
DIRECTIONS = {"north", "south", "east", "west", "up", "down", "n", "s", "e", "w", "u", "d"}

VERB_ALIASES = {
    "l": "look",
    "x": "look",
    "examine" : "look",
    "i": "inventory",
    "inv": "inventory",
    "get": "take",
    "grab": "take",
    "discard": "drop",
    "move": "go",
    "walk": "go",
    "head": "go",
    "exit": "quit",
    "logout": "quit",
    "bye": "quit",
    "h": "help",
    "?": "help",
    "stat": "status",
}   

KNOWN_VERBS = {
    "look",
    "go",
    "take",
    "drop",
    "inventory",
    "quit",
    "help",
    "talk to",
    "ask",
    "ask about",
    "whisper"
    "give",
    "plant",
    "disguise as",
    "hide",
    "read",
    "use",
    "wait",
    "sleep",
    "eat",
    "rest",
    "journal",
    "status",
    "tail",
    "bond",
    "say",
    "attack",
}


def _strip_articles(tokens: List[str]) -> List[str]:
    return [t for t in tokens if t.lower() not in ARTICLES]


def _resolve_verb(word: str) -> str:
    word = word.lower()
    if word in DIRECTIONS:
        return "go"
    resolved = VERB_ALIASES.get(word, word)
    if resolved not in KNOWN_VERBS:
        return resolved
    return resolved


def tokenize(text: str) -> List[str]:
    try:
        return shlex.split(text)
    except ValueError:
        return text.split()


def parse(text: str) -> Command:
    raw = text.strip()
    tokens = tokenize(raw)
    if not tokens:
        return Command(verb="pass", raw=raw)
    first = tokens[0].lower()

    if first == "talk" and len(tokens) > 2 and tokens[1].lower() == "to":
        rest = _strip_articles(tokens[2:])
        direct = " ".join(rest) if rest else None
        return Command(verb="talk to", direct_obj=direct, raw=raw)

    if first == "disguise" and len(tokens) > 2 and tokens[1].lower() == "as":
        rest = _strip_articles(tokens[2:])
        direct = " ".join(rest) if rest else None
        return Command(verb="disguise as", direct_obj=direct, raw=raw)
    
    if first == "ask" and len(tokens) > 2 and tokens[1].lower() == "about": 
        rest = _strip_articles(tokens[2:])
        direct = " ".join(rest) if rest else None
        return Command(verb="ask about", direct_obj=direct, raw=raw)
    
    if first == "whisper" and len(tokens) > 2:
        direct = tokens[1]
        indirect = " ".join(tokens[2:])
        return Command(verb="whisper", direct_obj=direct, indirect_obj=indirect, raw=raw)

    verb = _resolve_verb(first)
    rest  = tokens[1:]

    if verb == "go" and first in DIRECTIONS:
        return Command(verb="go", direct_obj=first, raw=raw)
    
    prep_idx = next(
        (i for i , t in enumerate(rest) if t.lower() in PREPOSITIONS), None
    )

    if prep_idx is not None:
        direct_tokens = rest[:prep_idx]
        direct = " ".join(_strip_articles(direct_tokens)) if direct_tokens else None
        prep = rest[prep_idx].lower()
        indirect_tokens = rest[prep_idx + 1:]
        indirect = " ".join(_strip_articles(indirect_tokens)) if indirect_tokens else None
        return Command(
            verb=verb,
            direct_obj=direct,
            preposition=prep,
            indirect_obj=indirect,
            raw=raw,
        )
    else: 
        direct = " ".join(_strip_articles(rest)) if rest else None
        return Command(verb=verb, direct_obj=direct, raw=raw)
