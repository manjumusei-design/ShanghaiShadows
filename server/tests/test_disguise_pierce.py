from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from server.commands import _check_disguise_on_entry, _check_disguise_on_talk
from server.constants import CURFEW_MINUTE
from server.curfew import CurfewResolution, CurfewTrigger
from server.npc import Npc
from server.stealth import Disguise, PierceStage, StealthSystem
from server.world import Item, Room


def make_npc():
    return Npc(id="target", name="Target", description="", faction="civilian", role="resident", personality="alert", awareness=50, perception=50)


def make_context(npc, minute=0, indoors=False):
    ctx = MagicMock()
    ctx.shared.game_time.day = 1
    ctx.shared.game_time.minute = minute
    ctx.shared.rumor_records = {}
    ctx.shared.world.npcs = {npc.id: npc}
    ctx.stealth = StealthSystem({})
    disguise = Disguise(id="test_disguise", name="test", apparent_faction="civilian", bonus=20, description="")
    ctx.disguises = {disguise.id: disguise}
    ctx.session.player.disguise = disguise.id
    ctx.session.player.inventory = [Item(id="coat", name="coat", description="", disguise_id=disguise.id)]
    ctx.session.player.equipped_disguise_item_id = "coat"
    ctx.session.player.wanted_level = 0
    ctx.session.player.trust = {}
    ctx.session.send_display = AsyncMock()
    ctx.room = Room(id="room", title="Room", description="", indoors=indoors, npcs=[npc.id])
    ctx.shared.world.get_room.return_value = ctx.room
    return ctx


def test_pierce_stages():
    system = StealthSystem({})
    npc = make_npc()
    with patch("server.stealth.random.randint", return_value=1):
        assert system.disguise_pierce_check(npc, 40) == PierceStage.NONE
    with patch("server.stealth.random.randint", return_value=15):
        assert system.disguise_pierce_check(npc, 20) == PierceStage.SUSPICION
    with patch("server.stealth.random.randint", return_value=40):
        assert system.disguise_pierce_check(npc, 20) == PierceStage.CHALLENGE
    with patch("server.stealth.random.randint", return_value=50):
        assert system.disguise_pierce_check(npc, 20) == PierceStage.EXPOSED


@pytest.mark.asyncio
async def test_entry_suspicion_retains_equipped_disguise():
    npc = make_npc()
    ctx = make_context(npc)
    with patch("server.stealth.random.randint", return_value=15):
        await _check_disguise_on_entry(ctx, ctx.room)
    assert npc.suspicion == 10
    assert ctx.session.player.disguise == "test_disguise"
    assert ctx.session.player.inventory[0].id == "coat"


@pytest.mark.asyncio
async def test_talk_challenge_retains_equipped_disguise():
    npc = make_npc()
    ctx = make_context(npc)
    with patch("server.stealth.random.randint", return_value=40):
        assert await _check_disguise_on_talk(ctx, npc) is True
    assert ctx.session.player.disguise == "test_disguise"
    assert ctx.session.player.inventory[0].id == "coat"


@pytest.mark.asyncio
async def test_talk_exposure_confiscates_exact_item():
    npc = make_npc()
    ctx = make_context(npc, indoors=True)
    unrelated = Item(id="other", name="other", description="")
    ctx.session.player.inventory.append(unrelated)
    with patch("server.stealth.random.randint", return_value=50):
        assert await _check_disguise_on_talk(ctx, npc) is True
    assert ctx.session.player.disguise == ""
    assert ctx.session.player.equipped_disguise_item_id == ""
    assert ctx.session.player.inventory == [unrelated]


@pytest.mark.asyncio
async def test_kempeitai_curfew_exposure_uses_curfew_resolver():
    npc = make_npc()
    npc.faction = "kempeitai"
    npc.role = "officer"
    ctx = make_context(npc, minute=CURFEW_MINUTE)
    ctx.disguises["test_disguise"].apparent_faction = "kempeitai"
    ctx.shared.world.npc_locations[npc.id] = ctx.room.id
    resolution = CurfewResolution("immune", CurfewTrigger.DISGUISE_EXPOSURE, 1, None, False)
    with patch("server.stealth.random.randint", return_value=50):
        with patch("server.commands.resolve_curfew_encounter", new_callable=AsyncMock, return_value=resolution) as resolver:
            assert await _check_disguise_on_talk(ctx, npc) is True
    resolver.assert_awaited_once_with(ctx, CurfewTrigger.DISGUISE_EXPOSURE)
    assert ctx.session.player.disguise == ""


@pytest.mark.asyncio
async def test_entry_exposure_confiscates_before_one_curfew_resolver_call():
    npc = make_npc()
    ctx = make_context(npc, minute=CURFEW_MINUTE)
    ctx.disguises["test_disguise"].apparent_faction = "civilian"
    ctx.shared.world.npc_locations[npc.id] = ctx.room.id
    resolution = CurfewResolution("miss", CurfewTrigger.DISGUISE_EXPOSURE, 1, 15, True)
    observed = {}

    async def resolve(current_ctx, trigger):
        observed["disguise"] = current_ctx.session.player.disguise
        observed["item"] = current_ctx.session.player.equipped_disguise_item_id
        observed["trigger"] = trigger
        return resolution

    with patch("server.stealth.random.randint", return_value=50):
        with patch("server.commands.resolve_curfew_encounter", new=resolve) as resolver:
            await _check_disguise_on_entry(ctx, ctx.room)
    assert observed == {
        "disguise": "",
        "item": "",
        "trigger": CurfewTrigger.DISGUISE_EXPOSURE,
    }
    assert observed["trigger"] == CurfewTrigger.DISGUISE_EXPOSURE


@pytest.mark.asyncio
@pytest.mark.parametrize("stage", ["suspicion", "challenge"])
async def test_non_exposed_disguise_result_does_not_call_curfew_resolver(stage):
    npc = make_npc()
    ctx = make_context(npc, minute=CURFEW_MINUTE)
    stage_value = PierceStage.SUSPICION if stage == "suspicion" else PierceStage.CHALLENGE
    with patch.object(ctx.stealth, "disguise_pierce_check", return_value=stage_value):
        with patch("server.commands.resolve_curfew_encounter", new_callable=AsyncMock) as resolver:
            await _check_disguise_on_entry(ctx, ctx.room)
    resolver.assert_not_awaited()