import argparse
import socket
import threading
from typing import Dict, Tuple


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


def broadcast(clients: Dict[socket.socket, Tuple[str, Tuple[str, int]]], text: str) -> None:
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


def handle_client(conn: socket.socket, addr: Tuple[str, int], clients: Dict[socket.socket, Tuple[str, Tuple[str, int]]], lock: threading.Lock) -> None:
    nick = None
    try:
        first = recv_frame(conn)
        if not first.startswith("JOIN "):
            send_frame(conn, "SYS protocol error: expected JOIN")
            return
        nick = first[5:].strip() or f"user@{addr[0]}"

        with lock:
            clients[conn] = (nick, addr)
            broadcast(clients, f"SYS {nick} joined from {addr[0]}:{addr[1]}")

        while True:
            msg = recv_frame(conn)
            if msg == "QUIT":
                with lock:
                    broadcast(clients, f"SYS {nick} left")
                return
            if msg.startswith("MSG "):
                text = msg[4:].rstrip("\n")
                with lock:
                    broadcast(clients, f"MSG {nick}: {text}")
            else:
                send_frame(conn, "SYS protocol error: expected MSG or QUIT")

    except Exception:
        # отключился/ошибка чтения
        pass
    finally:
        with lock:
            if conn in clients:
                clients.pop(conn, None)
                if nick:
                    broadcast(clients, f"SYS {nick} disconnected")
        try:
            conn.close()
        except Exception:
            pass


def main() -> None:
    parser = argparse.ArgumentParser(description="Simple TCP chat server")
    parser.add_argument("host", nargs="?", default="0.0.0.0")
    parser.add_argument("port", nargs="?", type=int, default=5000)
    args = parser.parse_args()

    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server.bind((args.host, args.port))
    server.listen(50)

    print(f"Server listening on {args.host}:{args.port}")

    clients: Dict[socket.socket, Tuple[str, Tuple[str, int]]] = {}
    lock = threading.Lock()

    try:
        while True:
            conn, addr = server.accept()
            t = threading.Thread(target=handle_client, args=(conn, addr, clients, lock), daemon=True)
            t.start()
    except KeyboardInterrupt:
        print("\nServer stopped")
    finally:
        try:
            server.close()
        except Exception:
            pass


if __name__ == "__main__":
    main()
