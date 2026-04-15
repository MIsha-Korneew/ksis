"""
ЛР3 — чат (клиент). Папка с кодом та же, что у сервера, например:
  C:\\Users\\User\\ksis_clone\\3 laba\\

Запуск в CMD (отдельное окно, после того как сервер уже запущен):
  cd /d C:\\Users\\User\\ksis_clone\\3 laba
  py chat_client.py 127.0.0.1 5000 --nick ТвоеИмя

Второй клиент (другой IP на этом ПК, если настроены loopback-алиасы):
  py chat_client.py 127.0.0.1 5000 --nick Другой --bind 127.0.0.2

Выход из чата: набери /quit и Enter

В PyCharm: Run Configuration для chat_client.py
  Parameters: 127.0.0.1 5000 --nick Misha
  Working directory: ...\\3 laba
"""
import argparse
import socket
import threading
import sys


def recv_exact(sock: socket.socket, n: int) -> bytes:
    buf = b""
    while len(buf) < n:
        chunk = sock.recv(n - len(buf))
        if not chunk:
            raise ConnectionError("socket closed")
        buf += chunk
    return buf


def recv_frame(sock: socket.socket) -> str:
    header = recv_exact(sock, 4)
    length = int.from_bytes(header, "big")
    if length < 0 or length > 1_000_000:
        raise ValueError("bad frame length")
    payload = recv_exact(sock, length)
    return payload.decode("utf-8", errors="replace")


def send_frame(sock: socket.socket, text: str) -> None:
    payload = text.encode("utf-8")
    sock.sendall(len(payload).to_bytes(4, "big") + payload)


def reader(sock: socket.socket) -> None:
    try:
        while True:
            msg = recv_frame(sock)
            print(msg)
    except Exception:
        pass


def main() -> None:
    parser = argparse.ArgumentParser(description="Simple TCP chat client")
    parser.add_argument("host")
    parser.add_argument("port", type=int)
    parser.add_argument("--nick", required=True)
    parser.add_argument("--bind", default=None, help="local IP to bind (e.g. 127.0.0.2)")
    args = parser.parse_args()

    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    if args.bind:
        sock.bind((args.bind, 0))

    sock.connect((args.host, args.port))
    send_frame(sock, f"JOIN {args.nick}")

    t = threading.Thread(target=reader, args=(sock,), daemon=True)
    t.start()

    try:
        while True:
            line = sys.stdin.readline()
            if not line:
                break
            line = line.rstrip("\n")
            if line == "/quit":
                send_frame(sock, "QUIT")
                break
            if line.strip() == "":
                continue
            send_frame(sock, f"MSG {line}")
    except KeyboardInterrupt:
        try:
            send_frame(sock, "QUIT")
        except Exception:
            pass
    finally:
        try:
            sock.close()
        except Exception:
            pass


if __name__ == "__main__":
    main()
