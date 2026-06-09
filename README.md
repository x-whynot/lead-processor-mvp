# Lead Processor MVP

Автоматична обробка заявок з лендингу: нормалізація → AI-аналіз → збереження → сповіщення.

## Логіка рішення

```
POST /api/v1/leads  ←  заявка з лендингу (або test_send.py)
        │
        ▼
  Нормалізація даних
  (Ім'я з великої, email у нижній регістр, телефон без зайвих символів)
        │
        ▼
  Claude AI (claude-sonnet-4-5)
  → summary: стислий зміст заявки
  → lead_class: A (гарячий) / B (середній) / C (холодний)
        │
        ▼
  Google Sheets — новий рядок:
  [Дата, Ім'я, Телефон, Email, Компанія, AI-Summary, Клас]
        │
        ▼
  Telegram — broadcast усім підписникам бота
```

Підписники реєструються через `/start` у Telegram-боті і зберігаються локально у `subscribers.json`.

---

## Стек

| Компонент | Технологія |
|---|---|
| Веб-сервер | FastAPI + Uvicorn |
| AI-аналіз | Anthropic Claude API |
| Збереження лідів | Google Sheets (gspread) |
| Сповіщення | Telegram Bot API |
| Валідація | Pydantic v2 |
| Конфігурація | python-dotenv |

---

## Структура проекту

```
├── main.py            # FastAPI сервер — вся логіка обробки
├── test_send.py       # Симулятор заявки з лендингу
├── requirements.txt   # Залежності
├── .env.example       # Приклад конфігурації
├── .gitignore
└── README.md
```

---

## Тестовий payload

```json
{
  "name": "   микита   ",
  "phone": " +49 (123) 456-789  ",
  "email": "MYKYTA.Y@EXAMPLE.COM",
  "company": "Kims AI Solutions",
  "message": "Доброго дня! Ми хочемо впровадити ІІ-модуль у наші проекти для автоматизації модерації замовлень. Наш бюджет близько $5000, хочемо запуститися за місяць. Потрібна консультація."
}
```

Після обробки:
```json
{
  "name": "Микита",
  "phone": "+49123456789",
  "email": "mykyta.y@example.com",
  "lead_class": "A",
  "summary": "Клієнт хоче впровадити AI-модуль для автоматизації модерації замовлень. Бюджет $5000, термін — місяць."
}
```

---

## API ендпоінти

| Метод | URL | Опис |
|---|---|---|
| `GET` | `/` | Статус сервера |
| `POST` | `/api/v1/leads` | Прийом заявки з лендингу |
| `POST` | `/telegram/webhook` | Вебхук Telegram (реєстрація підписників) |
| `GET` | `/subscribers` | Список підписників |

Інтерактивна документація: `http://localhost:8000/docs`

---

## Запуск

### 1. Клонувати та встановити залежності

```bash
git clone https://github.com/x-whynot/lead-processor-mvp.git
cd lead-processor-mvp
pip install -r requirements.txt
```

### 2. Налаштувати змінні середовища

```bash
cp .env.example .env
```

Заповнити `.env`:

```env
ANTHROPIC_API_KEY=sk-ant-...
TELEGRAM_BOT_TOKEN=1234567890:AAH...
GOOGLE_SHEETS_SPREADSHEET_ID=ваш_id_таблиці
```

### 3. Налаштувати Google Sheets

1. [Google Cloud Console](https://console.cloud.google.com) → створити проект
2. Увімкнути **Google Sheets API** і **Google Drive API**
3. `IAM → Сервісні акаунти` → створити → завантажити JSON → перейменувати у `credentials.json` → покласти в корінь проекту
4. Відкрити Google Таблицю → Поділитися → вставити email сервісного акаунту з `credentials.json` → роль **Редактор**
5. Перший рядок таблиці — заголовки: `Дата | Ім'я | Телефон | Email | Компанія | AI-Summary | Клас`

### 4. Запустити сервер

```bash
uvicorn main:app --reload
```

### 5. Налаштувати Telegram вебхук

Потрібен публічний URL. Найпростіше через [cloudflared](https://github.com/cloudflare/cloudflared/releases) (без реєстрації):

```bash
./cloudflared tunnel --url http://localhost:8000
```

Зареєструвати вебхук — відкрити в браузері:

```
https://api.telegram.org/bot<TOKEN>/setWebhook?url=https://ВАШ_URL/telegram/webhook
```

Відповідь `{"ok":true}` означає успіх.

### 6. Підписати менеджерів

Кожен менеджер пише `/start` боту → потрапляє у `subscribers.json` → починає отримувати сповіщення.

### 7. Протестувати

```bash
python test_send.py
```

---

## Приклад сповіщення в Telegram

```
🔥 НОВИЙ ЛІД — КЛАС A 🔥
──────────────────────────────
👤 Ім'я: Микита
📞 Телефон: +49123456789
📧 Email: mykyta.y@example.com
🏢 Компанія: Kims AI Solutions
──────────────────────────────
🤖 AI-аналіз:
Клієнт хоче впровадити AI-модуль для автоматизації
модерації замовлень. Бюджет $5000, термін — місяць.
──────────────────────────────
🕐 09.06.2026 о 22:31
```