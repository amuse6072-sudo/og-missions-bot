# app/handlers/__init__.py
from __future__ import annotations
from aiogram import Dispatcher

# подключаем все роутеры хендлеров
from app.handlers import start as start_handlers
from app.handlers import ui as ui_handlers
from app.handlers import missions as missions_handlers
from app.handlers import admin_users as admin_users_handlers

def register(dp: Dispatcher) -> None:
    """
    Единая точка регистрации всех роутеров.
    Порядок важен: сначала /start и меню, потом остальное.
    """
    dp.include_router(start_handlers.router)
    dp.include_router(ui_handlers.router)
    dp.include_router(missions_handlers.router)
    dp.include_router(admin_users_handlers.router)
