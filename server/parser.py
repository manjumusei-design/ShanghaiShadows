from dataClasses import dataclass
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
        "quit": ["quit", "exit", "logout", "bye"],
        "help": ["help", "h", "?"],
        "inventory": ["inventory", "i", "inv"],
    }

    