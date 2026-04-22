from __future__ import annotations

from fastapi import Depends, FastAPI, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy.ext.asyncio import AsyncSession

from bot.config import ROOT_DIR
from bot.db import get_session
from bot.services.game_service import GameService


def create_app(game: GameService) -> FastAPI:
    app = FastAPI(title="DND Bot API")

    @app.get("/dnd_bot/healthz")
    async def healthz() -> dict:
        return {"ok": True}

    @app.get("/dnd_bot/api/character/{telegram_user_id}")
    async def get_character(telegram_user_id: int, db: AsyncSession = Depends(get_session)) -> dict:
        try:
            return await game.build_character_api_payload(db, telegram_user_id)
        except ValueError as e:
            raise HTTPException(status_code=404, detail=str(e))

    mini_dist = ROOT_DIR / "miniapp" / "dist"
    if mini_dist.exists():
        @app.get("/dnd_bot", include_in_schema=False)
        async def mini_redirect() -> RedirectResponse:
            return RedirectResponse(url="/dnd_bot/", status_code=307)

        app.mount("/dnd_bot", StaticFiles(directory=str(mini_dist), html=True), name="mini_app")
    else:
        @app.get("/dnd_bot", response_class=HTMLResponse)
        async def mini_stub() -> str:
            return (
                "<h3>Mini App is not built yet.</h3>"
                "<p>Run: <code>cd miniapp && npm install && npm run build</code></p>"
            )

    return app
