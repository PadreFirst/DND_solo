"""Inventory management handler: /inventory, use, drop, inspect."""
from __future__ import annotations

import logging

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, Message
from sqlalchemy.ext.asyncio import AsyncSession

from bot.models.user import OnboardingState
from bot.services.user_service import ensure_character, get_or_create_user
from bot.utils.formatters import format_inventory
from bot.utils.keyboards import inventory_item_keyboard, inventory_list_keyboard

log = logging.getLogger(__name__)
router = Router(name="inventory")


@router.message(Command("inventory"))
async def cmd_inventory(message: Message, db: AsyncSession) -> None:
    user = await get_or_create_user(message.from_user.id, message.from_user.username, db)
    if user.onboarding_state != OnboardingState.PLAYING or not user.character:
        await message.answer("Start a game first with /start")
        return
    char = user.character
    text = format_inventory(char)
    kb = inventory_list_keyboard(char.inventory) if char.inventory else None
    await message.answer(text, parse_mode="HTML", reply_markup=kb)


@router.callback_query(F.data.startswith("inv:select:"))
async def on_inv_select(cb: CallbackQuery, db: AsyncSession) -> None:
    user = await get_or_create_user(cb.from_user.id, cb.from_user.username, db)
    char = await ensure_character(user, db)

    idx = int(cb.data.split(":")[2])
    inv = char.inventory
    if idx >= len(inv):
        await cb.answer("Item not found", show_alert=True)
        return

    item = inv[idx]
    name = item.get("name", "???")
    desc = item.get("description", "No description")
    weight = item.get("weight", 0)
    qty = item.get("quantity", 1)

    text = (
        f"🔍 <b>{name}</b>\n"
        f"Quantity: {qty}\n"
        f"Weight: {weight} lb\n"
        f"<i>{desc}</i>"
    )
    await cb.message.edit_text(text, parse_mode="HTML",
                               reply_markup=inventory_item_keyboard(idx))
    await cb.answer()


@router.callback_query(F.data.startswith("inv:use:"))
async def on_inv_use(cb: CallbackQuery, db: AsyncSession) -> None:
    user = await get_or_create_user(cb.from_user.id, cb.from_user.username, db)
    char = await ensure_character(user, db)

    idx = int(cb.data.split(":")[2])
    inv = char.inventory
    if idx >= len(inv):
        await cb.answer("Item not found", show_alert=True)
        return

    item = inv[idx]
    name = item.get("name", "???")

    from bot.handlers.game import _process_player_action
    await cb.answer(f"Using {name}...")
    await _process_player_action(
        cb.message, cb.from_user.id, cb.from_user.username,
        f"I use {name} from my inventory", db
    )


@router.callback_query(F.data.startswith("inv:drop:"))
async def on_inv_drop(cb: CallbackQuery, db: AsyncSession) -> None:
    user = await get_or_create_user(cb.from_user.id, cb.from_user.username, db)
    char = await ensure_character(user, db)

    idx = int(cb.data.split(":")[2])
    inv = char.inventory
    if idx >= len(inv):
        await cb.answer("Item not found", show_alert=True)
        return

    dropped = inv.pop(idx)
    char.inventory = inv

    await cb.answer(f"Dropped {dropped.get('name', '???')}")
    text = format_inventory(char)
    kb = inventory_list_keyboard(char.inventory) if char.inventory else None
    await cb.message.edit_text(text, parse_mode="HTML", reply_markup=kb)


@router.callback_query(F.data.startswith("inv:inspect:"))
async def on_inv_inspect(cb: CallbackQuery, db: AsyncSession) -> None:
    user = await get_or_create_user(cb.from_user.id, cb.from_user.username, db)
    char = await ensure_character(user, db)

    idx = int(cb.data.split(":")[2])
    inv = char.inventory
    if idx >= len(inv):
        await cb.answer("Item not found", show_alert=True)
        return

    item = inv[idx]
    name = item.get("name", "???")

    from bot.handlers.game import _process_player_action
    await cb.answer(f"Inspecting {name}...")
    await _process_player_action(
        cb.message, cb.from_user.id, cb.from_user.username,
        f"I carefully inspect and examine {name} from my inventory", db
    )


@router.callback_query(F.data == "inv:back")
async def on_inv_back(cb: CallbackQuery, db: AsyncSession) -> None:
    user = await get_or_create_user(cb.from_user.id, cb.from_user.username, db)
    char = await ensure_character(user, db)
    text = format_inventory(char)
    kb = inventory_list_keyboard(char.inventory) if char.inventory else None
    await cb.message.edit_text(text, parse_mode="HTML", reply_markup=kb)
    await cb.answer()
