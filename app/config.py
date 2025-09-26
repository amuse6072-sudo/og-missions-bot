# app/config.py
from __future__ import annotations
from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import Field, AliasChoices
from typing import List, Optional, Tuple
import json, re


class Settings(BaseSettings):
    """
    Единая конфигурация проекта (pydantic-settings).
    Все значения можно задать через .env.
    """

    # pydantic v2: читаем .env (UTF-8) и ИГНОРИРУЕМ незнакомые ключи,
    # чтобы проект не падал, если в .env есть дополнительные переменные.
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",  # <-- ключевая строка, чтобы не было extra_forbidden
    )

    # ── Tokens / APIs ───────────────────────────────────────────────────────────
    BOT_TOKEN: str = Field(..., validation_alias="BOT_TOKEN")
    OPENROUTER_API_KEY: Optional[str] = Field(default=None, validation_alias="OPENROUTER_API_KEY")
    OPENROUTER_MODEL: str = Field(default="gpt-4o-mini", validation_alias="OPENROUTER_MODEL")

    # ── Access (whitelist/admin) ───────────────────────────────────────────────
    ALLOWED_USER_IDS_RAW: str = Field(
        default="7522486988,7794434715,698804137,606563037,878967186,1187540035,569881814",
        validation_alias="ALLOWED_USER_IDS",
    )
    ALLOWED_USERNAMES_RAW: str = Field(default="", validation_alias="ALLOWED_USERNAMES")
    ADMIN_USER_ID: Optional[int] = Field(default=569881814, validation_alias="ADMIN_USER_ID")

    # ── Reports / Timezone ─────────────────────────────────────────────────────
    REPORT_CHAT_ID: Optional[int] = Field(default=None, validation_alias="REPORT_CHAT_ID")
    REPORT_TIMES_RAW: str = Field(default="09:00,15:00,21:00", validation_alias="REPORT_TIMES")

    # Поддерживаем И TIMEZONE, и TZ (оба маппятся в одно поле) — через AliasChoices
    TIMEZONE: str = Field(
        default="Europe/Kyiv",
        validation_alias=AliasChoices("TIMEZONE", "TZ"),
    )

    # Рабочие часы для дедлайнов (например, «срочно = до конца рабочего дня»)
    WORKDAY_START_HOUR: int = Field(default=10, validation_alias="WORKDAY_START_HOUR")
    WORKDAY_END_HOUR: int = Field(default=20, validation_alias="WORKDAY_END_HOUR")

    # ── Logging / Storage ──────────────────────────────────────────────────────
    LOG_LEVEL: str = Field(default="INFO", validation_alias="LOG_LEVEL")
    STORAGE_DIR: Optional[str] = Field(default=None, validation_alias="STORAGE_DIR")

    # ── Media forwarding (optional) ────────────────────────────────────────────
    FORWARD_AUDIO_CHANNEL_ID: Optional[int] = Field(default=None, validation_alias="FORWARD_AUDIO_CHANNEL_ID")
    FORWARD_PHOTO_CHANNEL_ID: Optional[int] = Field(default=None, validation_alias="FORWARD_PHOTO_CHANNEL_ID")

    # ── helpers: парсинг списков/юзеров/времени ────────────────────────────────
    @staticmethod
    def _parse_ids(val: str) -> List[int]:
        if not val:
            return []
        # JSON-массив?
        try:
            data = json.loads(val)
            if isinstance(data, list):
                out: List[int] = []
                for x in data:
                    try:
                        out.append(int(x))
                    except Exception:
                        pass
                return out
        except Exception:
            pass
        # CSV/пробелы/скобки
        val = val.strip().strip("[]")
        parts = re.split(r"[,\s]+", val)
        out: List[int] = []
        for p in parts:
            p = p.strip()
            if not p:
                continue
            m = re.search(r"-?\d+", p)
            if m:
                try:
                    out.append(int(m.group(0)))
                except Exception:
                    pass
        return out

    @staticmethod
    def _parse_names(val: str) -> List[str]:
        if not val:
            return []
        # JSON-массив?
        try:
            data = json.loads(val)
            if isinstance(data, list):
                return [x if str(x).startswith("@") else f"@{str(x).strip()}" for x in data if str(x).strip()]
        except Exception:
            pass
        # CSV/пробелы/скобки
        val = val.strip().strip("[]")
        parts = re.split(r"[,\s]+", val)
        names: List[str] = []
        for p in parts:
            p = p.strip()
            if not p:
                continue
            if not p.startswith("@"):
                p = "@" + p
            names.append(p)
        return names

    @property
    def ALLOWED_USER_IDS(self) -> List[int]:
        return self._parse_ids(self.ALLOWED_USER_IDS_RAW)

    @property
    def ALLOWED_USERNAMES(self) -> List[str]:
        return self._parse_names(self.ALLOWED_USERNAMES_RAW)

    @property
    def REPORT_TIMES(self) -> List[str]:
        raw = self.REPORT_TIMES_RAW or ""
        items = [x.strip() for x in raw.split(",") if x.strip()]
        good: List[str] = []
        for x in items:
            try:
                hh, mm = map(int, x.split(":"))
                assert 0 <= hh < 24 and 0 <= mm < 60
                good.append(f"{hh:02d}:{mm:02d}")
            except Exception:
                continue
        return good or ["09:00", "15:00", "21:00"]

    # ── удобные алиасы для кода ────────────────────────────────────────────────
    @property
    def tz(self) -> str:
        """Совместимость со старым кодом, который ожидал settings.tz."""
        return self.TIMEZONE

    @property
    def work_hours(self) -> Tuple[int, int]:
        """(start_hour, end_hour) — удобно для дедлайн-парсера."""
        return (int(self.WORKDAY_START_HOUR), int(self.WORKDAY_END_HOUR))


settings = Settings()
