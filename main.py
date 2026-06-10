"""
main.py — MVP-сервер обробки лідів з лендингу.
Стек: FastAPI + Claude AI + Google Sheets + Telegram.
"""

import re
import json
import base64
import logging
from datetime import datetime, timezone, timedelta

KYIV_TZ = timezone(timedelta(hours=3))

import anthropic
import gspread
import httpx
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Request
from google.oauth2 import service_account
from google.oauth2.service_account import Credentials
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

НАЗВА_АРКУШУ_ПІДПИСНИКІВ = "Subscribers"
НАЗВА_АРКУШУ_ЛІДІВ = "Leads"


class Налаштування(BaseSettings):
    """Конфігурація зі змінних середовища (.env)."""

    anthropic_api_key: str
    telegram_bot_token: str
    google_sheets_spreadsheet_id: str
    google_credentials_base64: str = ""

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

    @field_validator("name", "phone", "company", "message", mode="before")
    @classmethod
    def прибрати_пробіли(cls, значення: str) -> str:
        return значення.strip() if isinstance(значення, str) else значення


# ──────────────────────────────────────────────
# GOOGLE SHEETS — авторизація та аркуші
# ──────────────────────────────────────────────

SCOPES = [
    "https://spreadsheets.google.com/feeds",
    "https://www.googleapis.com/auth/drive",
]


def отримати_google_credentials() -> Credentials:
    """Повертає Google Credentials з env або файлу."""
    if налаштування.google_credentials_base64:
        json_bytes = base64.b64decode(налаштування.google_credentials_base64)
        info = json.loads(json_bytes)
        return service_account.Credentials.from_service_account_info(info, scopes=SCOPES)
    return Credentials.from_service_account_file("credentials.json", scopes=SCOPES)


def отримати_таблицю() -> gspread.Spreadsheet:
    """Відкриває Google Sheets таблицю."""
    клієнт = gspread.authorize(отримати_google_credentials())
    return клієнт.open_by_key(налаштування.google_sheets_spreadsheet_id)


def отримати_або_створити_аркуш(таблиця: gspread.Spreadsheet, назва: str, заголовки: list) -> gspread.Worksheet:
    """Повертає аркуш за назвою, створює якщо не існує."""
    try:
        return таблиця.worksheet(назва)
    except gspread.WorksheetNotFound:
        аркуш = таблиця.add_worksheet(title=назва, rows=1000, cols=len(заголовки))
        аркуш.append_row(заголовки)
        logger.info(f"   ✅ Створено новий аркуш: {назва}")
        return аркуш


# ──────────────────────────────────────────────
# УПРАВЛІННЯ ПІДПИСНИКАМИ (Google Sheets)
# ──────────────────────────────────────────────


def завантажити_підписників() -> set:
    """Завантажує список chat_id підписників з аркушу Subscribers."""
    try:
        таблиця = отримати_таблицю()
        аркуш = отримати_або_створити_аркуш(
            таблиця, НАЗВА_АРКУШУ_ПІДПИСНИКІВ, ["chat_id", "ім'я", "дата_підписки"]
        )
        записи = аркуш.get_all_records()
        return {int(р["chat_id"]) for р in записи if р.get("chat_id")}
    except Exception as помилка:
        logger.warning(f"⚠️ Не вдалося завантажити підписників: {помилка}")
        return set()


def додати_підписника_до_sheets(chat_id: int, ім_я: str) -> bool:
    """
    Додає підписника до аркушу Subscribers.
    Повертає True якщо він новий.
    """
    try:
        таблиця = отримати_таблицю()
        аркуш = отримати_або_створити_аркуш(
            таблиця, НАЗВА_АРКУШУ_ПІДПИСНИКІВ, ["chat_id", "ім'я", "дата_підписки"]
        )
        існуючі = {int(р["chat_id"]) for р in аркуш.get_all_records() if р.get("chat_id")}

        if chat_id in існуючі:
            return False

        аркуш.append_row([
            chat_id,
            ім_я,
            datetime.now(KYIV_TZ).strftime("%Y-%m-%d %H:%M:%S"),
        ])
        logger.info(f"   ✅ Підписника {ім_я} ({chat_id}) додано до Sheets.")
        return True
    except Exception as помилка:
        logger.warning(f"⚠️ Не вдалося зберегти підписника: {помилка}")
        return False


