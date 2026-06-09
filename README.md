# MVP — Обробник лідів з лендингу

Автоматична обробка заявок: нормалізація → AI-аналіз (Claude) → Google Sheets → Telegram.

## Стек

* **FastAPI** — веб-сервер
* **Claude AI** — класифікація та summary ліда
* **Google Sheets** — збереження лідів
* **Telegram Bot** — сповіщення менеджерів

\---

## Швидкий старт

### 1\. Клонувати репозиторій

```bash
git clone https://github.com/YOUR\_USERNAME/YOUR\_REPO.git
cd YOUR\_REPO
```

### 2\. Встановити залежності

```bash
pip install -r requirements.txt
pip install pydantic-settings
```

### 3\. Налаштувати змінні середовища

Скопіювати приклад і заповнити реальними даними:

```bash
cp .env.example .env
```

Відкрити `.env` і заповнити:

```
ANTHROPIC\_API\_KEY=sk-ant-...
TELEGRAM\_BOT\_TOKEN=1234567890:AAH...
GOOGLE\_SHEETS\_SPREADSHEET\_ID=ваш\_id\_таблиці
```

### 4\. Додати credentials.json

* Зайти в [Google Cloud Console](https://console.cloud.google.com)
* Створити сервісний акаунт у проекті з увімкненими Google Sheets API і Google Drive API
* Завантажити JSON-ключ → перейменувати у `credentials.json` → покласти в корінь проекту
* Поділитися Google Таблицею з email сервісного акаунту (роль Редактор)

### 5\. Підготувати Google Таблицю

Перший рядок таблиці — заголовки:
| Дата | Ім'я | Телефон | Email | Компанія | AI-Summary | Клас |

### 6\. Запустити сервер

```bash
uvicorn main:app --reload
```

### 7\. Налаштувати Telegram вебхук

Потрібен публічний URL (наприклад через [cloudflared](https://github.com/cloudflare/cloudflared/releases)):

```bash
# Запустити тунель
./cloudflared tunnel --url http://localhost:8000

# Зареєструвати вебхук (вставити в браузер):
# https://api.telegram.org/bot<TOKEN>/setWebhook?url=https://YOUR\_URL/telegram/webhook
```

### 8\. Підписати менеджерів на сповіщення

Кожен менеджер має написати `/start` боту — після цього він отримуватиме сповіщення про нові ліди.

### 9\. Протестувати

```bash
python test\_send.py
```

\---

## Структура проекту

```
├── main.py              # FastAPI сервер
├── test\_send.py         # Симулятор заявки з лендингу
├── requirements.txt     # Залежності
├── .env                 # Приклад конфігурації
├── .gitignore
└── README.md
```

## API ендпоінти

|Метод|URL|Опис|
|-|-|-|
|`GET`|`/`|Статус сервера|
|`POST`|`/api/v1/leads`|Прийом заявки з лендингу|
|`POST`|`/telegram/webhook`|Вебхук для Telegram|
|`GET`|`/subscribers`|Список підписників|



