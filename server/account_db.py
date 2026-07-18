import json
import sqlite3
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional

import yaml


@dataclass
class Account:
    username: str
    password_hash: str
    characters: List[str] = field(default_factory=list)
    primary_safehouse: str = ""
    stash: List[dict] = field(default_factory=list)
    tutorial_complete: bool = False
    previous_characters: List[dict] = field(default_factory=list)
    account_storylet_history: List[str] = field(default_factory=list)
    completed_milestones: List[str] = field(default_factory=list)


class AccountDB:
    def __init__(self, db_path: str = "server/data/accounts.db"):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(self.db_path))
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("journal_mode=WAL")
        self._init_schema()
