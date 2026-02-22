"""Inline keyboard builders — all text localized."""
from __future__ import annotations

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

# --- World presets: combined genre+tone+theme in one step ---

_WORLDS = {
    "ru": {
        "classic_fantasy": "⚔️ Классическое фэнтези",
        "dark_fantasy": "🧛 Тёмное фэнтези",
        "scifi": "🚀 Научная фантастика",
        "pirate": "🏴‍☠️ Пиратские приключения",
        "noir": "🔍 Нуар и детектив",
        "horror": "👻 Хоррор",
        "steampunk": "⚙️ Стимпанк",
        "postapoc": "☢️ Постапокалипсис",
        "custom": "✏️ Опишу сам...",
    },
    "en": {
        "classic_fantasy": "⚔️ Classic Fantasy",
        "dark_fantasy": "🧛 Dark Fantasy",
        "scifi": "🚀 Sci-Fi",
        "pirate": "🏴‍☠️ Pirate Adventure",
        "noir": "🔍 Noir & Detective",
        "horror": "👻 Horror",
        "steampunk": "⚙️ Steampunk",
        "postapoc": "☢️ Post-Apocalyptic",
        "custom": "✏️ I'll describe it...",
    },
}


def language_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="🇷🇺 Русский", callback_data="lang:ru", style="primary"),
            InlineKeyboardButton(text="🇬🇧 English", callback_data="lang:en", style="primary"),
        ],
        [
            InlineKeyboardButton(text="🇪🇸 Español", callback_data="lang:es", style="primary"),
            InlineKeyboardButton(text="🇩🇪 Deutsch", callback_data="lang:de", style="primary"),
        ],
        [
            InlineKeyboardButton(text="🇫🇷 Français", callback_data="lang:fr", style="primary"),
            InlineKeyboardButton(text="🇨🇳 中文", callback_data="lang:zh", style="primary"),
        ],
    ])


def age_keyboard(lang: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="13–15", callback_data="age:13-15"),
            InlineKeyboardButton(text="16–17", callback_data="age:16-17"),
            InlineKeyboardButton(text="18–24", callback_data="age:18-24"),
        ],
        [
            InlineKeyboardButton(text="25–34", callback_data="age:25-34"),
            InlineKeyboardButton(text="35+", callback_data="age:35+"),
        ],
    ])


def world_keyboard(lang: str) -> InlineKeyboardMarkup:
    w = _WORLDS.get(lang, _WORLDS["en"])
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text=w["classic_fantasy"], callback_data="world:classic_fantasy"),
            InlineKeyboardButton(text=w["dark_fantasy"], callback_data="world:dark_fantasy"),
        ],
        [
            InlineKeyboardButton(text=w["scifi"], callback_data="world:scifi"),
            InlineKeyboardButton(text=w["pirate"], callback_data="world:pirate"),
        ],
        [
            InlineKeyboardButton(text=w["noir"], callback_data="world:noir"),
            InlineKeyboardButton(text=w["horror"], callback_data="world:horror"),
        ],
        [
            InlineKeyboardButton(text=w["steampunk"], callback_data="world:steampunk"),
            InlineKeyboardButton(text=w["postapoc"], callback_data="world:postapoc"),
        ],
        [InlineKeyboardButton(text=w["custom"], callback_data="world:custom")],
    ])


_TONES = {
    "ru": {
        "dark": "🌑 Мрачный и тёмный",
        "heroic": "⚔️ Героический и эпический",
        "humor": "😄 Юмористический",
        "realistic": "🎯 Реалистичный и жёсткий",
        "mystery": "🔮 Загадочный и мистический",
    },
    "en": {
        "dark": "🌑 Dark & Grim",
        "heroic": "⚔️ Heroic & Epic",
        "humor": "😄 Humorous & Lighthearted",
        "realistic": "🎯 Realistic & Gritty",
        "mystery": "🔮 Mysterious & Suspenseful",
    },
}

TONE_DESCRIPTIONS = {
    "dark": "Dark, grim, morally gray. Violence has weight, hope is scarce, atmosphere is oppressive.",
    "heroic": "Heroic, epic, inspiring. Grand battles, noble sacrifices, triumph against the odds.",
    "humor": "Lighthearted, witty, comedic. Pop culture references, absurd situations, fun above all.",
    "realistic": "Grounded, gritty, consequential. Actions have real consequences, no plot armor.",
    "mystery": "Suspenseful, enigmatic, atmospheric. Secrets everywhere, trust no one, slow revelations.",
}


