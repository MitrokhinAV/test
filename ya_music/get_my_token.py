from yandex_music import Client

def on_code(code):
    print("\n" + "="*50)
    print(f"1. Откройте эту ссылку в браузере: {code.verification_url}")
    print(f"2. Введите этот код подтверждения: {code.user_code}")
    print("="*50 + "\n")

print("Запрос авторизации в Яндексе...")
# Создаем пустой клиент и вызываем правильный метод
client = Client()
token_info = client.device_auth(on_code)

print("\nУСПЕШНО!")
print(f"Ваш токен для вставки в core.py:\n{token_info.access_token}")
