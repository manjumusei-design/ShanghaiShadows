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
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._init_schema()

    def _init_schema(self):
        self._conn.execute(
            """
            CREATE TABLE IF NOT EXISTS accounts (
                username TEXT PRIMARY KEY,
                password_hash TEXT NOT NULL,
                characters TEXT NOT NULL DEFAULT '[]',
                primary_safehouse TEXT NOT NULL DEFAULT '',
                stash TEXT NOT NULL DEFAULT '[]',
                tutorial_complete INTEGER NOT NULL DEFAULT 0
            )
            """
        )
        try:
            self._conn.execute("ALTER TABLE accounts ADD COLUMN tutorial_complete INTEGER NOT NULL DEFAULT 0")
        except sqlite3.OperationalError:
            pass
        try:
            self._conn.execute("ALTER TABLE accounts ADD COLUMN previous_characters TEXT NOT NULL DEFAULT '[]'")
        except sqlite3.OperationalError:
            pass
        try:
            self._conn.execute("ALTER TABLE accounts ADD COLUMN account_storylet_history TEXT NOT NULL DEFAULT '[]'")
        except sqlite3.OperationalError:
            pass
        try:
            self._conn.execute("ALTER TABLE accounts ADD COLUMN completed_milestones TEXT NOT NULL DEFAULT '[]'")
        except sqlite3.OperationalError:
            pass
        self._conn.execute(
            """
            CREATE TABLE IF NOT EXISTS character_slots (
                slot_id TEXT PRIMARY KEY,
                account_username TEXT NOT NULL,
                slot_number INTEGER NOT NULL,
                display_name TEXT NOT NULL,
                status TEXT NOT NULL CHECK (status IN ('living', 'dead', 'unavailable')),
                save_key TEXT NOT NULL UNIQUE,
                unavailable_reason TEXT NOT NULL DEFAULT '',
                UNIQUE (account_username, slot_number)
            )
            """
        )
        self._conn.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS one_living_character_slot ON character_slots(account_username) WHERE status = 'living'"
        )
        self._conn.execute(
            """
            CREATE TABLE IF NOT EXISTS lifecycle_events (
                event_id TEXT PRIMARY KEY,
                event_type TEXT NOT NULL,
                payload_json TEXT NOT NULL,
                projected_world INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL
            )
            """
        )
        self._conn.execute(
            """
            CREATE TABLE IF NOT EXISTS death_journal_claims (
                event_id TEXT PRIMARY KEY,
                claimant_slot_id TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'claimed',
                knowledge_json TEXT NOT NULL,
                created_at TEXT NOT NULL
            )
            """
        )
        self._conn.execute(
            """
            CREATE TABLE IF NOT EXISTS stash_transfers (
                transfer_id TEXT PRIMARY KEY,
                account_username TEXT NOT NULL,
                slot_id TEXT NOT NULL,
                items_json TEXT NOT NULL,
                created_at TEXT NOT NULL
            )
            """
        )
        self._conn.execute(
            """
            CREATE TABLE IF NOT EXISTS storylet_cancellations (
                event_id TEXT PRIMARY KEY,
                account_username TEXT NOT NULL,
                slot_id TEXT NOT NULL,
                save_key TEXT NOT NULL,
                payload_json TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'pending',
                created_at TEXT NOT NULL,
                sequence INTEGER NOT NULL DEFAULT 0
            )
            """
        )
        try:
            self._conn.execute("ALTER TABLE storylet_cancellations ADD COLUMN sequence INTEGER NOT NULL DEFAULT 0")
        except sqlite3.OperationalError:
            pass
        self._conn.commit()

    @staticmethod
    def _slot_from_row(row):
        if row is None:
            return None
        from .lifecycle import CharacterSlot
        return CharacterSlot(
            slot_id=row["slot_id"],
            account_username=row["account_username"],
            slot_number=int(row["slot_number"]),
            display_name=row["display_name"],
            status=row["status"],
            save_key=row["save_key"],
            unavailable_reason=row["unavailable_reason"] or "",
        )

    def get_account(self, username: str) -> Optional[Account]:
        row = self._conn.execute(
            "SELECT username, password_hash, characters, primary_safehouse, tutorial_complete,"
            " previous_characters, account_storylet_history, completed_milestones FROM accounts WHERE username = ?",
            (username,),
        ).fetchone()
        if not row:
            return None
        return Account(
            username=row["username"],
            password_hash=row["password_hash"],
            characters=json.loads(row["characters"]),
            primary_safehouse=row["primary_safehouse"],
            tutorial_complete=bool(row["tutorial_complete"]),
            previous_characters=json.loads(row["previous_characters"] or "[]"),
            account_storylet_history=json.loads(row["account_storylet_history"] or "[]"),
            completed_milestones=json.loads(row["completed_milestones"] or "[]"),
        )

    def get_stash(self, username: str) -> List[dict]:
        row = self._conn.execute(
            "SELECT stash FROM accounts WHERE username = ?", (username,)
        ).fetchone()
        if not row:
            return []
        return json.loads(row["stash"])

    def set_stash(self, username: str, stash: List[dict]):
        self._conn.execute(
            "UPDATE accounts SET stash = ? WHERE username = ?",
            (json.dumps(stash), username),
        )
        self._conn.commit()

    def insert_stash_transfer(self, transfer_id: str, account_username: str, slot_id: str, items_json: str, created_at: str):
        self._conn.execute(
            "INSERT OR REPLACE INTO stash_transfers (transfer_id, account_username, slot_id, items_json, created_at) VALUES (?, ?, ?, ?, ?)",
            (transfer_id, account_username, slot_id, items_json, created_at),
        )
        self._conn.commit()

    def list_stash_transfers(self, account_username: str, slot_id: Optional[str] = None) -> List[dict]:
        if slot_id:
            rows = self._conn.execute(
                "SELECT transfer_id, account_username, slot_id, items_json, created_at FROM stash_transfers WHERE account_username = ? AND slot_id = ? ORDER BY created_at",
                (account_username, slot_id),
            ).fetchall()
        else:
            rows = self._conn.execute(
                "SELECT transfer_id, account_username, slot_id, items_json, created_at FROM stash_transfers WHERE account_username = ? ORDER BY created_at",
                (account_username,),
            ).fetchall()
        return [
            {
                "transfer_id": row["transfer_id"],
                "account_username": row["account_username"],
                "slot_id": row["slot_id"],
                "items_json": row["items_json"],
                "created_at": row["created_at"],
            }
            for row in rows
        ]

    def delete_stash_transfer(self, transfer_id: str):
        self._conn.execute(
            "DELETE FROM stash_transfers WHERE transfer_id = ?",
            (transfer_id,),
        )
        self._conn.commit()

    def create_account(self, username: str, password_hash: str):
        self._conn.execute(
            "INSERT INTO accounts (username, password_hash) VALUES (?, ?)",
            (username, password_hash),
        )
        self._conn.commit()

    def add_character(self, username: str, slot: str):
        row = self._conn.execute(
            "SELECT characters FROM accounts WHERE username = ?", (username,)
        ).fetchone()
        if not row:
            raise ValueError(f"Account '{username}' does not exist")
        chars = json.loads(row["characters"])
        if slot not in chars:
            chars.append(slot)
        self._conn.execute(
            "UPDATE accounts SET characters = ? WHERE username = ?",
            (json.dumps(chars), username),
        )
        self._conn.commit()

    def create_character_slot(self, username: str, display_name: str, status: str = "living", unavailable_reason: str = ""):
        from .lifecycle import SLOT_STATUSES
        if status not in SLOT_STATUSES:
            raise ValueError("invalid character slot status")
        account_username = username.strip().lower()
        if not self.account_exists(account_username):
            raise ValueError(f"Account '{username}' does not exist")
        row = self._conn.execute(
            "SELECT COALESCE(MAX(slot_number), 0) + 1 AS next_number FROM character_slots WHERE account_username = ?",
            (account_username,),
        ).fetchone()
        slot_number = int(row["next_number"])
        slot_id = str(uuid.uuid4())
        save_key = f"slot_{slot_id}"
        try:
            self._conn.execute(
                "INSERT INTO character_slots (slot_id, account_username, slot_number, display_name, status, save_key, unavailable_reason) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (slot_id, account_username, slot_number, display_name or "Stranger", status, save_key, unavailable_reason or ""),
            )
            self._conn.commit()
        except sqlite3.IntegrityError as exc:
            self._conn.rollback()
            if "one_living_character_slot" in str(exc) or "UNIQUE constraint failed: character_slots.account_username" in str(exc):
                raise ValueError("account already has a living character slot") from exc
            raise
        return self.get_character_slot_by_id(slot_id)

    def list_character_slots(self, username: str):
        account_username = username.strip().lower()
        rows = self._conn.execute(
            "SELECT slot_id, account_username, slot_number, display_name, status, save_key, unavailable_reason FROM character_slots WHERE account_username = ? ORDER BY slot_number",
            (account_username,),
        ).fetchall()
        return [self._slot_from_row(row) for row in rows]

    def get_character_slot(self, username: str, slot_number: int):
        account_username = username.strip().lower()
        row = self._conn.execute(
            "SELECT slot_id, account_username, slot_number, display_name, status, save_key, unavailable_reason FROM character_slots WHERE account_username = ? AND slot_number = ?",
            (account_username, int(slot_number)),
        ).fetchone()
        return self._slot_from_row(row)

    def get_character_slot_by_id(self, slot_id: str):
        row = self._conn.execute(
            "SELECT slot_id, account_username, slot_number, display_name, status, save_key, unavailable_reason FROM character_slots WHERE slot_id = ?",
            (slot_id,),
        ).fetchone()
        return self._slot_from_row(row)

    def get_character_slot_by_save_key(self, username: str, save_key: str):
        account_username = username.strip().lower()
        row = self._conn.execute(
            "SELECT slot_id, account_username, slot_number, display_name, status, save_key, unavailable_reason FROM character_slots WHERE account_username = ? AND save_key = ?",
            (account_username, save_key),
        ).fetchone()
        return self._slot_from_row(row)

    def get_living_character_slot(self, username: str):
        account_username = username.strip().lower()
        row = self._conn.execute(
            "SELECT slot_id, account_username, slot_number, display_name, status, save_key, unavailable_reason FROM character_slots WHERE account_username = ? AND status = 'living'",
            (account_username,),
        ).fetchone()
        return self._slot_from_row(row)

    def rename_character_slot(self, username: str, slot_number: int, display_name: str):
        account_username = username.strip().lower()
        slot = self.get_character_slot(account_username, slot_number)
        if slot is None:
            raise ValueError("character slot does not exist")
        self._conn.execute(
            "UPDATE character_slots SET display_name = ? WHERE account_username = ? AND slot_number = ?",
            (display_name or "Stranger", account_username, int(slot_number)),
        )
        self._conn.commit()
        return self.get_character_slot(account_username, slot_number)

    def _write_character_slot_status(self, account_username: str, slot_number: int, status: str, unavailable_reason: str = ""):
        try:
            self._conn.execute(
                "UPDATE character_slots SET status = ?, unavailable_reason = ? WHERE account_username = ? AND slot_number = ?",
                (status, unavailable_reason or "", account_username, int(slot_number)),
            )
            self._conn.commit()
        except sqlite3.IntegrityError as exc:
            self._conn.rollback()
            raise ValueError("account already has a living character slot") from exc
        return self.get_character_slot(account_username, slot_number)

    def set_character_slot_status(self, username: str, slot_number: int, status: str, unavailable_reason: str = ""):
        from .lifecycle import SLOT_STATUSES
        if status not in SLOT_STATUSES:
            raise ValueError("invalid character slot status")
        account_username = username.strip().lower()
        current = self.get_character_slot(account_username, slot_number)
        if current is None:
            raise ValueError("character slot does not exist")
        if current.status in ("dead", "unavailable") and status == "living":
            raise ValueError("dead or unavailable character slots cannot be revived")
        return self._write_character_slot_status(account_username, slot_number, status, unavailable_reason)

    def activate_projected_character_slot(self, username: str, slot_number: int):
        account_username = username.strip().lower()
        current = self.get_character_slot(account_username, slot_number)
        if current is None:
            raise ValueError("character slot does not exist")
        if current.status != "unavailable" or current.unavailable_reason not in (
            "legacy_projection_pending",
            "slot_projection_pending",
            "slot_projection_failed",
        ):
            raise ValueError("character slot is not awaiting projection")
        return self._write_character_slot_status(account_username, slot_number, "living")

    def delete_account(self, username: str):
        account_username = username.strip().lower()
        self._conn.execute("DELETE FROM character_slots WHERE account_username = ?", (account_username,))
        self._conn.execute("DELETE FROM accounts WHERE username = ?", (account_username,))
        self._conn.commit()

    def set_safehouse(self, username: str, room_id: str):
        self._conn.execute(
            "UPDATE accounts SET primary_safehouse = ? WHERE username = ?",
            (room_id, username),
        )
        self._conn.commit()

    def set_tutorial_complete(self, username: str, value: bool) -> None:
        self._conn.execute(
            "UPDATE accounts SET tutorial_complete = ? WHERE username = ?",
            (1 if value else 0, username),
        )
        self._conn.commit()

    def get_lifecycle_event(self, event_id: str) -> Optional[dict]:
        row = self._conn.execute(
            "SELECT event_id, event_type, payload_json, projected_world, created_at FROM lifecycle_events WHERE event_id = ?",
            (event_id,),
        ).fetchone()
        if not row:
            return None
        return {
            "event_id": row["event_id"],
            "event_type": row["event_type"],
            "payload_json": row["payload_json"],
            "projected_world": bool(row["projected_world"]),
            "created_at": row["created_at"],
        }

    def list_unprojected_lifecycle_events(self) -> List[dict]:
        rows = self._conn.execute(
            "SELECT event_id, event_type, payload_json, projected_world, created_at FROM lifecycle_events WHERE projected_world = 0 ORDER BY created_at"
        ).fetchall()
        return [
            {
                "event_id": row["event_id"],
                "event_type": row["event_type"],
                "payload_json": row["payload_json"],
                "projected_world": bool(row["projected_world"]),
                "created_at": row["created_at"],
            }
            for row in rows
        ]

    def mark_lifecycle_event_projected(self, event_id: str) -> None:
        self._conn.execute(
            "UPDATE lifecycle_events SET projected_world = 1 WHERE event_id = ?",
            (event_id,),
        )
        self._conn.commit()

    def archive_death_transaction(self, event: dict) -> bool:
        from .lifecycle import _stash_payload_granted
        with self._conn:
            existing = self._conn.execute(
                "SELECT 1 FROM lifecycle_events WHERE event_id = ?",
                (event["event_id"],),
            ).fetchone()
            if existing is not None:
                return True
            row = self._conn.execute(
                "SELECT status FROM character_slots WHERE slot_id = ? AND account_username = ? AND save_key = ?",
                (event["slot_id"], event["account_username"], event["save_key"]),
            ).fetchone()
            if row is None or row["status"] != "living":
                return False
            account = self._conn.execute(
                "SELECT previous_characters, stash FROM accounts WHERE username = ?",
                (event["account_username"],),
            ).fetchone()
            if account is None:
                return False
            predecessor_list = json.loads(account["previous_characters"] or "[]")
            if event["event_id"] not in [entry.get("event_id") for entry in predecessor_list]:
                predecessor_list.append(event["predecessor"])
            stash = json.loads(account["stash"] or "[]")
            transfer_rows = self._conn.execute(
                "SELECT transfer_id, items_json FROM stash_transfers WHERE account_username = ? AND slot_id = ?",
                (event["account_username"], event["slot_id"]),
            ).fetchall()
            for transfer in transfer_rows:
                for payload in json.loads(transfer["items_json"]):
                    if not _stash_payload_granted(payload, event["inherited"]):
                        continue
                    index = next((i for i, entry in enumerate(stash) if entry == payload), None)
                    if index is not None:
                        stash.pop(index)
                self._conn.execute(
                    "DELETE FROM stash_transfers WHERE transfer_id = ?",
                    (transfer["transfer_id"],),
                )
            stash.extend(event["inherited"])
            self._conn.execute(
                "INSERT OR IGNORE INTO lifecycle_events (event_id, event_type, payload_json, projected_world, created_at) VALUES (?, ?, ?, 0, ?)",
                (event["event_id"], event["event_type"], json.dumps(event["payload"]), event["created_at"]),
            )
            self._conn.execute(
                "UPDATE character_slots SET status = 'dead', unavailable_reason = 'gameplay_death' WHERE slot_id = ? AND account_username = ? AND save_key = ? AND status = 'living'",
                (event["slot_id"], event["account_username"], event["save_key"]),
            )
            self._conn.execute(
                "UPDATE accounts SET previous_characters = ?, stash = ? WHERE username = ?",
                (json.dumps(predecessor_list), json.dumps(stash), event["account_username"]),
            )
        return True

    def get_storylet_cancellation(self, event_id: str) -> Optional[dict]:
        row = self._conn.execute(
            "SELECT event_id, account_username, slot_id, save_key, payload_json, status, created_at, sequence FROM storylet_cancellations WHERE event_id = ?",
            (event_id,),
        ).fetchone()
        if not row:
            return None
        return {
            "event_id": row["event_id"],
            "account_username": row["account_username"],
            "slot_id": row["slot_id"],
            "save_key": row["save_key"],
            "payload_json": row["payload_json"],
            "status": row["status"],
            "created_at": row["created_at"],
            "sequence": int(row["sequence"]),
        }

    def insert_storylet_cancellation(self, event: dict) -> bool:
        with self._conn:
            existing = self._conn.execute(
                "SELECT 1 FROM storylet_cancellations WHERE event_id = ?",
                (event["event_id"],),
            ).fetchone()
            if existing is not None:
                return True
            row = self._conn.execute(
                "SELECT 1 FROM character_slots WHERE slot_id = ? AND account_username = ? AND save_key = ?",
                (event["slot_id"], event["account_username"], event["save_key"]),
            ).fetchone()
            if row is None:
                return False
            self._conn.execute(
                "INSERT OR IGNORE INTO storylet_cancellations (event_id, account_username, slot_id, save_key, payload_json, status, created_at, sequence) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    event["event_id"],
                    event["account_username"],
                    event["slot_id"],
                    event["save_key"],
                    event["payload_json"],
                    event.get("status", "pending"),
                    event.get("created_at", ""),
                    int(event.get("sequence", 0)),
                ),
            )
        return True

    def list_storylet_cancellations(self, account_username: str, slot_id: str) -> List[dict]:
        rows = self._conn.execute(
            "SELECT event_id, account_username, slot_id, save_key, payload_json, status, created_at, sequence FROM storylet_cancellations WHERE account_username = ? AND slot_id = ? ORDER BY created_at, sequence, event_id",
            (account_username, slot_id),
        ).fetchall()
        return [
            {
                "event_id": row["event_id"],
                "account_username": row["account_username"],
                "slot_id": row["slot_id"],
                "save_key": row["save_key"],
                "payload_json": row["payload_json"],
                "status": row["status"],
                "created_at": row["created_at"],
                "sequence": int(row["sequence"]),
            }
            for row in rows
        ]

    def set_storylet_cancellation_status(self, event_id: str, status: str) -> bool:
        _CANCELLATION_STATUS_RANK = {"pending": 0, "applied": 1, "feedback_delivered": 2}
        row = self._conn.execute(
            "SELECT status FROM storylet_cancellations WHERE event_id = ?",
            (event_id,),
        ).fetchone()
        if row is None:
            return False
        if _CANCELLATION_STATUS_RANK.get(row["status"], 0) >= _CANCELLATION_STATUS_RANK.get(status, 0):
            return False
        self._conn.execute(
            "UPDATE storylet_cancellations SET status = ? WHERE event_id = ?",
            (status, event_id),
        )
        self._conn.commit()
        return True

    def get_death_journal_claim(self, event_id: str) -> Optional[dict]:
        row = self._conn.execute(
            "SELECT event_id, claimant_slot_id, status, knowledge_json, created_at FROM death_journal_claims WHERE event_id = ?",
            (event_id,),
        ).fetchone()
        if not row:
            return None
        return {
            "event_id": row["event_id"],
            "claimant_slot_id": row["claimant_slot_id"],
            "status": row["status"],
            "knowledge_json": row["knowledge_json"],
            "created_at": row["created_at"],
        }

    def insert_death_journal_claim(self, event_id: str, claimant_slot_id: str, knowledge_json: str, created_at: str) -> bool:
        try:
            self._conn.execute(
                "INSERT INTO death_journal_claims (event_id, claimant_slot_id, status, knowledge_json, created_at) VALUES (?, ?, 'claimed', ?, ?)",
                (event_id, claimant_slot_id, knowledge_json, created_at),
            )
            self._conn.commit()
            return True
        except sqlite3.IntegrityError:
            self._conn.rollback()
            return False

    def set_death_journal_claim_status(self, event_id: str, status: str) -> None:
        self._conn.execute(
            "UPDATE death_journal_claims SET status = ? WHERE event_id = ?",
            (status, event_id),
        )
        self._conn.commit()

    def get_previous_characters(self, username: str) -> List[dict]:
        row = self._conn.execute(
            "SELECT previous_characters FROM accounts WHERE username = ?", (username,)
        ).fetchone()
        if not row:
            return []
        return json.loads(row["previous_characters"] or "[]")

    def add_predecessor(self, username: str, data: dict):
        previous = self.get_previous_characters(username)
        previous.append(data)
        self._conn.execute(
            "UPDATE accounts SET previous_characters = ? WHERE username = ?",
            (json.dumps(previous), username),
        )
        self._conn.commit()

    def get_account_storylet_history(self, username: str) -> List[str]:
        row = self._conn.execute(
            "SELECT account_storylet_history FROM accounts WHERE username = ?", (username,)
        ).fetchone()
        if not row:
            return []
        return json.loads(row["account_storylet_history"] or "[]")

    def add_account_storylet(self, username: str, storylet_id: str):
        history = self.get_account_storylet_history(username)
        if storylet_id not in history:
            history.append(storylet_id)
        self._conn.execute(
            "UPDATE accounts SET account_storylet_history = ? WHERE username = ?",
            (json.dumps(history), username),
        )
        self._conn.commit()

    def get_completed_milestones(self, username: str) -> List[str]:
        row = self._conn.execute(
            "SELECT completed_milestones FROM accounts WHERE username = ?", (username,)
        ).fetchone()
        if not row:
            return []
        return json.loads(row["completed_milestones"] or "[]")

    def add_completed_milestone(self, username: str, milestone_id: str):
        milestones = self.get_completed_milestones(username)
        if milestone_id not in milestones:
            milestones.append(milestone_id)
        self._conn.execute(
            "UPDATE accounts SET completed_milestones = ? WHERE username = ?",
            (json.dumps(milestones), username),
        )
        self._conn.commit()

    def list_characters(self, username: str) -> List[str]:
        row = self._conn.execute(
            "SELECT characters FROM accounts WHERE username = ?", (username,)
        ).fetchone()
        if not row:
            return []
        return json.loads(row["characters"])

    def all_usernames(self) -> List[str]:
        rows = self._conn.execute("SELECT username FROM accounts").fetchall()
        return [r["username"] for r in rows]

    def account_exists(self, username: str) -> bool:
        row = self._conn.execute(
            "SELECT 1 FROM accounts WHERE username = ?", (username,)
        ).fetchone()
        return row is not None

    def migrate_from_yaml(self, yaml_path: str):
        path = Path(yaml_path)
        if not path.exists():
            return 0

        data = load_strict_yaml(path) or {}

        accounts_data = data.get("accounts", {})
        if not accounts_data:
            return 0

        count = 0
        for username, acct in accounts_data.items():
            key = username.lower()
            if self.account_exists(key):
                continue
            self._conn.execute(
                "INSERT INTO accounts (username, password_hash, characters, primary_safehouse, stash, tutorial_complete, previous_characters, account_storylet_history, completed_milestones) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    key,
                    acct.get("password_hash", ""),
                    json.dumps(acct.get("characters", [])),
                    acct.get("primary_safehouse", ""),
                    json.dumps(acct.get("stash", [])),
                    1 if acct.get("tutorial_complete", False) else 0,
                    json.dumps(acct.get("previous_characters", [])),
                    json.dumps(acct.get("account_storylet_history", [])),
                    json.dumps(acct.get("completed_milestones", [])),
                ),
            )
            count += 1

        self._conn.commit()

        backup = path.with_suffix(".yaml.bak")
        if backup.exists():
            backup.unlink()
        path.rename(backup)
        return count

    def close(self):
        self._conn.close()
