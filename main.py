"""
main.py — MVP-сервер обробки лідів з лендингу.
Стек: FastAPI + Claude AI + Google Sheets + Telegram.
"""

import re
import json
import base64
import logging
from datetime import datetime
from pathlib import Path

import anthropic
import gspread
import httpx
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Request
from google.oauth2.service_account import Credentials
from google.oauth2 import service_account
from pydantic import BaseModel, EmailStr, field_validator
from pydantic_settings import BaseSettings

# ──────────────────────────────────────────────
# КОНФІГУРАЦІЯ
# ──────────────────────────────────────────────

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)

ФАЙЛ_ПІДПИСНИКІВ = Path("subscribers.json")


class Налаштування(BaseSettings):
    """Конфігурація зі змінних середовища (.env)."""

    anthropic_api_key: str
    telegram_bot_token: str
    google_sheets_spreadsheet_id: str
    google_credentials_base64: str = ""  # base64 JSON для Railway

    class Config:
        env_file = ".env"
        extra = "ignore"


налаштування = Налаштування()

# ──────────────────────────────────────────────
# PYDANTIC-МОДЕЛЬ ВХІДНОЇ ЗАЯВКИ
# ──────────────────────────────────────────────


class Заявка(BaseModel):
    """Схема вхідної заявки з лендингу."""

    name: str
    phone: str
    email: EmailStr
    company: str = ""
    message: str

    @field_validator("name", "phone", "email", "company", "message", mode="before")
    @classmethod
    def прибрати_пробіли(cls, значення: str) -> str:
        return значення.strip() if isinstance(значення, str) else значення


# ──────────────────────────────────────────────
# УПРАВЛІННЯ ПІДПИСНИКАМИ
# ──────────────────────────────────────────────


def завантажити_підписників() -> set:
    """Завантажує список chat_id підписників з файлу."""
    if not ФАЙЛ_ПІДПИСНИКІВ.exists():
        return set()
    try:
        дані = json.loads(ФАЙЛ_ПІДПИСНИКІВ.read_text(encoding="utf-8"))
        return set(дані)
    except Exception:
        return set()


def зберегти_підписників(підписники: set) -> None:
    """Зберігає список chat_id підписників у файл."""
    ФАЙЛ_ПІДПИСНИКІВ.write_text(
        json.dumps(list(підписники), indent=2, ensure_ascii=False),
        encoding="utf-8",
    )


def додати_підписника(chat_id: int) -> bool:
    """Додає нового підписника. Повертає True якщо він новий."""
    підписники = завантажити_підписників()
    якщо_новий = chat_id not in підписники
    підписники.add(chat_id)
    зберегти_підписників(підписники)
    return якщо_новий


# ──────────────────────────────────────────────
# GOOGLE SHEETS — авторизація
# ──────────────────────────────────────────────

SCOPES = [
    "https://spreadsheets.google.com/feeds",
    "https://www.googleapis.com/auth/drive",
]


def отримати_google_credentials() -> Credentials:
    """
    Повертає Google Credentials.
    Пріоритет:
      1. Змінна середовища GOOGLE_CREDENTIALS_BASE64 (Railway/продакшн)
      2. Файл credentials.json (локальна розробка)
    """
    if налаштування.google_credentials_base64:
        logger.info("   Використовуємо credentials з змінної середовища.")
        json_bytes = base64.b64decode(налаштування.google_credentials_base64)
        info = json.loads(json_bytes)
        return service_account.Credentials.from_service_account_info(info, scopes=SCOPES)
    else:
        logger.info("   Використовуємо credentials з файлу credentials.json.")
        return Credentials.from_service_account_file("credentials.json", scopes=SCOPES)


# ──────────────────────────────────────────────
# ДОПОМІЖНІ ФУНКЦІЇ
# ──────────────────────────────────────────────


def нормалізувати_заявку(заявка: Заявка) -> dict:
    """Нормалізує поля заявки: капіталізація, нижній регістр, очищення телефону."""
    очищений_телефон = re.sub(r"[^\d+]", "", заявка.phone)

    return {
        "name": заявка.name.title(),
        "phone": очищений_телефон,
        "email": заявка.email.lower(),
        "company": заявка.company.strip(),
        "message": заявка.message,
    }


