from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional
import random
from .constants import BLACK_MARKET_LISTING_EXPIRE_DAYS, get_season, SEASONAL_PRICE_MULTIPLIER


def check_money(player, fabi_cost: int) -> bool:
    total_fabi = player.money_fabi + player.money_silver * 10
    return total_fabi >= fabi_cost


def spend_money(player, fabi_amount: int) -> None:
    total_fabi = player.money_fabi + player.money_silver * 10
    if total_fabi < fabi_amount:
        return
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
    player.money_fabi %= 10
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
        return self.FACTION_PRICES.get(faction, {}).get(category, 1.0)

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

    def get_item_price(self, item_base_cost: int, item_id: str, region: str,
                       npc_faction: str, inflation_rate: float = 1.0,
                       season_multiplier: float = 1.0, trust_score: int = 50) -> int:
        if item_base_cost <= 0:
            return 0

        if trust_score < 30:
            trust_tier_mod = 1.5 
        elif trust_score < 50:
            trust_tier_mod = 1.0  
        elif trust_score < 70:
            trust_tier_mod = 0.9 
        else:
            trust_tier_mod = 0.8  

        regional_mod = self.get_regional_modifier(item_id, region)
        faction_mod = self.get_faction_modifier(item_id, npc_faction)
        scarcity_mod = self.get_scarcity_modifier(item_id, region)

        key = f"{region}_{item_id}"
        condition = self.market_conditions.get(key)
        condition_price_mod = condition.price_modifier if condition else 1.0

        final_price = int(item_base_cost * regional_mod * faction_mod *
                         scarcity_mod * condition_price_mod * inflation_rate *
                         season_multiplier * trust_tier_mod)

        return max(1, final_price)

    def get_trust_tier(self, trust_score: int) -> str:
        if trust_score < 30:
            return "outsider"
        elif trust_score < 50:
            return "neutral"
        elif trust_score < 70:
            return "trusted"
        else:
            return "connected"

    def update_market_conditions(self, day: int, shared_state=None) -> None:
        self.last_update_day = day

        for region in self.REGIONAL_PRICES:
            for category in self.DEFAULT_AVAILABILITY:
                key = f"{region}_{category}"
                base_availability = self.DEFAULT_AVAILABILITY.get(category, 0.7)
                if key in self.market_conditions:
                    mc = self.market_conditions[key]
                    mc.availability = max(0.1, min(1.0, base_availability + random.uniform(-0.15, 0.15)))
                    mc.price_modifier = max(0.5, min(2.0, 1.0 + (1.0 - mc.availability) * 0.5))
                else:
                    self.market_conditions[key] = MarketCondition(
                        region=region,
                        item_category=category,
                        price_modifier=1.0,
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
