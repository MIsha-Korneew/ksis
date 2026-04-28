r"""
ЛР3 — чат (клиент). TCP + опционально поиск сервера по UDP broadcast.

Обычный запуск:
  cd /d C:\Users\User\ksis_clone\3 laba
  py chat_client.py 127.0.0.1 5000 --nick Имя

Поиск сервера в LAN (UDP broadcast):
  cd /d C:\Users\User\ksis_clone\3 laba
  py chat_client.py --discover --nick Имя

Wireshark: udp.port == 5001 — увидишь KSIS_DISCOVER и ответы KSIS_TCP / рассылку KSIS_ANN.
"""
import argparse
import socket
import sys
import threading
import time


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


def discover_server(udp_port: int, wait_sec: float = 3.0) -> tuple[str, int]:
    """
    Шлёт KSIS_DISCOVER в broadcast, ждёт KSIS_TCP|host|port или KSIS_ANN|host|port.
    """
    # --- сокет UDP: только режим --discover ---
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
    except OSError:
        pass
    sock.bind(("0.0.0.0", 0))
    sock.sendto(b"KSIS_DISCOVER\n", ("255.255.255.255", udp_port))

    sock.settimeout(0.25)
    deadline = time.time() + wait_sec
    while time.time() < deadline:
        try:
            data, addr = sock.recvfrom(2048)
        except socket.timeout:
            continue
        text = data.decode("utf-8", errors="replace").strip()
        for prefix in ("KSIS_TCP|", "KSIS_ANN|"):
            if text.startswith(prefix):
                parts = text.split("|")
                if len(parts) >= 3:
                    host = parts[1].strip()
                    port_str = parts[2].strip().split()[0]
                    port = int(port_str)
                    print(f"[discover] сервер: {host}:{port} (от {addr[0]})")
                    sock.close()
                    return host, port
    sock.close()
    raise SystemExit("Сервер не найден по UDP. Запусти chat_server и проверь порт --udp-port.")


def main() -> None:
    parser = argparse.ArgumentParser(description="TCP chat client (+ UDP discover)")
    parser.add_argument("host", nargs="?", default=None)
    parser.add_argument("port", nargs="?", type=int, default=None)
    parser.add_argument("--nick", required=True)
    parser.add_argument("--bind", default=None, help="локальный IP для TCP (например 127.0.0.2)")
    parser.add_argument("--discover", action="store_true", help="найти сервер через UDP broadcast")
    parser.add_argument("--udp-port", type=int, default=5001, help="UDP порт (как у сервера)")
    parser.add_argument("--discover-wait", type=float, default=3.0, help="сек ожидания ответов UDP")
    args = parser.parse_args()

    if args.discover:
        host, port = discover_server(args.udp_port, args.discover_wait)
    else:
        if args.host is None or args.port is None:
            parser.error("укажи host port или используй --discover")
        host, port = args.host, args.port

    # --- сокет TCP: переписка с сервером ---
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    if args.bind:
        sock.bind((args.bind, 0))

    sock.connect((host, port))
    send_frame(sock, f"JOIN {args.nick}")

    t = threading.Thread(target=reader, args=(sock,), daemon=True)
    t.start()
    print("Сообщения — строка и Enter; выход: /quit или Ctrl+C")

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
