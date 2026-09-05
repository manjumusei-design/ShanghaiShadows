from pathlib import Path

from .content_validation import ContentValidationError
from .world import Item


ITEMS_SOURCE = Path("server/data/items.yaml")


def validate_catalog_item(world, item_id: str) -> None:
    if item_id not in world.item_catalog:
        raise ContentValidationError(
            ITEMS_SOURCE,
            f"items[{item_id}]",
            f"unknown item {item_id!r}",
        )


def grant_catalog_item(world, inventory: list[Item], item_id: str, *, contraband: bool = False) -> Item:
    validate_catalog_item(world, item_id)
    item = world.clone_item(item_id)
    if item is None:
        raise ContentValidationError(
            ITEMS_SOURCE,
            f"items[{item_id}]",
            f"unable to clone item {item_id!r}",
        )
    if contraband:
        item.contraband_risk = True
    from .equipment import register_inventory_item
    register_inventory_item(inventory, item)
    return item
