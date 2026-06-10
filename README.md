# Lead Processor MVP

Автоматична обробка заявок з лендингу: нормалізація → AI-аналіз → збереження → сповіщення.

## 🔗 Живе демо

**[web-production-99eda.up.railway.app](https://web-production-99eda.up.railway.app)**

Відкрий посилання → натисни "Відправити заявку" → отримай результат одразу на сторінці.

---

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
  Google Sheets — новий рядок в аркуші Leads:
  [Дата, Ім'я, Телефон, Email, Компанія, AI-Summary, Клас]
        │
        ▼
  Telegram — broadcast усім підписникам бота
```

Підписники реєструються через `/start` у Telegram-боті і зберігаються в аркуші `Subscribers` тієї ж Google Таблиці — не зникають між деплоями.

---

## Стек

| Компонент | Технологія |
|---|---|
| Веб-сервер | FastAPI + Uvicorn |
| AI-аналіз | Anthropic Claude API |
| Збереження лідів | Google Sheets — аркуш `Leads` |
| Підписники | Google Sheets — аркуш `Subscribers` |
| Сповіщення | Telegram Bot API |
| Валідація | Pydantic v2 + EmailStr |
| Деплой | Railway |

---

## Структура проекту

```
├── main.py            # FastAPI сервер — вся логіка обробки
├── test_send.py       # Симулятор заявки з лендингу (Python)
├── requirements.txt   # Залежності
├── Procfile           # Команда запуску для Railway
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
| `GET` | `/` | Demo-форма для тестування |
| `GET` | `/status` | Статус сервера |
| `POST` | `/api/v1/leads` | Прийом заявки з лендингу |
| `POST` | `/telegram/webhook` | Вебхук Telegram |
| `GET` | `/subscribers` | Список підписників |

Swagger документація: `/docs`

---

## Як протестувати

### Варіант А — через demo-форму (найпростіше)

1. Відкрити **[web-production-99eda.up.railway.app](https://web-production-99eda.up.railway.app)**
2. Натиснути "Відправити заявку"
3. Побачити результат на сторінці + отримати сповіщення в Telegram

### Варіант Б — через Python скрипт

```bash
git clone https://github.com/x-whynot/lead-processor-mvp.git
cd lead-processor-mvp
pip install requests
python test_send.py
```

### Варіант В — через curl

```bash
curl -X POST https://web-production-99eda.up.railway.app/api/v1/leads \
  -H "Content-Type: application/json" \
  -d '{
    "name": "   микита   ",
    "phone": " +49 (123) 456-789  ",
    "email": "MYKYTA.Y@EXAMPLE.COM",
    "company": "Kims AI Solutions",
    "message": "Доброго дня! Ми хочемо впровадити ІІ-модуль у наші проекти для автоматизації модерації замовлень. Наш бюджет близько $5000, хочемо запуститися за місяць. Потрібна консультація."
  }'
```

---

## Отримувати Telegram-сповіщення

1. Відкрити бота: **[@mvp_ai_test_bot](https://t.me/mvp_ai_test_bot)**
2. Написати `/start` — підписка на сповіщення
3. Готово — щойно надійде нова заявка, бот надішле сповіщення

**Доступні команди:**
- `/start` — підписатись на сповіщення про нові ліди
- `/stats` — статистика лідів по класах A / B / C
- `/export` — отримати CSV файл з усіма лідами

---

## Локальний запуск

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
4. Поділитися таблицею з email сервісного акаунту → роль **Редактор**

### 4. Запустити сервер

```bash
uvicorn main:app --reload
```

### 5. Налаштувати Telegram вебхук

```bash
# Публічний URL через cloudflared (без реєстрації):
./cloudflared tunnel --url http://localhost:8000

# Зареєструвати вебхук (відкрити в браузері):
# https://api.telegram.org/bot<TOKEN>/setWebhook?url=https://ВАШ_URL/telegram/webhook
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
🕐 10.06.2026 о 12:31
```