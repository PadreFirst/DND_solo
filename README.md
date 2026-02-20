# DnD Solo — AI Game Master Telegram Bot

Telegram-бот для одиночных DnD-приключений с AI Game Master на базе Google Gemini.

## Возможности

- **AI Game Master** — двухпроходная архитектура: Gemini решает механику (JSON), Python считает кубики, Gemini пишет нарратив
- **DnD 5.5e** — полное соответствие правилам: броски, навыки, XP, инвентарь, уровни, AC, спасброски
- **Генерация персонажа** — свободное описание или 5 вопросов + AI создаёт карточку с правильными статами
- **Генерация мира** — пресеты (фэнтези, хоррор, киберпанк...) или своё описание
- **Адаптивная персонализация** — бот анализирует стиль игры и подстраивает контент
- **Без цензуры** (18+) — полный контент для взрослых, модерация для подростков
- **Typing indicator** — бот показывает «печатает...» во время генерации
- **Inline-кнопки** — варианты действий, игровое меню, управление инвентарём
- **Многоязычность** — русский, английский (расширяемо)

## Архитектура

```
Telegram → aiogram 3 → Handlers
                          ├── Pass 1: Gemini → MechanicsDecision (JSON)
                          ├── Game Engine: Python (dice, damage, XP)
                          └── Pass 2: Gemini → Narrative text
                       
SQLite (dev) / PostgreSQL (prod) — единственный источник правды
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
GEMINI_MODEL=gemini-2.0-flash
GEMINI_MODEL_HEAVY=
GEMINI_PROXY=
DATABASE_URL=sqlite+aiosqlite:///./dnd_bot.db
DEBUG=true
```

| Переменная | Описание |
|---|---|
| `BOT_TOKEN` | Токен Telegram-бота от @BotFather |
| `GEMINI_API_KEY` | API-ключ Google AI Studio |
| `GEMINI_MODEL` | Модель для игрового процесса (default: `gemini-2.0-flash`) |
| `GEMINI_MODEL_HEAVY` | Модель для создания мира/персонажа (опционально, например `gemini-2.5-pro-preview-05-06`) |
| `GEMINI_PROXY` | HTTP/SOCKS5 прокси для Gemini API (если нужен) |

### 3. Установить и запустить

```bash
python -m venv venv
venv\Scripts\activate      # Windows
# source venv/bin/activate  # Linux/Mac
pip install -r requirements.txt
python -m bot.main
```

## Деплой на сервер

```bash
ssh root@your-server "bash -s" < deploy.sh
```

Скрипт автоматически: остановит бот → обновит код → установит зависимости → пересоздаст БД → запустит → проверит версию.

## Прокси для Gemini API

Если сервер в регионе, где Gemini API недоступен:

```
GEMINI_PROXY=http://user:pass@proxy-host:port
# или
GEMINI_PROXY=socks5://user:pass@proxy-host:port
```

## Структура проекта

```
bot/
├── config.py              # Настройки из .env
├── main.py                # Точка входа
├── models/                # SQLAlchemy модели (User, Character, GameSession, Memory)
├── handlers/
│   ├── start.py           # Онбординг: язык → возраст → мир → персонаж → миссия
│   ├── game.py            # Игровой цикл: Pass 1 → Engine → Pass 2
│   └── inventory.py       # Управление инвентарём
├── services/
│   ├── gemini.py          # Gemini API: structured + narrative + proxy
│   ├── game_engine.py     # Детерминированная механика DnD
│   ├── character_gen.py   # Генерация персонажа
│   ├── memory.py          # Контекст и суммаризация
│   ├── personalization.py # Адаптивные предпочтения
│   └── prompt_builder.py  # Шаблоны промптов
├── templates/
│   ├── messages/           # i18n строки (ru.py, en.py)
│   └── prompts/            # Промпт-шаблоны для Gemini
├── utils/
│   ├── dice.py            # Криптографический рандом
│   ├── formatters.py      # Форматирование для Telegram
│   ├── i18n.py            # Мультиязычность
│   └── keyboards.py       # Inline-клавиатуры
└── middlewares/
    └── db_session.py      # DB-сессия на каждый хендлер
```

## Лицензия

MIT