def tone_keyboard(lang: str) -> InlineKeyboardMarkup:
    t = _TONES.get(lang, _TONES["en"])
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=t["dark"], callback_data="tone:dark")],
        [InlineKeyboardButton(text=t["heroic"], callback_data="tone:heroic")],
        [InlineKeyboardButton(text=t["humor"], callback_data="tone:humor")],
        [InlineKeyboardButton(text=t["realistic"], callback_data="tone:realistic")],
        [InlineKeyboardButton(text=t["mystery"], callback_data="tone:mystery")],
    ])


def char_creation_method_keyboard(lang: str) -> InlineKeyboardMarkup:
    if lang == "ru":
        return InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="✍️ Описать свободно", callback_data="charmethod:free", style="primary")],
            [InlineKeyboardButton(text="❓ Ответить на вопросы", callback_data="charmethod:questions", style="primary")],
        ])
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✍️ Describe freely", callback_data="charmethod:free", style="primary")],
        [InlineKeyboardButton(text="❓ Answer questions", callback_data="charmethod:questions", style="primary")],
    ])


def character_review_keyboard(lang: str) -> InlineKeyboardMarkup:
    if lang == "ru":
        return InlineKeyboardMarkup(inline_keyboard=[[
            InlineKeyboardButton(text="✅ Принять", callback_data="charreview:accept", style="success"),
            InlineKeyboardButton(text="🔄 Заново", callback_data="charreview:regen", style="danger"),
        ]])
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="✅ Accept", callback_data="charreview:accept", style="success"),
        InlineKeyboardButton(text="🔄 Regenerate", callback_data="charreview:regen", style="danger"),
    ]])


def _strip_html(text: str) -> str:
    """Remove HTML tags from text."""
    import re
    return re.sub(r"<[^>]+>", "", text).strip()


def _clean_action(text: str) -> str:
    """Strip HTML, trim to fit Telegram button (max 25 visible chars)."""
    clean = _strip_html(text)
    clean = clean.strip("«»\"'")
    if len(clean) <= 25:
        return clean
    cut = clean[:25]
    last_space = cut.rfind(" ")
    if last_space > 10:
        return cut[:last_space]
    return cut


def _trim_callback(prefix: str, text: str) -> str:
    """Trim text so prefix+text fits in 64 bytes (Telegram callback_data limit)."""
    budget = 64 - len(prefix.encode("utf-8"))
    encoded = text.encode("utf-8")
    if len(encoded) <= budget:
        return prefix + text
    trimmed = encoded[:budget].decode("utf-8", errors="ignore")
    return prefix + trimmed


_STYLE_MAP = {
    "combat": ("danger", "⚔️"),
    "dialogue": ("primary", "💬"),
    "explore": (None, "🔍"),
    "safe": ("success", "🛡"),
}


def actions_keyboard(
    actions: list[str] | None = None,
    lang: str = "en",
    styles: list[str] | None = None,
) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []

    if actions:
        for i, act in enumerate(actions[:4]):
            clean = _clean_action(act)
            if not clean:
                continue
            cb_data = _trim_callback("act:", clean)

            style_key = (styles[i] if styles and i < len(styles) else None)
            style_val, emoji = _STYLE_MAP.get(style_key or "", (None, ""))
            label = f"{emoji} {clean}" if emoji else clean

            btn_kwargs = {"text": label, "callback_data": cb_data}
            if style_val:
                btn_kwargs["style"] = style_val
            rows.append([InlineKeyboardButton(**btn_kwargs)])

    menu_label = "📋 Меню" if lang == "ru" else "📋 Menu"
    loc_label = "📍" 
    gm_label = "❓ ГМ" if lang == "ru" else "❓ GM"
    rows.append([
        InlineKeyboardButton(text=menu_label, callback_data="gamemenu:open", style="primary"),
        InlineKeyboardButton(text=loc_label, callback_data="gamemenu:locinfo"),
        InlineKeyboardButton(text=gm_label, callback_data="gamemenu:askgm", style="success"),
    ])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def rest_keyboard(lang: str) -> InlineKeyboardMarkup:
    if lang == "ru":
        return InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="☀️ Короткий отдых", callback_data="gamemenu:short_rest", style="success")],
            [InlineKeyboardButton(text="🌙 Длинный отдых", callback_data="gamemenu:long_rest", style="success")],
            [InlineKeyboardButton(text="⬅️ Назад", callback_data="gamemenu:open", style="primary")],
        ])
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="☀️ Short Rest", callback_data="gamemenu:short_rest", style="success")],
        [InlineKeyboardButton(text="🌙 Long Rest", callback_data="gamemenu:long_rest", style="success")],
        [InlineKeyboardButton(text="⬅️ Back", callback_data="gamemenu:open", style="primary")],
    ])


