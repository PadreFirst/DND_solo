from __future__ import annotations

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, WebAppInfo


def options_keyboard(options: list[str]) -> InlineKeyboardMarkup:
    number_row = [
        InlineKeyboardButton(text=str(idx), callback_data=f"opt:{idx - 1}")
        for idx in range(1, min(len(options), 5) + 1)
    ]
    rows: list[list[InlineKeyboardButton]] = [number_row]
    rows.append([
        InlineKeyboardButton(text="📋 Меню", callback_data="menu:open"),
        InlineKeyboardButton(text="❓ ГМ", callback_data="menu:ask"),
    ])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def menu_keyboard(web_app_url: str | None = None) -> InlineKeyboardMarkup:
    """Inline menu — must mirror SIDE_PANEL_COMMANDS in bot/main.py.

    Rule of thumb: whatever is in the "/" slash-popup MUST also be here, and
    vice-versa. Otherwise players see two different menus and get confused.
    """
    if web_app_url:
        character_row = [InlineKeyboardButton(text="👤 Мой персонаж (мини-апп)", web_app=WebAppInfo(url=web_app_url))]
    else:
        character_row = [InlineKeyboardButton(text="👤 Мой персонаж (мини-апп)", callback_data="menu:character")]
    return InlineKeyboardMarkup(
        inline_keyboard=[
            character_row,
            [
                InlineKeyboardButton(text="📊 Карточка", callback_data="menu:stats"),
                InlineKeyboardButton(text="🎒 Инвентарь", callback_data="menu:inventory"),
            ],
            [
                InlineKeyboardButton(text="📋 Квест", callback_data="menu:quest"),
                InlineKeyboardButton(text="💡 Подсказка", callback_data="menu:hint"),
            ],
            [
                InlineKeyboardButton(text="🛒 Магазин", callback_data="menu:shop"),
                InlineKeyboardButton(text="🧰 Крафт", callback_data="menu:craft"),
            ],
            [
                InlineKeyboardButton(text="⚔ Бой", callback_data="menu:combat"),
                InlineKeyboardButton(text="🌙 Отдых", callback_data="menu:rest"),
            ],
            [InlineKeyboardButton(text="🔄 Новая игра", callback_data="menu:new")],
            [InlineKeyboardButton(text="⬅ Назад", callback_data="menu:back")],
        ]
    )
