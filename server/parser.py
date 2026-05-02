from dataclasses import dataclass
from typing import Dict, List, Optional


@dataclass
class Command: 
    verb: str
    args: List[str]
    raw: str

    def arg_str(self) -> str: 
        return " ".join(self.args)
    
class Parser: 
    VERB_SYNONYMS = {
        "look": ["look", "l", "examine", "x"],
        "go": ["go", "move", "walk", "head", "north", "south", "east", "west",
               "n", "s", "e", "w"],
        "take": ["take", "get", "grab"],
        "drop": ["drop", "discard"],
        "inventory": ["inventory", "i", "inv"],
        "quit": ["quit", "exit", "logout", "bye"],
        "help": ["help", "h", "?"],
    }

    DIRECTIONS = {"north", "south", "east", "west", "n", "s", "e", "w"}
    def __init__(self):
        self._verb_map: Dict[str, str] = {}
        for canonical, synonyms in self.VERB_SYNONYMS.items():
            for s in synonyms:
                self._verb_map[s] = canonical

    def parse(self, text: str) -> Optional[Command]:
        text = text.strip()
        if not text:
            return None
        tokens = text.lower().split()
        first = tokens[0]
        #This is to check if the first word is a known verb or synonym
        verb = self._verb_map.get(first)
        if verb is None and first in self.DIRECTIONS:
            # For example if north is typed alone, the game will treat is as "go north", maybe i can incorporate HCAI API for future use?
            return Command(verb="go", args=[first], raw=text)
        if verb is None: 
            # For unknown commands
            return Command(verb="unknown", args=tokens, raw=text)
        args = [t for t in tokens[1:] if t not in ("the", "a", "an")]
        return Command(verb=verb, args=args, raw=text)
    