# ──────────────────────────────────────────────
# ДОПОМІЖНІ ФУНКЦІЇ
# ──────────────────────────────────────────────


def нормалізувати_заявку(заявка: Заявка) -> dict:
    """Нормалізує поля заявки."""
    очищений_телефон = re.sub(r"[^\d+]", "", заявка.phone)
    return {
        "name": заявка.name.title(),
        "phone": очищений_телефон,
        "email": str(заявка.email).lower(),
        "company": заявка.company.strip(),
        "message": заявка.message,
    }


async def проаналізувати_через_claude(повідомлення: str) -> dict:
    """Аналізує повідомлення через Claude API."""
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
        messages=[{"role": "user", "content": f"Проаналізуй це повідомлення від ліда:\n\n{повідомлення}"}],
    )

    сирий_текст = re.sub(r"```json|```", "", відповідь.content[0].text.strip()).strip()
    logger.info(f"   Відповідь Claude: {сирий_текст}")
    return json.loads(сирий_текст)


def записати_в_google_sheets(дані: dict, аналіз: dict) -> None:
    """Додає новий рядок із даними ліда до аркушу Leads."""
    logger.info("📊 Записуємо дані в Google Sheets...")
    таблиця = отримати_таблицю()
    аркуш = отримати_або_створити_аркуш(
        таблиця, НАЗВА_АРКУШУ_ЛІДІВ,
        ["Дата", "Ім'я", "Телефон", "Email", "Компанія", "AI-Summary", "Клас"]
    )
    аркуш.append_row([
        datetime.now(KYIV_TZ).strftime("%Y-%m-%d %H:%M:%S"),
        дані["name"], дані["phone"], дані["email"],
        дані["company"], аналіз.get("summary", "—"), аналіз.get("lead_class", "?"),
    ])
    logger.info("   ✅ Лід записано до таблиці.")


async def надіслати_повідомлення(клієнт: httpx.AsyncClient, chat_id: int, текст: str) -> bool:
    """Надсилає повідомлення одному підписнику."""
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
    """Розсилає сповіщення всім підписникам з Google Sheets."""
    підписники = завантажити_підписників()

    if not підписники:
        logger.warning("📭 Список підписників порожній.")
        return

    logger.info(f"📬 Розсилаємо {len(підписники)} підписникам...")

    клас = аналіз.get("lead_class", "?")
    резюме = аналіз.get("summary", "—")
    іконка = {"A": "🔥", "B": "🌤", "C": "🧊"}.get(клас, "❓")

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
        f"🕐 {datetime.now(KYIV_TZ).strftime('%d.%m.%Y о %H:%M')}"
    )

    успішно = 0
    async with httpx.AsyncClient() as клієнт:
        for chat_id in підписники:
            if await надіслати_повідомлення(клієнт, chat_id, повідомлення):
                успішно += 1

    logger.info(f"   ✅ Надіслано {успішно}/{len(підписники)}.")


# ──────────────────────────────────────────────
# FASTAPI ДОДАТОК
# ──────────────────────────────────────────────

app = FastAPI(
    title="MVP Обробник Лідів",
    description="Приймає заявки з лендингу, аналізує через Claude AI та сповіщає менеджерів.",
    version="1.0.0",
)


@app.get("/status", tags=["Статус"])
async def перевірка_статусу():
    підписники = завантажити_підписників()
    return {
        "статус": "✅ Сервер працює",
        "час": datetime.now(KYIV_TZ).isoformat(),
        "підписників": len(підписники),
    }


@app.post("/telegram/webhook", tags=["Telegram"])
async def telegram_webhook(запит: Request):
    """Вебхук Telegram — /start реєструє підписника в Google Sheets."""
    тіло = await запит.json()
    повідомлення = тіло.get("message", {})
    текст = повідомлення.get("text", "")
    chat = повідомлення.get("chat", {})
    chat_id = chat.get("id")
    ім_я = chat.get("first_name", "Менеджер")

    if not chat_id:
        return {"ok": True}

    if текст.strip() == "/start":
        є_новий = додати_підписника_до_sheets(chat_id, ім_я)

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
    """Показує підписників з Google Sheets."""
    підписники = завантажити_підписників()
    return {"кількість": len(підписники), "chat_ids": list(підписники)}


