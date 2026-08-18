from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional
import random
from .constants import BLACK_MARKET_LISTING_EXPIRE_DAYS, get_season, SEASONAL_PRICE_MULTIPLIER
from .trust import get_trust_tier


def _validate_fabi_amount(amount: int) -> int:
    if not isinstance(amount, int) or amount < 0:
        raise ValueError("fabi value must be a non neg int")
    return amount


def _availability_price_modifier(availability: float) -> float:
    return max(0,5m min(2.0, 1.0 + (1.0 - availability) * 0.5))


def wallet_fabi_value(player) -> int:
    return int(player.money_fabi) + 10 * int(player.money_silver)


def can_afford_fabi(player, amount: int) -> bool:
    return wallet_fabi_value(player) >= _validate_fabi_amount(amount)


def spend_fabi_value(player, amount: int) -> bool:
    amount = _validate_fabi_amount(amount)
    if not can_afford_fabi(player, amount):
        return False
    remaining = wallet_fabi_value(player) - amount
    player.money_silver, player.money_fabi = divmod(remaining, 10)
    return True


def earn_fabi_value(player, amount: int) -> None:
    total = wallet_fabi_value(player) + _validate_fabi_amount(amount)
    player.money_silver, player.money_fabi = divmod(total, 10)


def set_wallet_fabi_value(player, amount: int) -> None:
    amount = _validate_fabi_amount(amount)
    player.money_silver, player.money_fabi = divmod(amount, 10)


def check_money(player, fabi_cost: int) -> bool:
    return can_afford_fabi(player, fabi_cost)


def spend_money(player, fabi_amount: int) -> None:
    spend_fabi_value(player, fabi_amount)


def earn_money(player, fabi_amount: int) -> None:
    earn_fabi_value(player, fabi_amount)

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
    available_until: int  


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
        'kempeitai': {'weapons': 2.0, 'contraband': 3.0, 'food': 1.5},  
        'green_gang': {'contraband': 0.7, 'weapons': 0.9}, 
        'ccp': {'weapons': 0.8, 'food': 0.9},  
        'civilian': {}, 
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
        'japanese_rice': 'japanese_goods', 'japanese_medicine': 'japanese_goods',
        'kempeitai_ration': 'japanese_goods', 'japanese_travel_pass': 'japanese_goods',
    }

    def __init__(self):
        self.market_conditions: Dict[str, MarketCondition] = {}
        self.black_market_listings: List[BlackMarketListing] = []
        self.last_update_day: int = 0
        self.pending_credits: Dict[str, int] = {}
        self._listing_counter: int = 0

    def get_item_category(self, item_id: str) -> str:
        return self.ITEM_CATEGORIES.get(item_id, 'general')

    def get_item_base_price(self, item_id: str, item_catalog: Optional[Dict[str, Any]] = None) -> int:
        entry = (item_catalog or {}).get(item_id)
        if entry is None or not getattr(entry, "takeable", False):
            return 0
        return max(0, int(getattr(entry, "base_cost", 0) or 0))
    
    def get_regional_modifier(self, item_id: str, region: str) -> float:
        category = self.get_item_category(item_id)
        return self.REGIONAL_PRICES.get(region, {}).get(category, 1.0)

    def get_faction_modifier(self, item_id: str, faction: str) -> float:
        category = self.get_item_category(item_id)
        return self.FACTION_PRICES.get(faction, {}).get(category, 1.0)


    def get_item_price(self, item_base_cost: int, item_id: str, region: str,
                       npc_faction: str, inflation_rate: float = 1.0,
                       season_multiplier: float = 1.0, trust_score: int = 50,
                       player_morale: int = 50, item_rarity: str = "common") -> int:
        if item_base_cost <= 0:
            return 0

        if player_morale < 30:
            morale_mod = 1.10
        elif player_morale < 70:
            morale_mod = 1.00
        else:
            morale_mod = 0.95

        trust_tier_mod = {
            "hostile": 1.5,
            "neutral": 1.0,
            "trusted": 0.9,
            "connected": 0.8,
        }.get(get_trust_tier(trust_score), 1.0)

        regional_mod = self.get_regional_modifier(item_id, region)
        faction_mod = self.get_faction_modifier(item_id, npc_faction)

        category = self.get_item_category(item_id)
        key = f"{region}_{category}"
        condition = self.market_conditions.get(key)
        condition_price_mod = condition.price_modifier if condition else 1.0

        rarity_multiplier = {
            "common": 1.0,
            "uncommon": 1.05,
            "rare": 1.10,
            "legendary": 1.20,
        }.get(item_rarity.lower(), 1.0)
        final_price = int(item_base_cost * regional_mod * faction_mod *
                         condition_price_mod * inflation_rate *
                         season_multiplier * trust_tier_mod * morale_mod * rarity_multiplier)

        return max(1, final_price)

    def get_resale_price(self, item, region: str, faction: str, base_cost: int = 0,
                         trust_score: int = 50, player_morale: int = 50,
                         inflation_rate: float = 1.0, season_multiplier: float = 1.0) -> int:
        if not getattr(item, "takeable", True):
            return 0
        if getattr(item, "is_quest_item", False):
            return 0
        condition_multiplier = 1.0
        if (getattr(item, "is_weapon", False) or getattr(item, "is_armour", False)) and getattr(item, "max_durability", -1) > 0:
            ratio = getattr(item, "durability", 0) / item.max_durability
            if ratio <= 0:
                return 0
            condition_multiplier = ratio
        quote = self.get_item_price(
            base_cost, item.id, region, faction,
            inflation_rate=inflation_rate,
            season_multiplier=season_multiplier,
            trust_score=trust_score,
            player_morale=player_morale,
            item_rarity=getattr(item, "rarity", "common"),
        )
        return int(quote * 0.5 * condition_multiplier)

    def update_market_conditions(self, day: int, shared_state=None) -> None:
        self.last_update_day = day

        for region in self.REGIONAL_PRICES:
            for category in self.DEFAULT_AVAILABILITY:
                key = f"{region}_{category}"
                base_availability = self.DEFAULT_AVAILABILITY.get(category, 0.7)
                if key in self.market_conditions:
                    mc = self.market_conditions[key]
                    mc.availability = max(0.1, min(1.0, base_availability + random.uniform(-0.15, 0.15)))
                    mc.price_modifier = _availability_price_modifier(mc.availability)
                else:
                    self.market_conditions[key] = MarketCondition(
                        region=region,
                        item_category=category,
                        price_modifier=_availability_price_modifier(base_availability),
                        availability=base_availability,
                    )

    def create_listing(self, seller_id: str, seller_name: str, item_id: str, price: int,
                       currency: str, risk_level: int, available_until: int) -> int:
        self._listing_counter += 1
        listing = BlackMarketListing(
            seller_id=seller_id,
            seller_name=seller_name,
            item_id=item_id,
            price=price,
            currency=currency,
            risk_level=risk_level,
            available_until=available_until,
        )
        self.black_market_listings.append(listing)
        return self._listing_counter

    def remove_listing(self, index: int) -> Optional[BlackMarketListing]:
        if 0 <= index < len(self.black_market_listings):
            return self.black_market_listings.pop(index)
        return None

    def credit_player(self, player_name: str, amount: int) -> None:
        if player_name in self.pending_credits:
            self.pending_credits[player_name] += amount
        else:
            self.pending_credits[player_name] = amount

    def claim_credits(self, player_name: str) -> int:
        amount = self.pending_credits.pop(player_name, 0)
        return amount


