"""Inline keyboard builders — all text localized."""
from __future__ import annotations

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

# --- Localization maps ---

_GENRE = {
    "ru": {
        "fantasy": "⚔️ Фэнтези",
        "sci-fi": "🚀 Научная фантастика",
        "dark_fantasy": "🧛 Тёмное фэнтези",
        "pirate": "🌊 Пираты",
        "steampunk": "🔮 Стимпанк",
        "classic": "🏰 Классическое DnD",
        "custom": "✏️ Свой вариант...",
    },
    "en": {
        "fantasy": "⚔️ Fantasy",
        "sci-fi": "🚀 Sci-Fi",
        "dark_fantasy": "🧛 Dark Fantasy",
        "pirate": "🌊 Pirate",
        "steampunk": "🔮 Steampunk",
        "classic": "🏰 Classic DnD",
        "custom": "✏️ Custom...",
    },
}

_TONE = {
    "ru": {
        "epic": "🎭 Серьёзный и эпичный",
        "humorous": "😄 Лёгкий и с юмором",
        "dark": "🌑 Мрачный и жёсткий",
        "balanced": "⚖️ Сбалансированный",
        "custom": "✏️ Свой вариант...",
    },
    "en": {
        "epic": "🎭 Serious & Epic",
        "humorous": "😄 Light & Humorous",
        "dark": "🌑 Dark & Gritty",
        "balanced": "⚖️ Balanced",
        "custom": "✏️ Custom...",
    },
}

_THEME = {
    "ru": {
        "war": "🗡 Войны и сражения",
        "mystery": "🔍 Тайны и интриги",
        "monsters": "🐉 Охота на монстров",
        "politics": "👑 Политика и власть",
        "exploration": "🌍 Исследования",
        "survival": "💀 Выживание",
        "custom": "✏️ Свой вариант...",
    },
    "en": {
        "war": "🗡 War & Conquest",
        "mystery": "🔍 Mystery & Intrigue",
        "monsters": "🐉 Monster Hunting",
        "politics": "👑 Politics & Power",
        "exploration": "🌍 Exploration",
        "survival": "💀 Survival",
        "custom": "✏️ Custom...",
    },
}

_AGE = {
    "ru": {
        "13-15": "13–15",
        "16-17": "16–17",
        "18-24": "18–24",
        "25-34": "25–34",
        "35+": "35+",
    },
    "en": {
        "13-15": "13–15",
        "16-17": "16–17",
        "18-24": "18–24",
        "25-34": "25–34",
        "35+": "35+",
    },
}


def language_keyboard() -> InlineKeyboardMarkup:
    """First screen — always in English, with flags."""
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="🇷🇺 Русский", callback_data="lang:ru"),
            InlineKeyboardButton(text="🇬🇧 English", callback_data="lang:en"),
        ],
        [
            InlineKeyboardButton(text="🇪🇸 Español", callback_data="lang:es"),
            InlineKeyboardButton(text="🇩🇪 Deutsch", callback_data="lang:de"),
        ],
        [
            InlineKeyboardButton(text="🇫🇷 Français", callback_data="lang:fr"),
            InlineKeyboardButton(text="🇨🇳 中文", callback_data="lang:zh"),
        ],
    ])


def age_keyboard(lang: str) -> InlineKeyboardMarkup:
    labels = _AGE.get(lang, _AGE["en"])
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text=labels["13-15"], callback_data="age:13-15"),
            InlineKeyboardButton(text=labels["16-17"], callback_data="age:16-17"),
            InlineKeyboardButton(text=labels["18-24"], callback_data="age:18-24"),
        ],
        [
            InlineKeyboardButton(text=labels["25-34"], callback_data="age:25-34"),
            InlineKeyboardButton(text=labels["35+"], callback_data="age:35+"),
        ],
    ])


def genre_keyboard(lang: str) -> InlineKeyboardMarkup:
    g = _GENRE.get(lang, _GENRE["en"])
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text=g["fantasy"], callback_data="genre:fantasy"),
            InlineKeyboardButton(text=g["sci-fi"], callback_data="genre:sci-fi"),
        ],
        [
            InlineKeyboardButton(text=g["dark_fantasy"], callback_data="genre:dark_fantasy"),
            InlineKeyboardButton(text=g["pirate"], callback_data="genre:pirate"),
        ],
        [
            InlineKeyboardButton(text=g["steampunk"], callback_data="genre:steampunk"),
            InlineKeyboardButton(text=g["classic"], callback_data="genre:classic"),
        ],
        [InlineKeyboardButton(text=g["custom"], callback_data="genre:custom")],
    ])