@app.post("/api/v1/leads", tags=["Ліди"])
async def обробити_заявку(заявка: Заявка):
    """Головний ендпоінт: нормалізація → Claude AI → Google Sheets → Telegram."""
    logger.info(f"📥 Отримано нову заявку від: {заявка.name} ({заявка.email})")

    нормалізовані = нормалізувати_заявку(заявка)

    try:
        аналіз = await проаналізувати_через_claude(нормалізовані["message"])
    except Exception as помилка:
        logger.error(f"❌ Помилка Claude API: {помилка}")
        raise HTTPException(status_code=502, detail=f"Помилка AI-аналізу: {помилка}")

    try:
        записати_в_google_sheets(нормалізовані, аналіз)
    except Exception as помилка:
        logger.warning(f"⚠️ Google Sheets помилка: {помилка}")

    try:
        await надіслати_всім_підписникам(нормалізовані, аналіз)
    except Exception as помилка:
        logger.warning(f"⚠️ Telegram помилка: {помилка}")

    logger.info("🎉 Заявку успішно оброблено!")
    return {"статус": "успіх", "нормалізовані_дані": нормалізовані, "ai_аналіз": аналіз}


@app.get("/", tags=["Демо"])
async def demo_сторінка():
    """Інтерактивна демо-сторінка для тестування MVP."""
    from fastapi.responses import HTMLResponse
    return HTMLResponse(content="""
<!DOCTYPE html>
<html lang="uk">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>MVP — Обробник Лідів</title>
  <style>
    * { box-sizing: border-box; margin: 0; padding: 0; }
    body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; background: #0f172a; color: #e2e8f0; min-height: 100vh; display: flex; align-items: center; justify-content: center; padding: 24px; }
    .card { background: #1e293b; border-radius: 16px; padding: 40px; width: 100%; max-width: 600px; box-shadow: 0 25px 50px rgba(0,0,0,0.4); }
    h1 { font-size: 24px; font-weight: 700; margin-bottom: 4px; color: #f1f5f9; }
    .subtitle { font-size: 14px; color: #64748b; margin-bottom: 32px; }
    .pipeline { display: flex; align-items: center; gap: 8px; margin-bottom: 32px; flex-wrap: wrap; }
    .step { background: #0f172a; border-radius: 8px; padding: 8px 14px; font-size: 12px; color: #94a3b8; border: 1px solid #334155; }
    .arrow { color: #334155; font-size: 16px; }
    label { display: block; font-size: 13px; font-weight: 500; color: #94a3b8; margin-bottom: 6px; margin-top: 16px; }
    input, textarea { width: 100%; background: #0f172a; border: 1px solid #334155; border-radius: 8px; padding: 10px 14px; color: #f1f5f9; font-size: 14px; outline: none; transition: border-color 0.2s; font-family: inherit; }
    input:focus, textarea:focus { border-color: #6366f1; }
    textarea { resize: vertical; min-height: 100px; }
    button { width: 100%; margin-top: 24px; padding: 14px; background: #6366f1; border: none; border-radius: 10px; color: white; font-size: 16px; font-weight: 600; cursor: pointer; transition: background 0.2s; }
    button:hover { background: #4f46e5; }
    button:disabled { background: #334155; color: #64748b; cursor: not-allowed; }
    .result { margin-top: 24px; border-radius: 10px; padding: 20px; display: none; }
    .result.success { background: #0d2818; border: 1px solid #16a34a; }
    .result.error { background: #2d0f0f; border: 1px solid #dc2626; }
    .result-title { font-size: 15px; font-weight: 600; margin-bottom: 12px; }
    .result.success .result-title { color: #4ade80; }
    .result.error .result-title { color: #f87171; }
    .badge { display: inline-block; padding: 4px 12px; border-radius: 20px; font-size: 13px; font-weight: 700; margin-bottom: 12px; }
    .badge-A { background: #431407; color: #fb923c; }
    .badge-B { background: #0c1a2e; color: #60a5fa; }
    .badge-C { background: #1a1a2e; color: #a78bfa; }
    .result-row { display: flex; gap: 8px; margin-bottom: 6px; font-size: 13px; }
    .result-label { color: #64748b; min-width: 90px; }
    .result-value { color: #e2e8f0; }
    .summary-box { margin-top: 12px; padding: 12px; background: #0f172a; border-radius: 8px; font-size: 13px; color: #94a3b8; line-height: 1.6; }
    .loader { display: inline-block; width: 16px; height: 16px; border: 2px solid #ffffff40; border-top-color: white; border-radius: 50%; animation: spin 0.7s linear infinite; vertical-align: middle; margin-right: 8px; }
    @keyframes spin { to { transform: rotate(360deg); } }
    .hint { font-size: 12px; color: #475569; margin-top: 8px; }
  </style>
</head>
<body>
  <div class="card">
    <h1>🚀 MVP — Обробник Лідів</h1>
    <p class="subtitle">Тестова форма заявки з лендингу</p>
    <div class="pipeline">
      <span class="step">📥 Заявка</span><span class="arrow">→</span>
      <span class="step">🔧 Нормалізація</span><span class="arrow">→</span>
      <span class="step">🤖 Claude AI</span><span class="arrow">→</span>
      <span class="step">📊 Google Sheets</span><span class="arrow">→</span>
      <span class="step">📬 Telegram</span>
    </div>
    <label>Ім'я</label>
    <input id="name" value="   test-name   ">
    <label>Телефон</label>
    <input id="phone" value=" +49 (123) 456-789  ">
    <label>Email</label>
    <input id="email" value="TEST.EMAIL@GMAIL.COM">
    <label>Компанія</label>
    <input id="company" value=" Test AI Solutions">
    <label>Повідомлення</label>
    <textarea id="message">Доброго дня! Ми хочемо впровадити ІІ-модуль у наші проекти для автоматизації модерації замовлень. Наш бюджет близько $5000, хочемо запуститися за місяць. Потрібна консультація.</textarea>
    <p class="hint">💡 Дані навмисно "брудні" — з зайвими пробілами і великими літерами. Система нормалізує їх автоматично.</p>
    <button id="btn" onclick="sendLead()">Відправити заявку</button>
    <div class="result" id="result"></div>
  </div>
  <script>
    async function sendLead() {
      const btn = document.getElementById('btn');
      const result = document.getElementById('result');
      btn.disabled = true;
      btn.innerHTML = '<span class="loader"></span>Обробляємо...';
      result.style.display = 'none';
      const payload = {
        name: document.getElementById('name').value,
        phone: document.getElementById('phone').value,
        email: document.getElementById('email').value,
        company: document.getElementById('company').value,
        message: document.getElementById('message').value,
      };
      try {
        const resp = await fetch('/api/v1/leads', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(payload),
        });
        const data = await resp.json();
        if (resp.ok) {
          const d = data['нормалізовані_дані'];
          const ai = data['ai_аналіз'];
          const cls = ai.lead_class;
          const icons = { A: '🔥', B: '🌤', C: '🧊' };
          const labels = { A: 'Гарячий лід', B: 'Середній лід', C: 'Холодний лід' };
          result.className = 'result success';
          result.innerHTML = `
            <div class="result-title">✅ Заявку успішно оброблено!</div>
            <span class="badge badge-${cls}">${icons[cls] || '❓'} Клас ${cls} — ${labels[cls] || ''}</span>
            <div class="result-row"><span class="result-label">👤 Ім'я:</span><span class="result-value">${d.name}</span></div>
            <div class="result-row"><span class="result-label">📞 Телефон:</span><span class="result-value">${d.phone}</span></div>
            <div class="result-row"><span class="result-label">📧 Email:</span><span class="result-value">${d.email}</span></div>
            <div class="result-row"><span class="result-label">🏢 Компанія:</span><span class="result-value">${d.company || '—'}</span></div>
            <div class="summary-box">🤖 <b>AI-аналіз:</b><br>${ai.summary}</div>
            <div class="result-row" style="margin-top:12px;font-size:12px;color:#475569">
              📊 Записано в Google Sheets &nbsp;·&nbsp; 📬 Надіслано в Telegram
            </div>`;
        } else {
          result.className = 'result error';
          result.innerHTML = `<div class="result-title">❌ Помилка</div><div style="font-size:13px;color:#fca5a5">${JSON.stringify(data.detail || data)}</div>`;
        }
      } catch(e) {
        result.className = 'result error';
        result.innerHTML = `<div class="result-title">❌ Помилка з'єднання</div><div style="font-size:13px;color:#fca5a5">${e.message}</div>`;
      }
      result.style.display = 'block';
      btn.disabled = false;
      btn.innerHTML = 'Відправити заявку';
    }
  </script>
</body>
</html>""")