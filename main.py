# main.py — веб-вход для Render (webhook) в твоём стиле логирования
from __future__ import annotations

# --- грузим .env, как в runner.py ------------------------------------------------
try:
    from dotenv import load_dotenv  # pip install python-dotenv
    load_dotenv(override=False)
except Exception:
    pass

import os
from typing import Optional

from fastapi import FastAPI, Request
from loguru import logger

from aiogram import Bot, Dispatcher, types
from aiogram.enums import ParseMode
from aiogram.client.default import DefaultBotProperties
from aiogram.client.session.aiohttp import AiohttpSession

# твои модули
from app.db import ensure_db  # гарантируем схему БД до старта
# если у тебя есть app.config.settings (как в runner.py), можно тянуть токен оттуда
try:
    from app.config import settings  # type: ignore
except Exception:
    settings = None  # fallback на os.getenv

# ────────────────────────── ENV ──────────────────────────
BOT_TOKEN = (getattr(settings, "BOT_TOKEN", None) if settings else None) or os.getenv("BOT_TOKEN")
BASE_URL = os.getenv("BASE_URL")  # например, https://your-app.onrender.com
WEBHOOK_SECRET = os.getenv("WEBHOOK_SECRET", "secret123")

# ────────────────────────── Хелперы (как в runner.py) ──────────────────────────
def _try_import(path: str):
    try:
        module = __import__(path, fromlist=["router"])
        if hasattr(module, "router"):
            return module
    except Exception:
        return None
    return None

def _build_session() -> AiohttpSession:
    """
    Совместимо с твоей логикой: поддержка PROXY_URL, без лишних таймаутов/коннекторов.
    """
    proxy: Optional[str] = os.getenv("PROXY_URL")
    if proxy:
        logger.info("[BOOT] proxy enabled via PROXY_URL")
        try:
            return AiohttpSession(proxy=proxy)
        except TypeError:
            logger.warning("[BOOT] proxy kw not supported by AiohttpSession, falling back to default session")
            return AiohttpSession()
    return AiohttpSession()

def _build_bot() -> Bot:
    if not BOT_TOKEN:
        raise RuntimeError("BOT_TOKEN not set")
    session = _build_session()
    return Bot(
        token=BOT_TOKEN,
        session=session,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )

def _include_if_present(dp: Dispatcher, mod, name: str):
    if mod and getattr(mod, "router", None):
        dp.include_router(mod.router)
        logger.info(f"[BOOT] router on → {name}")
    else:
        logger.info(f"[BOOT] router off → {name} (module not found)")

def _build_dispatcher() -> Dispatcher:
    dp = Dispatcher()

    # порядок как у тебя: старт/команды → UI → админка/миссии → остальное → text_flow (последним)
    start_handlers        = _try_import("app.handlers.start")
    ui_handlers           = _try_import("app.handlers.ui")
    admin_handlers        = _try_import("app.handlers.admin")          # legacy
    missions_handlers     = _try_import("app.handlers.missions")
    admin_users_handlers  = _try_import("app.handlers.admin_users")    # новая админка участников
    basic_handlers        = _try_import("app.handlers.basic")          # legacy
    text_flow_handlers    = _try_import("app.handlers.text_flow")      # ассистент — последним

    _include_if_present(dp, start_handlers, "start")
    _include_if_present(dp, ui_handlers, "ui")
    _include_if_present(dp, admin_handlers, "admin (legacy)")
    _include_if_present(dp, missions_handlers, "missions")
    _include_if_present(dp, admin_users_handlers, "admin_users")
    _include_if_present(dp, basic_handlers, "basic (legacy)")
    _include_if_present(dp, text_flow_handlers, "text_flow (assistant)")

    # единая отладочная мидлварь (если есть)
    try:
        from app.middlewares.debug import DebugMiddleware  # type: ignore
        dbg = DebugMiddleware()
        dp.update.middleware(dbg)
        dp.message.middleware(dbg)
        dp.callback_query.middleware(dbg)
        logger.info("[BOOT] DebugMiddleware attached")
    except Exception:
        pass

    return dp

# ────────────────────────── Инициализация ──────────────────────────
bot = _build_bot()
dp = _build_dispatcher()
app = FastAPI()

# ────────────────────────── Webhook endpoint ───────────────────────
@app.post("/webhook")
async def telegram_webhook(request: Request):
    # Проверка секрета от Telegram (можно выключить, если не нужен)
    if WEBHOOK_SECRET:
        if request.headers.get("x-telegram-bot-api-secret-token") != WEBHOOK_SECRET:
            return {"ok": False, "detail": "bad secret"}

    data = await request.json()
    update = types.Update.model_validate(data)
    # ВАЖНО: быстрая отдача 200 OK — иначе Телега дублирует апдейт
    await dp.feed_update(bot, update)
    return {"ok": True}

# ────────────────────────── Жизненный цикл ─────────────────────────
@app.on_event("startup")
async def on_startup():
    # Логгер в консоль (как у тебя в runner.py)
    logger.remove()
    logger.add(lambda msg: print(msg, end=""), level=os.getenv("LOG_LEVEL", "DEBUG"))

    # Подсказки про окружение:
    if os.getenv("PROXY_URL"):
        logger.info("[ENV] PROXY_URL is set")
    if not os.getenv("REPORT_CHAT_ID"):
        logger.warning("[ENV] REPORT_CHAT_ID is not set (групповые оповещения не будут отправляться)")

    if not BASE_URL:
        raise RuntimeError("BASE_URL is required (public https URL)")

    # Гарантируем схему БД
    await ensure_db()
    logger.info("[DB] schema ensured")

    # Ставим вебхук
    url = f"{BASE_URL.rstrip('/')}/webhook"
    await bot.set_webhook(
        url=url,
        secret_token=WEBHOOK_SECRET or None,
        drop_pending_updates=True,
    )
    logger.info(f"[WEBHOOK] set to {url}")

    # Побочные циклы (если есть)
    try:
        from app.services.reminders import start_reminders_loop  # type: ignore
        import asyncio
        asyncio.create_task(start_reminders_loop(bot))
        logger.info("[BOOT] reminders loop started")
    except Exception:
        pass

@app.on_event("shutdown")
async def on_shutdown():
    try:
        await bot.delete_webhook(drop_pending_updates=False)
    except Exception:
        pass
    try:
        await bot.session.close()
    except Exception:
        pass
    logger.info("[BOOT] graceful shutdown complete")

# health-check
@app.get("/")
async def health():
    return {"status": "ok"}
