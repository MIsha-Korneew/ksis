# ЛР3: чат клиент-сервер (TCP + UDP broadcast)

## Где лежит код

`C:\Users\User\ksis_clone\3 laba\` — `chat_server.py`, `chat_client.py`.

## Запуск

**Сервер** (TCP + периодический UDP broadcast на `255.255.255.255`):

```text
py chat_server.py 0.0.0.0 5000
```

UDP по умолчанию порт **5001** (`--udp-port 5001`).

**Клиент** (подключение вручную):

```text
py chat_client.py 127.0.0.1 5000 --nick Misha
```

**Клиент** (поиск сервера по UDP — шлёт `KSIS_DISCOVER`, ждёт `KSIS_TCP` / `KSIS_ANN`):

```text
py chat_client.py --discover --nick Misha
```

Выход из чата: `/quit`

## Протоколы

### TCP (чат), порт 5000

Кадр: **4 байта длина (big-endian)** + **UTF-8 строка**.

- Клиент → сервер: `JOIN <nick>`, `MSG <text>`, `QUIT`
- Сервер → клиенты: `SYS ...`, `MSG <nick>: <text>`

### UDP (объявление / поиск), порт 5001

- Клиент → broadcast: `KSIS_DISCOVER\n`
- Сервер → клиент (unicast): `KSIS_TCP|<ip>|<tcp_port>\n`
- Сервер → broadcast: `KSIS_ANN|<ip>|<tcp_port>\n` (каждые 5 с, настраивается)

## Wireshark

- `tcp.port == 5000` — рукопожатие, сообщения чата
- `udp.port == 5001` — broadcast и ответы discovery

Если на loopback нет UDP — захватывай интерфейс **Npcap Loopback** / аналог.

## Примечание

Подпись **RSL / Malformed** на TCP:5000 — ложное определение Wireshark; полезная нагрузка — наш бинарный кадр (длина + текст).
