"""Inline keyboard builders — all text localized."""
from __future__ import annotations

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, WebAppInfo

from bot.config import settings

# --- World presets: combined genre+tone+theme in one step ---

_WORLDS = {
    "ru": {
        "star_wars": "⭐ Звёздные войны",
        "lotr": "💍 Властелин Колец",
        "harry_potter": "🧙 Гарри Поттер",
        "witcher": "🐺 Ведьмак",
        "marvel": "🦸 Marvel",
        "got": "🐉 Игра Престолов",
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
        "star_wars": "⭐ Star Wars",
        "lotr": "💍 Lord of the Rings",
        "harry_potter": "🧙 Harry Potter",
        "witcher": "🐺 The Witcher",
        "marvel": "🦸 Marvel",
        "got": "🐉 Game of Thrones",
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
            InlineKeyboardButton(text=w["star_wars"], callback_data="world:star_wars"),
            InlineKeyboardButton(text=w["lotr"], callback_data="world:lotr"),
        ],
        [
            InlineKeyboardButton(text=w["harry_potter"], callback_data="world:harry_potter"),
            InlineKeyboardButton(text=w["witcher"], callback_data="world:witcher"),
        ],
        [
            InlineKeyboardButton(text=w["marvel"], callback_data="world:marvel"),
            InlineKeyboardButton(text=w["got"], callback_data="world:got"),
        ],
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
        "epic":    "🔥 Эпика и героизм",
        "dark":    "💀 Мрачно и жёстко",
        "fun":     "😄 Лёгкий и весёлый",
        "horror":  "😱 Ужас и выживание",
        "intrigue":"🕵️ Тайны и интриги",
    },
    "en": {
        "epic":    "🔥 Epic & Heroic",
        "dark":    "💀 Dark & Brutal",
        "fun":     "😄 Fun & Lighthearted",
        "horror":  "😱 Horror & Survival",
        "intrigue":"🕵️ Mystery & Intrigue",
    },
}

_TONE_HINTS = {
    "ru": {
        "epic":     "«Властелин Колец», оригинальные «Звёздные войны»",
        "dark":     "«Игра Престолов», «Ведьмак»",
        "fun":      "«Стражи Галактики», «Джуманджи»",
        "horror":   "«Чужой», «Очень странные дела»",
        "intrigue": "«Шерлок», «Достать ножи»",
    },
    "en": {
        "epic":     "Lord of the Rings, original Star Wars",
        "dark":     "Game of Thrones, The Witcher",
        "fun":      "Guardians of the Galaxy, Jumanji",
        "horror":   "Alien, Stranger Things",
        "intrigue": "Sherlock, Knives Out",
    },
}

TONE_DESCRIPTIONS = {
    "epic": (
        "Heroic, epic, inspiring. Grand battles, noble sacrifices, triumph against the odds. "
        "Good and evil are clear. The hero can struggle but ultimately rises. Emotional, uplifting moments. "
        "Think Lord of the Rings, original Star Wars trilogy."
    ),
    "dark": (
        "Dark, brutal, morally gray. No plot armor — anyone can die. Violence has real weight and consequences. "
        "Difficult choices with no right answer. Betrayal, politics, survival of the cunning. "
        "Think Game of Thrones, The Witcher."
    ),
    "fun": (
        "Lighthearted, witty, comedic. Absurd situations, pop culture humor, sarcastic NPCs, lucky accidents. "
        "Danger exists but the mood stays fun. Don't take anything too seriously. "
        "Think Guardians of the Galaxy, Jumanji, Terry Pratchett."
    ),
    "horror": (
        "Tense, oppressive, terrifying. Something is hunting the player. Resources are scarce, trust is fragile. "
        "Psychological pressure, jump scares, body horror, creeping dread. Survival is the victory. "
        "Think Alien, Stranger Things, Resident Evil."
    ),
    "intrigue": (
        "Suspenseful, cerebral, full of secrets. Everyone has hidden motives. Puzzles, deception, investigation. "
        "Combat is rare but decisive. The real weapon is information. Plot twists are frequent. "
        "Think Sherlock Holmes, Knives Out, political thrillers."
    ),
}


def tone_keyboard(lang: str) -> InlineKeyboardMarkup:
    tones = _TONES.get(lang, _TONES["en"])
    hints = _TONE_HINTS.get(lang, _TONE_HINTS["en"])
    rows = []
    for key in ("epic", "dark", "fun", "horror", "intrigue"):
        rows.append([InlineKeyboardButton(
            text=f"{tones[key]}  —  {hints[key]}",
            callback_data=f"tone:{key}",
        )])
    return InlineKeyboardMarkup(inline_keyboard=rows)


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


