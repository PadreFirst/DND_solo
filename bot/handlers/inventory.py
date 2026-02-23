"""Inventory management handler: /inventory, use, drop, inspect."""
from __future__ import annotations

import logging

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, Message
from sqlalchemy.ext.asyncio import AsyncSession

from bot.models.user import OnboardingState
from bot.services.user_service import ensure_character, ensure_session, get_or_create_user
from bot.utils.formatters import format_inventory
from bot.utils.keyboards import (
    cat_label,
    inventory_categories_keyboard,
    inventory_cat_items_keyboard,
    inventory_item_keyboard,
)

log = logging.getLogger(__name__)
router = Router(name="inventory")


@router.message(Command("inventory"))
async def cmd_inventory(message: Message, db: AsyncSession) -> None:
    user = await get_or_create_user(message.from_user.id, message.from_user.username, db)
    if user.onboarding_state != OnboardingState.PLAYING or not user.character:
        hint = "Сначала начни игру: /start" if user.language == "ru" else "Start a game first with /start"
        await message.answer(hint)
        return
    char = user.character
    gs = await ensure_session(user, db)
    cur = gs.currency_name or ""
    text = format_inventory(char, user.language, cur)
    kb = inventory_categories_keyboard(char.inventory, user.language) if char.inventory else None
    await message.answer(text, parse_mode="HTML", reply_markup=kb)


# --- Category navigation (#9) ---

async def _show_categories(cb: CallbackQuery, db: AsyncSession) -> None:
    user = await get_or_create_user(cb.from_user.id, cb.from_user.username, db)
    char = await ensure_character(user, db)
    gs = await ensure_session(user, db)
    cur = gs.currency_name or ""
    text = format_inventory(char, user.language, cur)
    kb = inventory_categories_keyboard(char.inventory, user.language) if char.inventory else None
    try:
        await cb.message.edit_text(text, parse_mode="HTML", reply_markup=kb)
    except Exception:
        pass
    await cb.answer()


@router.callback_query(F.data == "inv:cats")
async def on_inv_cats(cb: CallbackQuery, db: AsyncSession) -> None:
    await _show_categories(cb, db)


@router.callback_query(F.data == "inv:back")
async def on_inv_back(cb: CallbackQuery, db: AsyncSession) -> None:
    await _show_categories(cb, db)


@router.callback_query(F.data.startswith("inv:cat:"))
async def on_inv_cat(cb: CallbackQuery, db: AsyncSession) -> None:
    parts = cb.data.split(":")
    cat = parts[2]
    page = int(parts[3]) if len(parts) > 3 else 0
    user = await get_or_create_user(cb.from_user.id, cb.from_user.username, db)
    char = await ensure_character(user, db)
    header = cat_label(cat, user.language)
    kb = inventory_cat_items_keyboard(char.inventory or [], cat, user.language, page)
    try:
        await cb.message.edit_text(header, parse_mode="HTML", reply_markup=kb)
    except Exception:
        pass
    await cb.answer()


# --- Item actions ---

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
    desc = item.get("description", "")
    qty = item.get("quantity", 1)
    itype = item.get("type", "misc")
    mechanics = item.get("mechanics", {})
    if isinstance(mechanics, str):
        import json as _json
        try:
            mechanics = _json.loads(mechanics)
        except Exception:
            mechanics = {}

    lines = [f"🔍 <b>{name}</b>"]
    if itype == "weapon" and mechanics:
        dmg = mechanics.get("damage", "?")
        dtype = mechanics.get("type", "")
        lines.append(f"⚔️ Урон: <b>{dmg} {dtype}</b>" if user.language == "ru" else f"⚔️ Damage: <b>{dmg} {dtype}</b>")
    elif itype == "armor" and mechanics:
        ac = mechanics.get("ac", "?")
        atype = mechanics.get("type", "")
        lines.append(f"🛡 Защита: <b>AC {ac}</b> ({atype})" if user.language == "ru" else f"🛡 Defense: <b>AC {ac}</b> ({atype})")
    if qty > 1:
        lines.append(f"Количество: {qty}" if user.language == "ru" else f"Quantity: {qty}")
    if item.get("equipped"):
        lines.append("✅ Экипировано" if user.language == "ru" else "✅ Equipped")
    if desc:
        lines.append(f"<i>{desc}</i>")

    text = "\n".join(lines)
    await cb.message.edit_text(text, parse_mode="HTML",
                               reply_markup=inventory_item_keyboard(idx, user.language))
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
    if user.language == "ru":
        await cb.answer(f"Использую {name}...")
        action_text = f"Я использую {name} из инвентаря"
    else:
        await cb.answer(f"Using {name}...")
        action_text = f"I use {name} from my inventory"
    await _process_player_action(
        cb.message, cb.from_user.id, cb.from_user.username,
        action_text, db
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

    name = dropped.get("name", "???")
    msg = f"Выброшено: {name}" if user.language == "ru" else f"Dropped {name}"
    await cb.answer(msg)
    gs = await ensure_session(user, db)
    cur = gs.currency_name or ""
    text = format_inventory(char, user.language, cur)
    kb = inventory_categories_keyboard(char.inventory, user.language) if char.inventory else None
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
    if user.language == "ru":
        await cb.answer(f"Изучаю {name}...")
        action_text = f"Я внимательно осматриваю {name} из инвентаря"
    else:
        await cb.answer(f"Inspecting {name}...")
        action_text = f"I carefully inspect and examine {name} from my inventory"
    await _process_player_action(
        cb.message, cb.from_user.id, cb.from_user.username,
        action_text, db
    )