async def проаналізувати_через_claude(повідомлення: str) -> dict:
    """
    Надсилає повідомлення до Claude API та отримує структурований аналіз ліда.
    Повертає словник з ключами: summary, lead_class.
    """
    клієнт = anthropic.Anthropic(api_key=налаштування.anthropic_api_key)

    системний_промпт = """Ти — асистент з аналізу бізнес-лідів.
Твоє завдання — проаналізувати повідомлення від потенційного клієнта та повернути ТІЛЬКИ валідний JSON без жодного додаткового тексту.

Структура відповіді:
{
  "summary": "Стислий зміст заявки українською мовою (максимум 2 речення).",
  "lead_class": "A"
}

Правила класифікації:
- A (гарячий лід) — є конкретний бюджет, чіткі терміни, реальна потреба.
- B (середній лід) — є потреба, але немає бюджету або термінів.
- C (холодний/спам) — нечітке повідомлення, реклама, або явний спам.

Відповідай ТІЛЬКИ JSON. Без markdown, без пояснень."""

    logger.info("🤖 Надсилаємо запит до Claude API...")

    відповідь = клієнт.messages.create(
        model="claude-sonnet-4-5",
        max_tokens=512,
        system=системний_промпт,
        messages=[
            {
                "role": "user",
                "content": f"Проаналізуй це повідомлення від ліда:\n\n{повідомлення}",
            }
        ],
    )

    сирий_текст = відповідь.content[0].text.strip()
    logger.info(f"   Відповідь Claude: {сирий_текст}")

    сирий_текст = re.sub(r"```json|```", "", сирий_текст).strip()
    аналіз = json.loads(сирий_текст)
    return аналіз


def записати_в_google_sheets(дані: dict, аналіз: dict) -> None:
    """Додає новий рядок із даними ліда до Google Sheets."""
    logger.info("📊 Записуємо дані в Google Sheets...")

    облікові_дані = отримати_google_credentials()
    клієнт_sheets = gspread.authorize(облікові_дані)
    таблиця = клієнт_sheets.open_by_key(налаштування.google_sheets_spreadsheet_id)
    аркуш = таблиця.sheet1

    нова_строка = [
        datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        дані["name"],
        дані["phone"],
        дані["email"],
        дані["company"],
        аналіз.get("summary", "—"),
        аналіз.get("lead_class", "?"),
    ]

    аркуш.append_row(нова_строка)
    logger.info("   ✅ Рядок успішно додано до таблиці.")


async def надіслати_повідомлення(клієнт: httpx.AsyncClient, chat_id: int, текст: str) -> bool:
    """Надсилає одне повідомлення конкретному chat_id. Повертає True при успіху."""
    url = f"https://api.telegram.org/bot{налаштування.telegram_bot_token}/sendMessage"
    try:
        відповідь = await клієнт.post(
            url,
            json={"chat_id": chat_id, "text": текст, "parse_mode": "HTML"},
            timeout=15,
        )
        відповідь.raise_for_status()
        return True
    except Exception as помилка:
        logger.warning(f"   ⚠️ Не вдалося надіслати chat_id={chat_id}: {помилка}")
        return False


async def надіслати_всім_підписникам(дані: dict, аналіз: dict) -> None:
    """Розсилає сповіщення про новий лід усім підписникам бота."""
    підписники = завантажити_підписників()

    if not підписники:
        logger.warning("📭 Список підписників порожній — нікому надсилати.")
        return

    logger.info(f"📬 Розсилаємо сповіщення {len(підписники)} підписникам...")

    клас = аналіз.get("lead_class", "?")
    резюме = аналіз.get("summary", "—")
    іконки_класу = {"A": "🔥", "B": "🌤", "C": "🧊"}
    іконка = іконки_класу.get(клас, "❓")

    повідомлення = (
        f"{іконка} <b>НОВИЙ ЛІД — КЛАС {клас}</b> {іконка}\n"
        f"{'─' * 30}\n"
        f"👤 <b>Ім'я:</b> {дані['name']}\n"
        f"📞 <b>Телефон:</b> <code>{дані['phone']}</code>\n"
        f"📧 <b>Email:</b> {дані['email']}\n"
        f"🏢 <b>Компанія:</b> {дані['company'] or '—'}\n"
        f"{'─' * 30}\n"
        f"🤖 <b>AI-аналіз:</b>\n{резюме}\n"
        f"{'─' * 30}\n"
        f"🕐 {datetime.now().strftime('%d.%m.%Y о %H:%M')}"
    )

    успішно = 0
    async with httpx.AsyncClient() as клієнт:
        for chat_id in підписники:
            if await надіслати_повідомлення(клієнт, chat_id, повідомлення):
                успішно += 1

    logger.info(f"   ✅ Надіслано {успішно}/{len(підписники)} підписникам.")


