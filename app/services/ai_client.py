from __future__ import annotations
import os, json, re, asyncio, aiohttp
from typing import Any, Dict, List, Optional
from loguru import logger

# ─────────────────────────── ENV / Defaults ───────────────────────────
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY", "").strip()
OPENROUTER_MODEL   = os.getenv("OPENROUTER_MODEL", "gpt-4o-mini").strip()
# Может быть полным endpoint или базой (добавим нужный путь автоматически)
OPENROUTER_URL_ENV = os.getenv("OPENROUTER_URL", "").strip() or os.getenv("OPENROUTER_BASE_URL", "").strip()
OPENROUTER_SITE_URL = os.getenv("OPENROUTER_SITE_URL", "").strip()
OPENROUTER_APP_NAME = os.getenv("OPENROUTER_APP_NAME", "").strip()
REQ_TIMEOUT = int(os.getenv("AI_TIMEOUT", os.getenv("OPENROUTER_TIMEOUT", "30")))

def _normalize_openrouter_endpoint(url: str) -> str:
    """
    Принимает либо полный endpoint, либо базовый URL.
    Возвращает корректный endpoint для chat/completions.
    """
    url = (url or "").rstrip("/")
    if not url:
        return "https://openrouter.ai/api/v1/chat/completions"
    # Если уже указывает на completions — оставляем как есть
    if url.endswith("/chat/completions"):
        return url
    # Если это прямо /api/v1 — добавим путь completions
    if url.endswith("/api/v1"):
        return url + "/chat/completions"
    # Если это базовый домен — добавим /api/v1/chat/completions
    return url + "/api/v1/chat/completions"

OPENROUTER_URL = _normalize_openrouter_endpoint(OPENROUTER_URL_ENV)

def _normalize_model_id_for_openrouter(model: str) -> str:
    """
    Если модель указана без префикса, добавим 'openai/' (например 'gpt-4o-mini' → 'openai/gpt-4o-mini').
    """
    model = (model or "").strip()
    if not model:
        return "openai/gpt-4o-mini"
    if "/" not in model:
        return f"openai/{model}"
    return model

# ───────────────────────── JSON extraction ────────────────────────────
def _extract_json_any(text: str) -> Optional[Dict[str, Any]]:
    """
    Достаёт JSON из сырой строки: чистый JSON, ```json ... ``` или {...} внутри текста.
    """
    if not text:
        return None
    # 1) fenced
    m = re.search(r"```json\s*(\{.*?\})\s*```", text, flags=re.S)
    if m:
        try:
            return json.loads(m.group(1))
        except Exception:
            pass
    # 2) first {...}
    m = re.search(r"(\{.*\})", text, flags=re.S)
    if m:
        block = m.group(1)
        try:
            return json.loads(block)
        except Exception:
            pass
    # 3) plain json
    try:
        return json.loads(text)
    except Exception:
        return None

# ────────────────────────── Low-level call ────────────────────────────
async def _openrouter_json(
    messages: List[Dict[str, str]],
    response_format: Optional[Dict[str, Any]] = None,
    timeout: int = REQ_TIMEOUT,
) -> Optional[Dict[str, Any]]:
    """
    Вызов OpenRouter. Возвращает JSON (dict) из ответа модели, либо None.
    Никогда не бросает наружу — логируем и гасим.
    """
    if not OPENROUTER_API_KEY:
        logger.warning("[AI] OPENROUTER_API_KEY is empty — skipping remote call")
        return None

    model_id = _normalize_model_id_for_openrouter(OPENROUTER_MODEL)
    headers = {
        "Authorization": f"Bearer {OPENROUTER_API_KEY}",
        "Content-Type": "application/json",
    }
    if OPENROUTER_SITE_URL:
        headers["HTTP-Referer"] = OPENROUTER_SITE_URL
    if OPENROUTER_APP_NAME:
        headers["X-Title"] = OPENROUTER_APP_NAME

    payload: Dict[str, Any] = {
        "model": model_id,
        "messages": messages,
        "temperature": 0.2,
    }
    # Некоторые модели понимают response_format={"type":"json_object"}
    if response_format:
        payload["response_format"] = response_format

    try:
        async with aiohttp.ClientSession() as sess:
            async with sess.post(OPENROUTER_URL, headers=headers, json=payload, timeout=timeout) as resp:
                if resp.status >= 400:
                    txt = await resp.text()
                    logger.error(f"[AI] HTTP {resp.status}: {txt}")
                    return None
                data = await resp.json()
    except Exception as e:
        logger.exception(f"[AI] request failed: {e}")
        return None

    try:
        content = data["choices"][0]["message"]["content"]
    except Exception:
        logger.error("[AI] unexpected response structure")
        return None

    parsed = _extract_json_any(content)
    if parsed is not None:
        logger.info("[AI] OpenRouter JSON ok")
    else:
        logger.warning("[AI] OpenRouter answered but JSON parse failed")
    return parsed

# ───────────────────────── Public wrappers ────────────────────────────
async def chat_json(system: str, user: str, schema_hint: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """
    Универсальный JSON-чат: добавляем подсказку схеме; парсим ответ.
    """
    sys_msg = {"role": "system", "content": system}
    # Если есть schema_hint — аккуратно доклеим в конец промпта пользователя
    if schema_hint:
        user = f"{user}\n\nSchema: {schema_hint}"
    user_msg = {"role": "user", "content": user}

    messages = [sys_msg, user_msg]
    response_format = {"type": "json_object"}  # если модель поддерживает — даст строгий JSON

    # Попытка 1: строгий JSON
    result = await _openrouter_json(messages, response_format=response_format)
    if result is not None:
        return result

    # Попытка 2: без response_format (некоторые модели OpenRouter не поддерживают)
    result = await _openrouter_json(messages, response_format=None)
    return result

# ───────────────────── Mission helper (new, safe) ─────────────────────
async def mission_from_text(user_text: str) -> Optional[Dict[str, Any]]:
    """
    Превращает короткое сообщение пользователя в структурированный JSON миссии.
    Поли: title, description, assignee_hint, deadline_text, priority.
    Возвращает dict или None.
    """
    system = (
        "You are a task router. Convert a user's short message into a mission JSON. "
        "Answer ONLY with a single-line JSON object. No markdown. No comments."
    )
    schema = (
        '{"title":"строка","description":"строка","assignee_hint":null,'
        '"deadline_text":"сегодня вечером","priority":"normal"}'
    )
    user = (
        "Преобразуй сообщение пользователя в задачу.\n"
        "Сделай короткий title, а полное описание в description.\n"
        "Если указаны имена/ники – положи их в assignee_hint (или null).\n"
        "Время/дату не высчитывай, а верни как человеко-понятную фразу в deadline_text "
        "(например: 'сегодня вечером', 'завтра утром', 'в понедельник к 15:00').\n"
        "priority выбери из {low, normal, high}. Верни только JSON без форматирования.\n\n"
        f"Сообщение: {user_text}"
    )
    return await chat_json(system=system, user=user, schema_hint=schema)
