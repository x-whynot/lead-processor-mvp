"""
test_send.py — Симулятор відправки "брудної" заявки з лендингу.
Відправляє тестовий POST-запит на сервер.
"""

import requests
import json

# URL сервера — можна змінити на localhost:8000 для локального запуску
URL = "https://web-production-99eda.up.railway.app/api/v1/leads"

# "Брудний" payload — як прийшло б з реального лендингу
ТЕСТОВА_ЗАЯВКА = {
    "name": "   test-name   ",
    "phone": " +49 (123) 456-789  ",
    "email": "TEST.EMAIL@GMAIL.COM",
    "company": "Test Company",
    "message": (
        "Доброго дня! Ми хочемо впровадити ІІ-модуль у наші проекти для автоматизації "
        "модерації замовлень. Наш бюджет близько $5000, хочемо запуститися за місяць. "
        "Потрібна консультація."
    ),
}


def надіслати_заявку() -> None:
    print("=" * 50)
    print("📤 Відправляємо тестову заявку на сервер...")
    print(f"   URL: {URL}")
    print(f"   Дані: {json.dumps(ТЕСТОВА_ЗАЯВКА, ensure_ascii=False, indent=2)}")
    print("=" * 50)

    try:
        відповідь = requests.post(URL, json=ТЕСТОВА_ЗАЯВКА, timeout=60)
        відповідь.raise_for_status()

        print("\n✅ Заявку успішно оброблено!")
        print(f"   HTTP-статус: {відповідь.status_code}")
        print(f"   Відповідь сервера:\n{json.dumps(відповідь.json(), ensure_ascii=False, indent=2)}")

    except requests.exceptions.ConnectionError:
        print("\n❌ Помилка підключення! Перевірте URL сервера.")

    except requests.exceptions.HTTPError as помилка:
        print(f"\n❌ HTTP-помилка: {помилка}")
        print(f"   Відповідь: {помилка.response.text}")

    except Exception as помилка:
        print(f"\n❌ Несподівана помилка: {помилка}")


if __name__ == "__main__":
    надіслати_заявку()