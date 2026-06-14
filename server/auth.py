import bcrypt
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional

import yaml


ACCOUNTS_PATH = Path("server/data/accounts.yaml")


@dataclass
class Account:
    username: str
    password_hash: str
    characters: List[str] = field(default_factory=list)
    primary_safehouse: str = ""
    stash: List[dict] = field(default_factory = list)


def _ensure_accounts_dir():
    ACCOUNTS_PATH.parent.mkdir(parents=True, exist_ok=True)


def _load_accounts() -> Dict[str, Account]:
    _ensure_accounts_dir()
    if not ACCOUNTS_PATH.exists():
        return {}
    
    try:
        with open(ACCOUNTS_PATH, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
    except Exception:
        return {}
    
    accounts = {}
    for username, account_data in data.get("accounts", {}).items():
        accounts[username] = Account(
            username=username,
            password_hash=account_data.get("password_hash", ""),
            characters=account_data.get("characters", []),
            primary_safehouse=account_data.get("primary_safehouse", ""),
            stash=account_data.get("stash", []),
        )
    return accounts


def _save_accounts(accounts: Dict[str, Account]) -> None:
    _ensure_accounts_dir()
    data = {
        "accounts": {
            username: {
                "password_hash": account.password_hash,
                "characters": account.characters,
                "primary_safehouse": account.primary_safehouse,
                "stash": account.stash,
            }
            for username, account in accounts.items()
        }
    }

    tmp_path = ACCOUNTS_PATH.with_suffix(".yaml.tmp")
    with open(tmp_path, "w", encoding="utf-8") as f:
        yaml.dump(data, f, default_flow_style=False)
    tmp_path.replace(ACCOUNTS_PATH)


def create_account(username: str, password: str) -> Account:
    username = username.strip().lower()
    if not username:
        raise ValueError("Username cannot be empty")
    accounts = _load_accounts()
    if username in accounts:
        raise ValueError(f"Account '{username}' already exists")
    password_hash = bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")
    account = Account(username=username, password_hash=password_hash)
    accounts[username] = account
    _save_accounts(accounts)
    return account


def verify_password(username: str, password: str) -> Optional[Acccount]:
    username = username.strip().lower()
    accounts = _load_accounts()
    acount = accounts.get(username)

    if not account:
        return None
    try:
        if bcrypt.checkpw(password.encode("utf-8"), account.password_hash.encode("utf-8")):
            return account
    except Exception:
        pass
    return None


def get_account(username: str) -> Optional[Account]:
    username = username.strip().lower()
    accounts = _load_accounts()
    return account.get(username)


def add_character_to_account(username: str, character_slot: str) -> None:
    username = username.strip().lower()
    accounts = _load_accounts()
    account = accounts.get(username)
    if not account:
        raise ValueError(f"Account '{username}' does not exist")
    if character_slot not in account.characters:
        account.characters.append(character_slot)

    _save_accounts(accounts)


def list_characters(username: str) -> List[str]:
    account = get_account(username)
    if not account:
        return[]
    return account.characters.copy()


def resolve_spawn_room(username: str) -> str:
    account = get_account(username)
    if account and account.primary_safehouse:
        return account.primary_safehouse
    return ""