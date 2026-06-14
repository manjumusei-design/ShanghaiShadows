import random
from dataclasses import dataclass, field
from typing import List, Optional, TYPE_CHECKING

from .constants import DISARM_CHANCE_CAP, MORALE_LOW_THRESHOLD, MORALE_PENALTY_MAX, STEALTH_KILL_BONUS

if TYPE_CHECKING:
    from .world import Item


@dataclass
class CombatResult:
    won: bool = False
    silent: bool = False
    disarmed: bool = False
    weapon_broken: bool = False
    attacker_damaged: int = 0
    messages: List[str] = field(default_factory=list)


def resolve_attack(
        attacker_courage: int,
        attacker_weapon: Optional["Item"],
        target_authority: int,
        target_armour: Optional["Item"],
        attacker_hidden: bool = False,
        attacker_morale: int = 100,
) -> CombatResult:
    result = CombatResult()

    effective_courage = attacker_courage
    if attacker_weapon:
        effective_courage += attacker_weapon.courage_bonus
    if attacker_hidden:
        effective_courage += STEALTH_KILL_BONUS
        result.silent = True

    defence = target_armour.defense_value if target_armour else 0
    effective_courage -= defence
    if attacker_morale < MORALE_LOW_THRESHOLD:
        effective_courage -= min(MORALE_PENALTY_MAX, MORALE_LOW_THRESHOLD - attacker_morale)
    if effective_courage >= target_authority:
        result.won = True
        result.messages.append("Your strike finds its mark.")
    else:
        disarm_chance = min((target_authority - effective_courage) * 2, DISARM_CHANCE_CAP)
        if random.randint(1, 100) <= disarm_chance:
            result.disarmed = True
            result.messages.append("Your attack is deflected and you are disarmed!")
        else:
            result.attacker_damaged = random.randint(5, 15)
            result.messages.append(f"Your attack fails. You take {result.attacker_damaged} damage in the struggle.")

    return result


def degrade_weapon(weapon: "Item", attack_suceeded: bool) -> bool:
    if weapon.durability == -1:
        return False
    weapon.durability -= 5 if attack_suceeded else 2
    if weapon.durability <= 0:
        weapon.durability = 0
        return True
    return False


def degrade_armour(armour: "Item") -> bool:
    if armour.durability == -1:
        return False
    armour.durability -= 3
    if armour.durability <= 0:
        armour.durability = 0
        return True
    return False