_DISCLAIMER_PATTERNS = ("если есть", "if you have", "нет в", "нет у", "если ", "if ", "maybe", "возможно")


def _clean_action(text: str) -> str:
    """Strip HTML, trim to fit Telegram button. Validates completeness."""
    import re
    clean = _strip_html(text)
    clean = clean.strip("«»\"'")

    # check parenthetical content: disclaimer → reject, ability name → strip parens and keep
    paren_match = re.search(r"\(([^)]*)\)?", clean)
    if paren_match:
        inside = paren_match.group(1).lower()
        if any(p in inside for p in _DISCLAIMER_PATTERNS):
            return ""
        clean = re.sub(r"\s*\([^)]*\)?\s*", " ", clean).strip()

    # reject bare verbs (single word with no object/target)
    if " " not in clean.strip():
        return ""

    if len(clean) <= 32:
        result = clean
    else:
        cut = clean[:32]
        last_space = cut.rfind(" ")
        if last_space > 10:
            cut = cut[:last_space]
        result = cut

    # drop trailing adjective-like words (Russian: -ый, -ий, -ой, -ая, -ые, -ое, -ую, -ей)
    words = result.split()
    if len(words) > 2:
        last = words[-1].lower()
        if any(last.endswith(s) for s in ("ый", "ий", "ой", "ая", "ые", "ое", "ую", "ей", "ых", "их")):
            result = " ".join(words[:-1])

    # after trimming, if only one word remains — it's incomplete
    if " " not in result.strip():
        return ""

    return result


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


# --- #9: Inventory categories ---

ITEM_CAT_TYPES: dict[str, tuple[str, ...] | None] = {
    "w": ("weapon",),
    "a": ("armor", "shield"),
    "p": ("potion", "consumable"),
    "o": None,
}

_CAT_META = {
    "w": {"emoji": "⚔️", "ru": "Оружие", "en": "Weapons"},
    "a": {"emoji": "🛡", "ru": "Броня", "en": "Armor"},
    "p": {"emoji": "🧪", "ru": "Зелья", "en": "Potions"},
    "o": {"emoji": "📦", "ru": "Прочее", "en": "Other"},
}

_INV_PAGE = 8


def item_category(item: dict) -> str:
    itype = (item.get("type") or "misc").lower()
    for k, types in ITEM_CAT_TYPES.items():
        if types and itype in types:
            return k
    return "o"


def _group_items(items: list[dict]) -> dict[str, list[tuple[int, dict]]]:
    groups: dict[str, list[tuple[int, dict]]] = {k: [] for k in ITEM_CAT_TYPES}
    for i, item in enumerate(items):
        groups[item_category(item)].append((i, item))
    return groups


def cat_label(cat: str, lang: str) -> str:
    m = _CAT_META.get(cat, _CAT_META["o"])
    return f"{m['emoji']} {m.get(lang, m['en'])}"