def tone_keyboard(lang: str) -> InlineKeyboardMarkup:
    t = _TONE.get(lang, _TONE["en"])
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text=t["epic"], callback_data="tone:epic"),
            InlineKeyboardButton(text=t["humorous"], callback_data="tone:humorous"),
        ],
        [
            InlineKeyboardButton(text=t["dark"], callback_data="tone:dark"),
            InlineKeyboardButton(text=t["balanced"], callback_data="tone:balanced"),
        ],
        [InlineKeyboardButton(text=t["custom"], callback_data="tone:custom")],
    ])


def theme_keyboard(lang: str) -> InlineKeyboardMarkup:
    t = _THEME.get(lang, _THEME["en"])
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text=t["war"], callback_data="theme:war"),
            InlineKeyboardButton(text=t["mystery"], callback_data="theme:mystery"),
        ],
        [
            InlineKeyboardButton(text=t["monsters"], callback_data="theme:monsters"),
            InlineKeyboardButton(text=t["politics"], callback_data="theme:politics"),
        ],
        [
            InlineKeyboardButton(text=t["exploration"], callback_data="theme:exploration"),
            InlineKeyboardButton(text=t["survival"], callback_data="theme:survival"),
        ],
        [InlineKeyboardButton(text=t["custom"], callback_data="theme:custom")],
    ])


def char_creation_method_keyboard(lang: str) -> InlineKeyboardMarkup:
    if lang == "ru":
        return InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="✍️ Описать свободно", callback_data="charmethod:free")],
            [InlineKeyboardButton(text="❓ Ответить на вопросы", callback_data="charmethod:questions")],
        ])
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✍️ Describe freely", callback_data="charmethod:free")],
        [InlineKeyboardButton(text="❓ Answer questions", callback_data="charmethod:questions")],
    ])


def character_review_keyboard(lang: str) -> InlineKeyboardMarkup:
    if lang == "ru":
        return InlineKeyboardMarkup(inline_keyboard=[
            [
                InlineKeyboardButton(text="✅ Принять", callback_data="charreview:accept"),
                InlineKeyboardButton(text="🔄 Заново", callback_data="charreview:regen"),
            ],
        ])
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="✅ Accept", callback_data="charreview:accept"),
            InlineKeyboardButton(text="🔄 Regenerate", callback_data="charreview:regen"),
        ],
    ])


def actions_keyboard(actions: list[str]) -> InlineKeyboardMarkup:
    buttons = []
    for action in actions[:6]:
        buttons.append([InlineKeyboardButton(
            text=action, callback_data=f"act:{action[:60]}",
        )])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def inventory_item_keyboard(item_index: int, lang: str = "en") -> InlineKeyboardMarkup:
    if lang == "ru":
        return InlineKeyboardMarkup(inline_keyboard=[
            [
                InlineKeyboardButton(text="🔧 Использовать", callback_data=f"inv:use:{item_index}"),
                InlineKeyboardButton(text="🗑 Выбросить", callback_data=f"inv:drop:{item_index}"),
                InlineKeyboardButton(text="🔍 Осмотреть", callback_data=f"inv:inspect:{item_index}"),
            ],
            [InlineKeyboardButton(text="⬅️ Назад", callback_data="inv:back")],
        ])
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="🔧 Use", callback_data=f"inv:use:{item_index}"),
            InlineKeyboardButton(text="🗑 Drop", callback_data=f"inv:drop:{item_index}"),
            InlineKeyboardButton(text="🔍 Inspect", callback_data=f"inv:inspect:{item_index}"),
        ],
        [InlineKeyboardButton(text="⬅️ Back", callback_data="inv:back")],
    ])


def inventory_list_keyboard(items: list[dict]) -> InlineKeyboardMarkup:
    buttons = []
    for i, item in enumerate(items[:10]):
        name = item.get("name", "???")
        qty = item.get("quantity", 1)
        label = f"{name} x{qty}" if qty > 1 else name
        buttons.append([InlineKeyboardButton(
            text=label, callback_data=f"inv:select:{i}"
        )])
    return InlineKeyboardMarkup(inline_keyboard=buttons)
