"""Simple i18n — pick the right message template module by language code."""
from __future__ import annotations

from types import ModuleType

from bot.templates.messages import en, ru

_MODULES: dict[str, ModuleType] = {
    "ru": ru,
    "en": en,
}


def t(key: str, lang: str = "ru", **kwargs: str) -> str:
    mod = _MODULES.get(lang, ru)
    template = getattr(mod, key, None)
    if template is None:
        template = getattr(ru, key, f"[{key}]")
    if kwargs:
        return template.format(**kwargs)
    return template