def inventory_categories_keyboard(items: list[dict], lang: str = "en") -> InlineKeyboardMarkup:
    groups = _group_items(items)
    rows: list[list[InlineKeyboardButton]] = []
    for k in ITEM_CAT_TYPES:
        g = groups[k]
        if not g:
            continue
        label = f"{cat_label(k, lang)} ({len(g)})"
        rows.append([InlineKeyboardButton(text=label, callback_data=f"inv:cat:{k}")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def inventory_cat_items_keyboard(
    items: list[dict], cat: str, lang: str = "en", page: int = 0,
) -> InlineKeyboardMarkup:
    groups = _group_items(items)
    cat_items = groups.get(cat, [])
    total = len(cat_items)
    start = page * _INV_PAGE
    page_items = cat_items[start : start + _INV_PAGE]

    rows: list[list[InlineKeyboardButton]] = []
    for idx, item in page_items:
        name = item.get("name", "???")
        qty = item.get("quantity", 1)
        eq = "✅ " if item.get("equipped") else ""
        label = f"{eq}{name} ×{qty}" if qty > 1 else f"{eq}{name}"
        rows.append([InlineKeyboardButton(text=label, callback_data=f"inv:select:{idx}")])

    nav: list[InlineKeyboardButton] = []
    if page > 0:
        nav.append(InlineKeyboardButton(text="⬅️", callback_data=f"inv:cat:{cat}:{page - 1}"))
    if start + _INV_PAGE < total:
        nav.append(InlineKeyboardButton(text="➡️", callback_data=f"inv:cat:{cat}:{page + 1}"))
    if nav:
        rows.append(nav)

    back = "⬅️ Категории" if lang == "ru" else "⬅️ Categories"
    rows.append([InlineKeyboardButton(text=back, callback_data="inv:cats")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


# --- #10: Combat quick buttons ---

def _combat_quick_rows(
    inventory: list[dict], abilities: list[dict], lang: str,
) -> list[list[InlineKeyboardButton]]:
    rows: list[list[InlineKeyboardButton]] = []

    weapons: list[InlineKeyboardButton] = []
    for i, item in enumerate(inventory):
        if item.get("type", "").lower() == "weapon" and item.get("equipped"):
            label = f"⚔️ {item.get('name', '???')}"[:28]
            weapons.append(InlineKeyboardButton(
                text=label, callback_data=_trim_callback("cbt:w:", str(i)), style="danger",
            ))
            if len(weapons) >= 2:
                break
    if weapons:
        rows.append(weapons)

    potions: list[InlineKeyboardButton] = []
    for i, item in enumerate(inventory):
        if (item.get("type") or "").lower() in ("potion", "consumable"):
            name = item.get("name", "???")
            qty = item.get("quantity", 1)
            label = f"🧪 {name}"
            if qty > 1:
                label += f" ×{qty}"
            label = label[:28]
            potions.append(InlineKeyboardButton(
                text=label, callback_data=_trim_callback("cbt:p:", str(i)), style="success",
            ))
            if len(potions) >= 2:
                break
    if potions:
        rows.append(potions)

    active_abs: list[InlineKeyboardButton] = []
    for i, ab in enumerate(abilities):
        if ab.get("type", "").lower() == "active":
            label = f"✨ {ab.get('name', '???')}"[:28]
            active_abs.append(InlineKeyboardButton(
                text=label, callback_data=_trim_callback("cbt:a:", str(i)), style="primary",
            ))
            if len(active_abs) >= 2:
                break
    if active_abs:
        rows.append(active_abs)

    return rows


def actions_keyboard(
    actions: list[str] | None = None,
    lang: str = "en",
    styles: list[str] | None = None,
    combat_data: dict | None = None,
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

    if combat_data:
        rows.extend(_combat_quick_rows(
            combat_data.get("inventory", []),
            combat_data.get("abilities", []),
            lang,
        ))

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


def _webapp_row(label: str) -> list[InlineKeyboardButton]:
    if not settings.webapp_url:
        return []
    return [InlineKeyboardButton(text=label, web_app=WebAppInfo(url=settings.webapp_url))]


def game_menu_keyboard(lang: str) -> InlineKeyboardMarkup:
    if lang == "ru":
        rows = []
        webapp = _webapp_row("🎮 Панель персонажа")
        if webapp:
            rows.append(webapp)
        rows.extend([
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
        return InlineKeyboardMarkup(inline_keyboard=rows)

    rows = []
    webapp = _webapp_row("🎮 Character Dashboard")
    if webapp:
        rows.append(webapp)
    rows.extend([
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
    return InlineKeyboardMarkup(inline_keyboard=rows)


def inventory_item_keyboard(item_index: int, lang: str = "en") -> InlineKeyboardMarkup:
    if lang == "ru":
        return InlineKeyboardMarkup(inline_keyboard=[
            [
                InlineKeyboardButton(text="🔧 Использовать", callback_data=f"inv:use:{item_index}", style="success"),
                InlineKeyboardButton(text="🔍 Осмотреть", callback_data=f"inv:inspect:{item_index}", style="primary"),
            ],
            [InlineKeyboardButton(text="🗑 Выбросить", callback_data=f"inv:drop:{item_index}", style="danger")],
            [InlineKeyboardButton(text="⬅️ Назад", callback_data="inv:cats", style="primary")],
        ])
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="🔧 Use", callback_data=f"inv:use:{item_index}", style="success"),
            InlineKeyboardButton(text="🔍 Inspect", callback_data=f"inv:inspect:{item_index}", style="primary"),
        ],
        [InlineKeyboardButton(text="🗑 Drop", callback_data=f"inv:drop:{item_index}", style="danger")],
        [InlineKeyboardButton(text="⬅️ Back", callback_data="inv:cats", style="primary")],
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
