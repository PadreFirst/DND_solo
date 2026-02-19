# DnD Telegram Bot — AI Game Master

AI-powered solo DnD 5e (2024 Revised) adventure bot for Telegram, running on Gemini 3 Flash.

## Quick Start

1. **Create a Telegram bot** via [@BotFather](https://t.me/BotFather) and get the token.

2. **Get a Gemini API key** from [Google AI Studio](https://aistudio.google.com/apikey).

3. **Set up environment:**
   ```bash
   cp .env.example .env
   # Edit .env with your tokens
   ```

4. **Install dependencies:**
   ```bash
   pip install -r requirements.txt
   ```

5. **Run:**
   ```bash
   python -m bot.main
   ```

The bot starts in polling mode — no webhook or tunnel needed for development.

## Architecture

Two-pass Gemini architecture to prevent hallucinations:

- **Pass 1 (Structured JSON):** Gemini analyzes the player's action and decides what game mechanics apply (skill checks, attacks, damage, inventory changes, etc.)
- **Game Engine:** Code rolls all dice, calculates damage, applies DnD rules deterministically.
- **Pass 2 (Narrative):** Gemini receives the mechanical results and writes an immersive story.

The database is the single source of truth for all game state (HP, inventory, XP, etc.) — the AI reads state from DB every turn and never relies on its own "memory" for numbers.

## Commands

- `/start` — Begin a new adventure (onboarding flow)
- `/stats` — View character sheet
- `/inventory` — Manage inventory
- `/quest` — View current quest
- `/debug` — Show full game state JSON (dev mode)

## Project Structure

```
bot/
  main.py              — Entry point
  config.py            — Settings from .env
  handlers/            — Telegram message/callback handlers
  services/            — Business logic (Gemini, game engine, memory, personalization)
  models/              — SQLAlchemy ORM models
  db/                  — Database engine
  templates/prompts/   — Prompt templates for Gemini
  templates/messages/  — Multilingual UI text
  utils/               — Dice roller, formatters, keyboards
```
