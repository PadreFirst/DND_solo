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

## Что уже реализовано

- Telegram polling на `aiogram`.
- База данных (`SQLAlchemy` + `aiosqlite`), автосоздание таблиц.
- Контекст хода: стейт персонажа + локация + последние сообщения.
- Генерация хода через Gemini с требованием JSON-формата.
- Исполнение механики в коде:
  - skill checks / attack / saving throws;
  - атаки врагов (бросок атаки + урон кубиками);
  - изменение HP;
  - базовые изменения инвентаря;
  - XP и level up;
  - репутация фракций.
- Кнопки действий 1-5, отдельное меню.
- FastAPI endpoint для мини-аппа:
  - `GET /healthz`
  - `GET /api/character/{telegram_user_id}`

## Ограничения текущей версии

Это рабочий фундамент, но не полный "hardcore движок DND 5e":
- нет полного валидатора всех условий/статусов,
- нет полной боевой стейт-машины со всеми реакциями,
- нет полного флоу торговли/крафта/даунтайма,
- нет полноценного фронтенда мини-аппа (только backend API).

Основа подготовлена так, чтобы следующий шаг был быстрым: можно расширять таблицы/правила без переписывания ядра.