def game_menu_keyboard(lang: str) -> InlineKeyboardMarkup:
    if lang == "ru":
        return InlineKeyboardMarkup(inline_keyboard=[
            [
                InlineKeyboardButton(text="📊 Персонаж", callback_data="gamemenu:stats", style="primary"),
                InlineKeyboardButton(text="🎒 Инвентарь", callback_data="gamemenu:inv", style="primary"),
            ],
            [
                InlineKeyboardButton(text="⚡ Способности", callback_data="gamemenu:abilities", style="primary"),
                InlineKeyboardButton(text="📜 Задание", callback_data="gamemenu:quest", style="primary"),
            ],
            [
                InlineKeyboardButton(text="🗺 Локация", callback_data="gamemenu:location", style="primary"),
                InlineKeyboardButton(text="🛏 Отдых", callback_data="gamemenu:rest", style="success"),
            ],
            [
                InlineKeyboardButton(text="🔎 Осмотр", callback_data="gamemenu:inspect", style="success"),
                InlineKeyboardButton(text="❓ Спросить ГМа", callback_data="gamemenu:askgm", style="success"),
            ],
            [
                InlineKeyboardButton(text="🔄 Новая игра", callback_data="gamemenu:newgame", style="danger"),
            ],
            [InlineKeyboardButton(text="⬅️ Назад к игре", callback_data="gamemenu:close")],
        ])
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="📊 Character", callback_data="gamemenu:stats", style="primary"),
            InlineKeyboardButton(text="🎒 Inventory", callback_data="gamemenu:inv", style="primary"),
        ],
        [
            InlineKeyboardButton(text="⚡ Abilities", callback_data="gamemenu:abilities", style="primary"),
            InlineKeyboardButton(text="📜 Quest", callback_data="gamemenu:quest", style="primary"),
        ],
        [
            InlineKeyboardButton(text="🗺 Location", callback_data="gamemenu:location", style="primary"),
            InlineKeyboardButton(text="🛏 Rest", callback_data="gamemenu:rest", style="success"),
        ],
        [
            InlineKeyboardButton(text="🔎 Inspect", callback_data="gamemenu:inspect", style="success"),
            InlineKeyboardButton(text="❓ Ask GM", callback_data="gamemenu:askgm", style="success"),
        ],
        [
            InlineKeyboardButton(text="🔄 New game", callback_data="gamemenu:newgame", style="danger"),
        ],
        [InlineKeyboardButton(text="⬅️ Back to game", callback_data="gamemenu:close")],
    ])


def inventory_item_keyboard(item_index: int, lang: str = "en") -> InlineKeyboardMarkup:
    if lang == "ru":
        return InlineKeyboardMarkup(inline_keyboard=[
            [
                InlineKeyboardButton(text="🔧 Использовать", callback_data=f"inv:use:{item_index}", style="success"),
                InlineKeyboardButton(text="🗑 Выбросить", callback_data=f"inv:drop:{item_index}", style="danger"),
            ],
            [InlineKeyboardButton(text="⬅️ Назад", callback_data="inv:back", style="primary")],
        ])
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="🔧 Use", callback_data=f"inv:use:{item_index}", style="success"),
            InlineKeyboardButton(text="🗑 Drop", callback_data=f"inv:drop:{item_index}", style="danger"),
        ],
        [InlineKeyboardButton(text="⬅️ Back", callback_data="inv:back", style="primary")],
    ])


def inventory_list_keyboard(items: list[dict]) -> InlineKeyboardMarkup:
    buttons = []
    for i, item in enumerate(items[:10]):
        name = item.get("name", "???")
        qty = item.get("quantity", 1)
        label = f"{name} x{qty}" if qty > 1 else name
        buttons.append([InlineKeyboardButton(text=label, callback_data=f"inv:select:{i}")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def abilities_list_keyboard(abilities: list[dict], lang: str = "en") -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    for i, ab in enumerate(abilities[:12]):
        name = ab.get("name", "???")
        atype = ab.get("type", "")
        icon = "⚡" if atype == "active" else "🔹"
        rows.append([InlineKeyboardButton(text=f"{icon} {name}", callback_data=f"ability:select:{i}")])
    back_label = "⬅️ Назад" if lang == "ru" else "⬅️ Back"
    rows.append([InlineKeyboardButton(text=back_label, callback_data="ability:back", style="primary")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def ability_detail_keyboard(idx: int, lang: str = "en") -> InlineKeyboardMarkup:
    back_label = "⬅️ Назад" if lang == "ru" else "⬅️ Back"
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=back_label, callback_data="ability:back", style="primary")],
    ])