economy_system = EconomySystem()

DISTRICT_TO_REGION = {
    'hidden_shanghai': 'ccp',
    'residential': 'residential',
    'warehouse': 'docks',
    'church': 'old_city',
    'school': 'commercial',
    'refugee_entry': 'commercial',
    'bund': 'bund',
    'commercial': 'commercial',
    'old_city': 'old_city',
    'hongkou': 'hongkou',
    'french': 'french_concession',
    'docks': 'docks',
    'ccp_base': 'ccp',
    'gmd_office': 'gmd',
}


def serialize_economy_state() -> dict:
    return {
        "market_conditions": [
            {
                "region": mc.region,
                "item_category": mc.item_category,
                "price_modifier": mc.price_modifier,
                "availability": mc.availability,
                "scarcity_reason": mc.scarcity_reason,
            }
            for mc in economy_system.market_conditions.values()
        ],
        "black_market_listings": [
            {
                "seller_id": bml.seller_id,
                "seller_name": bml.seller_name,
                "item_id": bml.item_id,
                "price": bml.price,
                "currency": bml.currency,
                "risk_level": bml.risk_level,
                "available_until": bml.available_until,
            }
            for bml in economy_system.black_market_listings
        ],
        "last_update_day": economy_system.last_update_day,
        "pending_credits": dict(economy_system.pending_credits),
        "listing_counter": economy_system._listing_counter,
    }


def load_economy_state(data: dict) -> None:
    economy_system.market_conditions.clear()
    economy_system.black_market_listings.clear()
    economy_system.pending_credits.clear()
    for mc_data in data.get("market_conditions", []):
        mc = MarketCondition(
            region=mc_data["region"],
            item_category=mc_data["item_category"],
            price_modifier=mc_data.get("price_modifier", 1.0),
            availability=mc_data.get("availability", 1.0),
            scarcity_reason=mc_data.get("scarcity_reason"),
        )
        key = f"{mc.region}_{mc.item_category}"
        economy_system.market_conditions[key] = mc
    for bml_data in data.get("black_market_listings", []):
        bml = BlackMarketListing(
            seller_id=bml_data["seller_id"],
            seller_name=bml_data.get("seller_name", bml_data["seller_id"]),
            item_id=bml_data["item_id"],
            price=bml_data["price"],
            currency=bml_data["currency"],
            risk_level=bml_data["risk_level"],
            available_until=bml_data["available_until"],
        )
        economy_system.black_market_listings.append(bml)
    economy_system.last_update_day = data.get("last_update_day", 0)
    economy_system.pending_credits = data.get("pending_credits", {})
    economy_system._listing_counter = data.get("listing_counter", 0)
