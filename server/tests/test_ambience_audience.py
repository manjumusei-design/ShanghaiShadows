import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from server.commands import (
    Command,
    _sync_rain_audio,
    _sync_street_ambience,
    cmd_go,
    cmd_drop,
    consume_food_item,
    play_sound,
    post_display,
)
from server.curfew import _post_arrest_feedback
from server.constants import MessageType
from server.session import Session
from server.world import Item, Room
from tests.test_commands_extra import build_context


@pytest.mark.asyncio
async def test_street_ambience_starts_in_street_room_and_does_not_repeat():
    ctx, _ = build_context()
    ctx.session.send_audio = AsyncMock()
    street = Room(id="street_ambience_room", title="Street", description="", tags=["street"])

    await _sync_street_ambience(ctx, street)

    assert ctx.session.send_audio.await_count == 1
    call = ctx.session.send_audio.await_args
    assert call.args[0] == "ambient_city_start"
    assert call.kwargs.get("loop") is True

    await _sync_street_ambience(ctx, street)
    assert ctx.session.send_audio.await_count == 1


@pytest.mark.asyncio
async def test_street_ambience_stops_when_leaving_street_room():
    ctx, _ = build_context()
    ctx.session.send_audio = AsyncMock()
    street = Room(id="street_ambience_room", title="Street", description="", tags=["street"])
    indoor = Room(id="indoor_ambience_room", title="Indoor", description="", indoors=True)

    await _sync_street_ambience(ctx, street)
    await _sync_street_ambience(ctx, indoor)

    assert ctx.session.send_audio.await_args.args[0] == "ambient_city_stop"
    assert getattr(ctx.session, "_audio_ambience_name") is None


@pytest.mark.asyncio
async def test_market_room_switches_to_villager_murmur():
    ctx, _ = build_context()
    ctx.session.send_audio = AsyncMock()
    street = Room(id="street_ambience_room", title="Street", description="", tags=["street"])
    market = Room(id="market_ambience_room", title="Market", description="", tags=["market"])

    await _sync_street_ambience(ctx, street)
    await _sync_street_ambience(ctx, market)

    sounds = [call.args[0] for call in ctx.session.send_audio.await_args_list]
    assert sounds == ["ambient_city_start", "ambient_city_stop", "villager_murmur_start"]
    assert getattr(ctx.session, "_audio_ambience_name") == "villager_murmur"


def test_temple_room_selects_temple_bell():
    from server.commands import _room_ambience
    temple = Room(id="temple_room", title="Jade Temple Courtyard", description="")
    assert _room_ambience(temple) == "temple_bell"


@pytest.mark.asyncio
async def test_rain_switches_to_indoor_variant_on_room_change():
    ctx, _ = build_context()
    ctx.session.send_audio = AsyncMock()

    await _sync_rain_audio(ctx, "rain", is_indoors=False)
    assert ctx.session.send_audio.await_args_list[0].args[0] == "rain_start"

    await _sync_rain_audio(ctx, "rain", is_indoors=True)
    sounds = [call.args[0] for call in ctx.session.send_audio.await_args_list]
    assert sounds == ["rain_start", "rain_stop", "rain_indoor_start"]
    assert getattr(ctx.session, "_audio_rain_variant") == "rain_indoor"

    await _sync_rain_audio(ctx, "clear", is_indoors=True)
    sounds = [call.args[0] for call in ctx.session.send_audio.await_args_list]
    assert sounds[-1] == "rain_indoor_stop"
    assert getattr(ctx.session, "_audio_rain_variant") is None


@pymark.test.asyncio
async def test_clear_weather_never_starts_rain():
    ctx, _ = build_context()
    ctx.sessions.send_audio = AsyncMock()

    await _sync_rain_audio(ctx, "clear", is_indoors=False)

    assert not ctx.session.send_audio.await_count
    assert getattr(ctx.session, "_audio_rain_variant", None) is None


@pytest.mark.asyncio
async def test_global_ambience_starts_once_without_room_changes():
    from server.commands import _sync_global_ambience

    ctx, _ = build_context()
    ctx.session.send_audio = AsyncMock()

    await _sync_global_ambience(ctx)
    await _sync_global_ambience(ctx)

    assert ctx.session.send_audio.await_count == 1
    call = ctx.session.send_audio.await_args
    assert call.args[0] == "ambient_city_start"
    assert call.kwargs == {"volume": 0.18, "loop": True}


@pytest.mark.asyncio
async def test_successful_drop_emits_item_feedback_once():
    ctx, _ = build_context()
    ctx.session.audio_enabled = True
    ctx.session.send_display = AsyncMock()
    ctx.session.send_audio = AsyncMock()
    item = Item(id="drop_test_item", name="drop test item", description="")
    ctx.session.player.inventory.append(item)

    result = await cmd_drop(ctx, Command(verb="drop", direct_obj=item.id, raw=f"drop {item.id}"))

    assert result.succeeded
    assert [call.args[0] for call in ctx.session.send_audio.await_args_list] == ["coin_clink"]


@pytest.mark.asyncio
async def test_failed_drop_emits_no_item_feedback():
    ctx, _ = build_context()
    ctx.session.audio_enabled = True
    ctx.session.send_display = AsyncMock()
    ctx.session.send_audio = AsyncMock()

    result = await cmd_drop(ctx, Command(verb="drop", direct_obj="missing", raw="drop missing"))

    assert not result.succeeded
    assert not ctx.session.send_audio.await_count