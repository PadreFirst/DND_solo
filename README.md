# DnD Solo — AI Game Master Telegram Bot

Telegram-бот для одиночных DnD-приключений с AI Game Master на базе Google Gemini.
Персонаж, мир, миссия и сюжет генерируются AI. Механика — честные кубики по правилам D&D 5.5e.

## Возможности

- **AI Game Master** — Gemini генерирует механику (JSON) + нарратив в одном проходе
- **D&D 5.5e** — броски атаки, навыки, спасброски, AC, XP, левелинг, death saves, action economy
- **Мульти-модельность** — тяжёлые задачи (генерация мира/персонажа) на Pro, геймплей на Flash
- **Генерация персонажа** — свободное описание → AI + детерминированный код (статы, HP, AC, инвентарь)
- **Генерация мира** — пресеты (Star Wars, LotR, Harry Potter, Witcher, Marvel, GoT, классика) или своё описание
- **Тактические локации** — автоматическое описание при смене локации (выходы, укрытия, интерактивные объекты)
- **Категоризованный инвентарь** — оружие, броня, зелья, прочее с пагинацией
- **Боевые кнопки** — в бою: быстрый доступ к оружию, зельям и способностям
- **Способности класса** — активные и пассивные с описанием механики и перезарядки
- **Death Saving Throws** — при 0 HP: 3 броска спасения, стабилизация или гибель
- **Адаптивная персонализация** — бот анализирует стиль игры и подстраивает контент
- **Telegram Mini App** — дашборд персонажа: статы, инвентарь, способности, квест
- **Без цензуры** (18+) — полный контент для взрослых, модерация для подростков
- **Progressive статусы** — 30+ вариантов сообщений ожидания, автоматически сменяющихся
- **Контекстные кнопки** — варианты действий по результату бросков (успех/провал)
- **Многоязычность** — русский, английский (расширяемо)

## Архитектура

```
Telegram → aiogram 3 → Handlers
                          ├── Gemini → GameResponse (JSON: механика + нарратив)
                          ├── Game Engine: Python (dice, damage, XP, death saves)
                          └── Response assembly + Telegram UI
                       
SQLite (dev) / PostgreSQL (prod) — единственный источник правды

Mini App Dashboard ← aiohttp (port 8080) ← Cloudflare Tunnel
```

## Настройка

### 1. Клонировать

```bash
git clone https://github.com/PadreFirst/DND_solo.git
cd DND_solo
```

### 2. Создать `.env`

```
BOT_TOKEN=your_telegram_bot_token
GEMINI_API_KEY=your_gemini_api_key
GEMINI_MODEL=gemini-3-flash-preview
GEMINI_MODEL_HEAVY=gemini-3-pro-preview
GEMINI_PROXY=
DATABASE_URL=sqlite+aiosqlite:///./dnd_bot.db
WEBAPP_URL=
DEBUG=true
```

| Переменная | Описание |
|---|---|
| `BOT_TOKEN` | Токен Telegram-бота от @BotFather |
| `GEMINI_API_KEY` | API-ключ Google AI Studio |
| `GEMINI_MODEL` | Модель для геймплея (default: `gemini-3-flash-preview`) |
| `GEMINI_MODEL_HEAVY` | Модель для генерации мира/персонажа (default: пустая → используется `GEMINI_MODEL`) |
| `GEMINI_MODEL_LIGHT` | Модель для вспомогательных задач (локация, осмотр, ГМ-ответы) |
| `GEMINI_PROXY` | Cloudflare Worker или HTTP-прокси для Gemini API (если geo-blocked) |
| `WEBAPP_URL` | URL Mini App дашборда (опционально, e.g. `https://dnd.yourdomain.com`) |

### 3. Установить и запустить

```bash
python -m venv venv
source venv/bin/activate    # Linux/Mac
# venv\Scripts\activate     # Windows
pip install -r requirements.txt
python -m bot.main
```

## Деплой на сервер

```bash
ssh root@your-server "bash -s" < deploy.sh
```

Скрипт автоматически: остановит бот → обновит код → установит зависимости → запустит → проверит.

## Mini App Dashboard

Для работы Mini App нужен HTTPS-домен. Рекомендуется Cloudflare Tunnel:

```bash
bash setup_tunnel.sh
```

Далее — указать `WEBAPP_URL` в `.env` и настроить Menu Button бота через @BotFather.

## Структура проекта

```
bot/
├── config.py              # Настройки из .env
├── main.py                # Точка входа (aiogram + aiohttp)
├── models/                # SQLAlchemy модели (User, Character, GameSession, Memory)
├── handlers/
│   ├── start.py           # Онбординг: язык → возраст → мир → тон → персонаж → миссия
│   ├── game.py            # Игровой цикл + death saves + боевые кнопки
│   └── inventory.py       # Категоризованный инвентарь
├── services/
│   ├── gemini.py          # Gemini API: structured + narrative + multi-model + proxy
│   ├── game_engine.py     # Детерминированная механика D&D (dice, combat, death saves)
│   ├── character_gen.py   # Генерация персонажа (AI + код)
│   ├── memory.py          # Контекст и суммаризация истории
│   ├── personalization.py # Адаптивные предпочтения игрока
│   └── prompt_builder.py  # Шаблоны промптов для Gemini
├── templates/
│   ├── messages/          # i18n строки (ru.py, en.py)
│   └── prompts/           # Промпт-шаблоны
├── utils/
│   ├── dice.py            # Криптографический рандом
│   ├── formatters.py      # Форматирование для Telegram
│   ├── i18n.py            # Мультиязычность
│   └── keyboards.py       # Inline-клавиатуры (action, combat, inventory, menu)
├── web/
│   └── server.py          # aiohttp сервер для Mini App API
└── middlewares/
    └── db_session.py      # DB-сессия на каждый хендлер

static/                    # Mini App frontend (HTML/CSS/JS)
```

## Лицензия

MIT
