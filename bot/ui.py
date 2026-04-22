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
    first_row: list[InlineKeyboardButton]
    if web_app_url:
        first_row = [InlineKeyboardButton(text="👤 Мой персонаж (мини-апп)", web_app=WebAppInfo(url=web_app_url))]
    else:
        first_row = [InlineKeyboardButton(text="👤 Мой персонаж (мини-апп)", callback_data="menu:character")]
    return InlineKeyboardMarkup(
        inline_keyboard=[
            first_row,
            [InlineKeyboardButton(text="💡 Подсказка", callback_data="menu:hint")],
            [InlineKeyboardButton(text="🔄 Новая игра", callback_data="menu:new")],
            [InlineKeyboardButton(text="⬅ Назад", callback_data="menu:back")],
        ]
    )
