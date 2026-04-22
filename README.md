# DND Telegram GM Bot

Телеграм-бот "Гейм-мастер" для текстовой DND-сессии:
- ведет сцену через Gemini (через ваш Cloudflare proxy),
- применяет броски и HP-изменения кодом,
- хранит состояние в SQLite,
- отдает API для мини-аппа: `GET /api/character/{telegram_user_id}`.

## Быстрый старт

1. Установить Python 3.11+.
2. Создать и активировать окружение:
   - Windows PowerShell:
     - `python -m venv .venv`
     - `.venv\Scripts\Activate.ps1`
3. Установить зависимости:
   - `pip install -r requirements.txt`
4. Проверить `.env`:
   - `BOT_TOKEN`
   - `GEMINI_API_KEY`
   - `GEMINI_PROXY`
   - `GEMINI_PROXY_TOKEN` (если включена проверка токена в worker)
   - `DATABASE_URL=sqlite+aiosqlite:///./dnd_bot.db`
   - `WEB_APP_URL` (опционально, ссылка на Telegram Mini App)
5. Запуск:
   - `python -m bot.main`

## Mini App (React + TS)

Фронт лежит в `miniapp/`.

1. Сборка фронта:
   - `cd miniapp`
   - `npm install`
   - `npm run build`
2. После сборки backend автоматически отдает мини-апп:
   - `GET /mini-app`
3. Для кнопки "Мой персонаж" в Telegram:
   - укажи в `.env` переменную `WEB_APP_URL`
   - пример: `WEB_APP_URL=https://your-domain/mini-app/`

## Статус ТЗ (что из figma-борды применено)

Легенда: ✅ — работает в коде и в UI; 🟡 — описано в `system_prompt.md` (LLM знает, но код не энфорсит); ⬜ — не реализовано.

| Блок ТЗ | Статус | Где |
|---|---|---|
| Создание персонажа под сеттинг (раса/класс/экипировка) | ✅ | `game_service.py::_apply_character_setup` (LLM возвращает `character_setup`) |
| Движок бросков: skill / attack / save / advantage / disadvantage | ✅ | `services/engine.py`, `services/dice.py` |
| Бросок урона оружия (с критом ×2 кости) | ✅ | `engine.roll_damage` |
| Сцена боя (HP/КД всех врагов, отображение ДО атаки) | ✅ | `TurnPlan.scene_enemies`, `GameSession.scene_state_json` |
| Применение урона к HP конкретного врага по имени | ✅ | `process_turn` + `_find_scene_target` |
| Мехблок (расчёты/броски) ДО нарратива | ✅ | `process_turn`: `pre_block → narrative → post_block` |
| Инвентарь в `/inventory` с формулой урона (`1d10`, `2d6+1`) | ✅ | `format_inventory_detailed` |
| Команды /start /stats /inventory /quest /hint /rest /new /help | ✅ | `handlers.py`, `main.py::SIDE_PANEL_COMMANDS` |
| Inline-меню == slash-меню (одно и то же действия) | ✅ | `ui.py::menu_keyboard` + `SIDE_PANEL_COMMANDS` |
| XP / level up / HP max пересчёт | ✅ | `process_turn` |
| Атаки врагов (d20 + бонус против КД игрока, урон) | ✅ | `process_turn` |
| Телеграм Mini App (readonly стейт) | ✅ | `miniapp/`, telegram-web-app.js подключён |
| 15 условий (Blinded/Poisoned/…) — автомодификаторы на броски | ✅ | `engine.compute_auto_modifiers` |
| Типы урона + resist/immunity/vulnerability | ✅ | `engine.apply_damage(damage_type)` + `resistances_json` |
| Погода / время суток — автоэффекты на броски | ✅ | `engine.compute_auto_modifiers` (туман/дождь/шторм/снег/ночь) |
| Death saves (3/3 цикл: nat20→встаёт, nat1→2 провала, 3✅→стабилизирован, 3❌→смерть) | ✅ | `engine.roll_death_save` + `_handle_death_save_turn` |
| Короткий/длинный отдых (Hit Dice, снятие состояний, /rest) | ✅ | `engine.perform_short_rest/long_rest` + callback `rest:*` |
| Adventure summary каждые 10 ходов (background task) | ✅ | `gemini.summarize_adventure` + `_refresh_adventure_summary` |
| Минимальные Hard Checks (нет оружия → блок атаки с объяснением) | ✅ | `process_turn` перед `make_attack_roll` |
| Смена моделей Gemini Flash/Pro по сложности хода | ✅ | `gemini.py` (opening → heavy, turn → flash, summary → flash) |
| Репутация фракций — авто-бонус/штраф к соц.броскам | 🟡 | таблица + LLM дают `reputation_change`; авто-±2 к соц.броскам зависит от NPC-контекста (Batch C) |
| Торговля (сабрежим NPC с inventory_json) | 🟡 | LLM следует правилам; отдельного кодового сабрежима нет (Batch B) |
| Крафт: рецепт + компоненты + проверка навыка | 🟡 | поля `known_recipes_json` + правила в prompt; кодового флоу нет (Batch B) |
| Combat state machine (инициатива, раунды, action economy) | 🟡 | поля в БД есть; код их не использует (Batch B) |
| Attunement (макс 3 магических, проверки бонусов) | 🟡 | поле `attunement_json` есть; код не валидирует (Batch C) |
| Carrying weight (STR×7 кг) | ⬜ | не реализовано (Batch C) |
| Guided onboarding (визарт: вселенная → стиль → персонаж → статы) | ⬜ | сейчас один концепт-месседж (Batch C) |
| Passive Perception vs скрытые объекты | ⬜ | формула есть в движке, скрытые объекты в сценах не реализованы (Batch C) |

**Вывод:** ядро ТЗ (движок бросков, сцена боя, урон, инвентарь с кубами, сеттинг-осознанная генерация) — реализовано в коде. Остальное (условия, погода, крафт, торговля) описано в `system_prompt.md` и LLM использует эти правила нарративно, но жёсткого кодового энфорсмента нет. Это осознанный выбор приоритетов — сначала то, что игрок чувствует в каждом ходу.

## Архитектура (коротко)

- `bot/main.py` — запуск polling + FastAPI в одном процессе.
- `bot/handlers.py` — Telegram handlers (команды + callback'и + текст).
- `bot/services/game_service.py` — оркестратор хода, LLM ⇄ БД ⇄ движок.
- `bot/services/gemini.py` — тонкая обёртка над Gemini + JSON-схема TurnPlan.
- `bot/services/engine.py` — чистые D&D-механики (броски, урон, HP).
- `bot/services/dice.py` — парсер `NdM[+K]`.
- `bot/schemas.py` — Pydantic-схема ответа LLM.
- `bot/models.py` — ORM таблицы.
- `miniapp/` — Telegram Mini App (React + Vite), readonly просмотр стейта.
- `system_prompt.md` — поведенческий контракт GM (560 строк, LLM видит целиком).

## FastAPI endpoints

- `GET /dnd_bot/healthz`
- `GET /dnd_bot/api/character/{telegram_user_id}`
- `/dnd_bot/` — статик мини-аппа
