"""
ЛР3 — чат (сервер). TCP + UDP broadcast (объявление и поиск сервера).

Папка: C:\\Users\\User\\ksis_clone\\3 laba\\

Запуск:
  py chat_server.py 0.0.0.0 5000
  (UDP для broadcast по умолчанию порт 5001: --udp-port 5001)

Wireshark: фильтр  udp.port == 5001  или  tcp.port == 5000
"""
import argparse
import socket
import threading
from typing import Dict, Tuple


def detect_local_ip() -> str:
    """IP для объявления в LAN (не 127.0.0.1, если возможно)."""
    # --- сокет UDP (служебно: узнать локальный IP, не чат) ---
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("8.8.8.8", 80))
        return s.getsockname()[0]
    except Exception:
        return "127.0.0.1"
    finally:
        s.close()


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


def broadcast_tcp(clients: Dict[socket.socket, Tuple[str, Tuple[str, int]]], text: str) -> None:
    dead = []
    for s in list(clients.keys()):
        try:
            send_frame(s, text)
        except Exception:
            dead.append(s)
    for s in dead:
        try:
            s.close()
        except Exception:
            pass
        clients.pop(s, None)


def handle_client(
    conn: socket.socket,
    addr: Tuple[str, int],
    clients: Dict[socket.socket, Tuple[str, Tuple[str, int]]],
    lock: threading.Lock,
) -> None:
    nick = None
    try:
        first = recv_frame(conn)
        if not first.startswith("JOIN "):
            send_frame(conn, "SYS protocol error: expected JOIN")
            return
        nick = first[5:].strip() or f"user@{addr[0]}"

        with lock:
            clients[conn] = (nick, addr)
            broadcast_tcp(clients, f"SYS {nick} joined from {addr[0]}:{addr[1]}")

        while True:
            msg = recv_frame(conn)
            if msg == "QUIT":
                with lock:
                    broadcast_tcp(clients, f"SYS {nick} left")
                return
            if msg.startswith("MSG "):
                text = msg[4:].rstrip("\n")
                with lock:
                    broadcast_tcp(clients, f"MSG {nick}: {text}")
            else:
                send_frame(conn, "SYS protocol error: expected MSG or QUIT")

    except Exception:
        pass
    finally:
        with lock:
            if conn in clients:
                clients.pop(conn, None)
                if nick:
                    broadcast_tcp(clients, f"SYS {nick} disconnected")
        try:
            conn.close()
        except Exception:
            pass


def udp_discovery_responder(
    udp: socket.socket,
    announce_ip: str,
    tcp_port: int,
    stop: threading.Event,
) -> None:
    """Отвечает на KSIS_DISCOVER unicast-сообщением KSIS_TCP|ip|port."""
    while not stop.is_set():
        try:
            udp.settimeout(0.5)
            try:
                data, addr = udp.recvfrom(2048)
            except socket.timeout:
                continue
            if b"KSIS_DISCOVER" in data or data.strip().startswith(b"KSIS_DISCOVER"):
                reply = f"KSIS_TCP|{announce_ip}|{tcp_port}\n".encode("utf-8")
                try:
                    udp.sendto(reply, addr)
                except Exception:
                    pass
        except Exception:
            if stop.is_set():
                break


def udp_broadcast_announcer(
    udp: socket.socket,
    announce_ip: str,
    tcp_port: int,
    udp_port: int,
    interval: float,
    stop: threading.Event,
) -> None:
    """Периодически шлёт KSIS_ANN|ip|tcp_port на 255.255.255.255 (для Wireshark / клиентов)."""
    dest = ("255.255.255.255", udp_port)
    msg = f"KSIS_ANN|{announce_ip}|{tcp_port}\n".encode("utf-8")
    while not stop.is_set():
        try:
            udp.sendto(msg, dest)
        except Exception:
            pass
        if stop.wait(interval):
            break


def main() -> None:
    parser = argparse.ArgumentParser(description="TCP chat server + UDP broadcast")
    parser.add_argument("host", nargs="?", default="0.0.0.0", help="TCP bind address")
    parser.add_argument("port", nargs="?", type=int, default=5000, help="TCP port")
    parser.add_argument("--udp-port", type=int, default=5001, help="UDP port (discovery + announce)")
    parser.add_argument("--announce-ip", default=None, help="IP в UDP-сообщениях (по умолчанию авто)")
    parser.add_argument("--announce-interval", type=float, default=5.0, help="сек между UDP broadcast")
    args = parser.parse_args()

    announce_ip = args.announce_ip or detect_local_ip()

    # --- сокет UDP: KSIS_DISCOVER / KSIS_ANN (порт args.udp_port) ---
    udp = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    udp.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    try:
        udp.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
    except OSError:
        pass
    udp.bind(("0.0.0.0", args.udp_port))

    stop_udp = threading.Event()
    t_disc = threading.Thread(
        target=udp_discovery_responder,
        args=(udp, announce_ip, args.port, stop_udp),
        daemon=True,
    )
    t_ann = threading.Thread(
        target=udp_broadcast_announcer,
        args=(udp, announce_ip, args.port, args.udp_port, args.announce_interval, stop_udp),
        daemon=True,
    )
    t_disc.start()
    t_ann.start()

    # --- сокет TCP: чат (порт args.port), listen + accept ---
    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server.bind((args.host, args.port))
    server.listen(50)

    print(f"TCP server: {args.host}:{args.port}")
    print(f"UDP announce/discovery: 0.0.0.0:{args.udp_port} -> broadcast KSIS_ANN|{announce_ip}|{args.port}")

    clients: Dict[socket.socket, Tuple[str, Tuple[str, int]]] = {}
    lock = threading.Lock()

    try:
        while True:
            conn, addr = server.accept()  # conn — отдельный TCP-сокет клиента
            t = threading.Thread(target=handle_client, args=(conn, addr, clients, lock), daemon=True)
            t.start()
    except KeyboardInterrupt:
        print("\nServer stopped")
    finally:
        stop_udp.set()
        try:
            server.close()
        except Exception:
            pass
        try:
            udp.close()
        except Exception:
            pass


if __name__ == "__main__":
    main()
