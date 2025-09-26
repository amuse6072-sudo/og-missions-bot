from __future__ import annotations

# UI-тексты (оставил твои поля + пример команды)
APP_NAME = "OG Missions"
PER_PAGE = 8

MAIN_MENU = {
    "missions": "🧩 Миссии",
    "my": "🗂 Мои задачи",
    "stats": "📊 Статистика",
    "help": "❓ Помощь",
    "admin": "🛠 Админ-панель",
}

MISSION_BTNS = {
    "accept": "✅ Беру",
    "done": "🏁 Готово",
    "fail": "⛔️ Не успел",
    "details": "🔎 Детали",
    "assign": "👤 Назначить",
    "edit": "✏️ Редактировать",
    "delete": "🗑 Удалить",
    "back": "⬅️ Назад",
}

ADMIN_BTNS = {
    "stats": "📈 Отчёты",
    "broadcast": "📣 Анонс",
    "wipe": "🧹 Чистка",
    "back": "⬅️ Назад",
}

# Список команды можно держать как есть
TEAM = [
    {"tg_id": 7522486988, "full_name": "Ярик"},
    {"tg_id": 7794434715, "full_name": "Ростик"},
    {"tg_id": 698804137, "full_name": "Мурад"},
    {"tg_id": 606563037, "full_name": "Витя"},
    {"tg_id": 878967186, "full_name": "Артур"},
    {"tg_id": 1187540035, "full_name": "Женя"},
    {"tg_id": 569881814, "full_name": "Вася", "is_admin": True},  # админ
]