# ──────────────────────────────────────────────
# FASTAPI ДОДАТОК
# ──────────────────────────────────────────────

app = FastAPI(
    title="MVP Обробник Лідів",
    description="Приймає заявки з лендингу, аналізує через Claude AI та сповіщає менеджерів.",
    version="1.0.0",
)


@app.get("/", tags=["Статус"])
async def перевірка_статусу():
    """Перевірка працездатності сервера."""
    підписники = завантажити_підписників()
    return {
        "статус": "✅ Сервер працює",
        "час": datetime.now().isoformat(),
        "підписників": len(підписники),
    }


@app.post("/telegram/webhook", tags=["Telegram"])
async def telegram_webhook(запит: Request):
    """Вебхук для Telegram. /start — реєструє підписника."""
    тіло = await запит.json()
    logger.info(f"📩 Telegram webhook: {json.dumps(тіло, ensure_ascii=False)}")

    повідомлення = тіло.get("message", {})
    текст = повідомлення.get("text", "")
    chat = повідомлення.get("chat", {})
    chat_id = chat.get("id")
    ім_я = chat.get("first_name", "Менеджер")

    if not chat_id:
        return {"ok": True}

    if текст.strip() == "/start":
        є_новий = додати_підписника(chat_id)

        відповідь_текст = (
            f"👋 Привіт, <b>{ім_я}</b>!\n\n"
            f"✅ Ви успішно підписались на сповіщення про нові ліди.\n"
            f"Щойно надійде нова заявка — ви отримаєте повідомлення першими. 🚀"
            if є_новий else
            f"👋 {ім_я}, ви вже підписані!\n\n"
            f"📬 Сповіщення про нові ліди будуть надходити автоматично."
        )

        url = f"https://api.telegram.org/bot{налаштування.telegram_bot_token}/sendMessage"
        async with httpx.AsyncClient() as клієнт:
            await клієнт.post(
                url,
                json={"chat_id": chat_id, "text": відповідь_текст, "parse_mode": "HTML"},
                timeout=10,
            )

    return {"ok": True}


@app.get("/subscribers", tags=["Telegram"])
async def список_підписників():
    """Показує поточний список підписників."""
    підписники = завантажити_підписників()
    return {"кількість": len(підписники), "chat_ids": list(підписники)}


@app.post("/api/v1/leads", tags=["Ліди"])
async def обробити_заявку(заявка: Заявка):
    """Головний ендпоінт: нормалізація → Claude AI → Google Sheets → Telegram."""
    logger.info(f"📥 Отримано нову заявку від: {заявка.name} ({заявка.email})")

    нормалізовані = нормалізувати_заявку(заявка)
    logger.info(f"   Нормалізовані дані: {нормалізовані}")

    try:
        аналіз = await проаналізувати_через_claude(нормалізовані["message"])
    except Exception as помилка:
        logger.error(f"❌ Помилка Claude API: {помилка}")
        raise HTTPException(status_code=502, detail=f"Помилка AI-аналізу: {помилка}")

    try:
        записати_в_google_sheets(нормалізовані, аналіз)
    except Exception as помилка:
        logger.warning(f"⚠️ Не вдалося записати в Google Sheets: {помилка}")

    try:
        await надіслати_всім_підписникам(нормалізовані, аналіз)
    except Exception as помилка:
        logger.warning(f"⚠️ Помилка розсилки в Telegram: {помилка}")

    logger.info("🎉 Заявку успішно оброблено!")

    return {
        "статус": "успіх",
        "нормалізовані_дані": нормалізовані,
        "ai_аналіз": аналіз,
    }