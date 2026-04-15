# ЛР3: простой чат клиент-сервер (TCP)

## Где лежит код

Пример пути на твоём ПК (после `dir /s /b ...`):

`C:\Users\User\ksis_clone\3 laba\`

Файлы: `chat_server.py`, `chat_client.py`.

**PyCharm:** File → Open → выбери папку `ksis_clone` (или только `3 laba`).  
Код смотри в Project слева; запуск — зелёная стрелка или Terminal внизу.

---

# Запуск сервера:
#   py chat_server.py 0.0.0.0 5000
#
# Запуск клиента (можно несколько окон):
#   py chat_client.py 127.0.0.1 5000 --nick Misha
#   py chat_client.py 127.0.0.1 5000 --nick Anna --bind 127.0.0.2
#
# Команды в чате:
#   /quit  - выйти
#
# Протокол (очень простой):
#   Каждое сообщение = 4 байта длина (big-endian) + UTF-8 строка.
#   Строка начинается с типа:
#     JOIN <nick>
#     MSG  <text>
#     QUIT
# Сервер рассылает всем:
#     SYS  <text>
#     MSG  <nick>: <text>
