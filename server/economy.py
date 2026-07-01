from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional
import random
from .constants import BLACK_MARKET_LISTING_EXPIRE_DAYS, get_season, SEASONAL_PRICE_MULTIPLIER


def check_money(player, fabi_cost: int) -> bool:
    total_fabi = player.money_fabi + player.money_silver * 10
    return total_fabi >= fabi_cost


def spend_money(player, fabi_amount: int) -> None:
    if player.money_fabi >= fabi_amount:
        player.money_fabi -= fabi_amount
    else:
        remainder = fabi_amount - player.money_fabi
        player.money_fabi = 0
        silver_needed = (remainder + 9) // 10
        player.money_silver = max(0, player.money_silver - silver_needed)
        player.money_fabi += silver_needed * 10 - remainder


def earn_money(player, fabi_amount: int) -> None:
    player.money_fabi += fabi_amount
    silver_to_add = player.money_fabi // 10
    player.money_fabi %=10
    player.money_silver += silver_to_add


@dataclass
class MarketCondition:
    region: str
    item_category: str
    price_modifier: float = 1.0
    availability: float = 1.0
    scarcity_reason: Optional[str] = None


@dataclass
class BlackMarketListing:
    seller_id: str
    seller_name: str
    item_id: str
    price: int
    currency: str
    risk_level: int
    available_until: str


class EconomySystem:
    REGIONAL_PRICES = {
        'docks': {'food': 0.8, 'contraband': 0.7, 'weapons': 1.2, 'information': 1.3},
        'commercial': {'food': 1.0, 'weapons': 1.1, 'information': 0.9, 'luxury': 1.0},
        'french_concession': {'food': 1.3, 'weapons': 1.5, 'luxury': 0.8, 'contraband': 1.4},
        'old_city': {'food': 1.1, 'weapons': 0.9, 'traditional': 0.7, 'information': 0.8},
        'hongkou': {'food': 1.2, 'weapons': 0.8, 'japanese_goods': 0.6, 'contraband': 1.5},
        'bund': {'food': 1.2, 'luxury': 1.0, 'information': 1.1, 'weapons': 1.3},
        'residential': {'food': 1.0, 'traditional': 0.9, 'weapons': 1.2},
        'ccp': {'food': 0.9, 'weapons': 0.85, 'information': 0.7, 'contraband': 1.0},
        'gmd': {'food': 1.0, 'weapons': 0.9, 'information': 0.8},
    }

    FACTION_PRICES = {
        'kempeitai': {'weapons': 2.0, 'contraband': 3.0, 'food': 1.5},  # Hostile pricing
        'green_gang': {'contraband': 0.7, 'weapons': 0.9},  # Good prices for illegal goods
        'ccp': {'weapons': 0.8, 'food': 0.9},  # Support the resistance
        'civilian': {},  # Standard prices
        'gmd': {'weapons': 0.9, 'information': 0.8},
    }

    DEFAULT_AVAILABILITY = {
        'food': 0.8,
        'weapons': 0.5,
        'contraband': 0.3,
        'information': 0.4,
        'luxury': 0.6,
        'traditional': 0.7,
        'japanese_goods': 0.6,
    }

    ITEM_CATEGORIES = {
        # Food
        'rice_bowl': 'food', 'baozi': 'food', 'tea': 'food', 'cold_noodles': 'food',
        'dried_fish': 'food', 'street_snack': 'food', 'food_parcel': 'food',

        'mauser_c96': 'weapons', 'wooden_club': 'weapons', 'kitchen_knife': 'weapons',
        'smuggled_pistol': 'weapons', 'smuggled_rifle': 'weapons', 'strangling_wire': 'weapons',

        'contraband_morphine': 'contraband', 'forged_pass': 'contraband',
        'hidden_cash': 'contraband', 'quinine_bottle': 'contraband',

        'coded_ledger': 'information', 'patrol_route': 'information',
        'dock_manifest': 'information', 'resistance_map': 'information',
        'code_book': 'information',

        'silk_scarf': 'luxury', 'winter_coat': 'luxury',

        'prayer_beads': 'traditional', 'jade_talisman': 'traditional',

        'japanese_cigarettes': 'japanese_goods', 'japanese_textbook': 'japanese_goods',
    }

    def __init__(self):
        self.market_conditions: Dict[str, MarketCondition] = {}
        self.black_market_listings: List[BlackMarketListing] = []
        self.last_update_day: int = 0
        self.pending_credits: Dict[str, int] = {}
        self._listing_counter: int = 0

    def get_item_category(self, item_id: str) -> str:
        return self.ITEM_CATEGORIES.get(item_id, 'general')
    
    def get_regional_modifier(self, item_id: str, region: str) -> float:
        category = self.get_item_category(item_id)
        return self.REGIONAL_PRICES.get(region, {}).get(category, 1.0)
    
    def get_faction_modifier(self, item_id: str, faction: str) -> float:
        category = self.get_item_category(item_id)
        return self.FACTION_PRICES.get(faction, {}).get(category, 1,0)
    
    def get_scarcity_modifier(self, item_id: str, region: str) -> float:
        key = f"{region}_{item_id}"
        condition = self.market_conditions.get(key)
        if not condition:
            return 1.0
        if condition.availability < 0.3:
            return 1.5
        if condition.availability < 0.5:
            return 1.2
        return 1.0