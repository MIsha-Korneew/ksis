"""
Лабораторная работа №4 (КСиС): простой HTTP-прокси-сервер.

Прокси-сервер — это промежуточный узел между клиентом (браузером) и сервером
назначения: запросы сначала приходят на прокси, прокси устанавливает отдельное
TCP-соединение с целевым узлом, пересылает HTTP-запрос и возвращает ответ клиенту.
В задании рассматривается только протокол HTTP (без туннелирования HTTPS).

Суть лабораторной работы — реализовать такой прокси на низком уровне (интерфейс
сокетов), обеспечить многопоточную обработку подключений и журналирование
проксируемых запросов: в консоль выводится URL ресурса и код HTTP-ответа.
Браузер при работе через прокси передаёт в запросе абсолютный URL; прокси
преобразует его в запрос с путём и заголовком Host согласно RFC 2616 (раздел
о форме Request-URI при работе через прокси) и пересылает ответ потоком,
чтобы длительные соединения (например, потоковое радио) не обрывались
преждевременно.

Порядок проверки:
  1) Перейти в каталог с файлом, например:
     cd /d D:\\...\\4 laba
  2) Запустить прокси (порт 8080 можно заменить при занятом порту):
     py http_proxy.py --port 8080
     или: python http_proxy.py --port 8080
  3) В настройках системы или браузера указать ручной HTTP-прокси: адрес
     127.0.0.1 и тот же порт (например 8080). Для выполнения лабораторного
     задания достаточно трафика HTTP; проксирование HTTPS данной программой
     не поддерживается.
  4) Открыть в браузере примеры из методички (именно схема http://):
     http://example.com/
     http://live.legendy.by:8000/legendyfm
  5) Остановка прокси: сочетание клавиш Ctrl+C в окне терминала.

Подробные пояснения — в README.md в этой папке.
"""
from __future__ import annotations

import argparse
import re
import socket
import threading
from typing import Dict, List, Optional, Tuple
from urllib.parse import urlparse

DEFAULT_PORT = 8080
RECV = 65536

HOP_BY_HOP = frozenset(
    {
        "connection",
        "keep-alive",
        "proxy-authenticate",
        "proxy-authorization",
        "te",
        "trailer",
        "transfer-encoding",
        "upgrade",
        "proxy-connection",
    }
)


def read_line(sock: socket.socket, max_len: int = 65536) -> bytes:
    buf = b""
    while len(buf) < max_len:
        ch = sock.recv(1)
        if not ch:
            break
        buf += ch
        if buf.endswith(b"\r\n"):
            break
    return buf


def read_exact(sock: socket.socket, n: int) -> bytes:
    out = b""
    while len(out) < n:
        chunk = sock.recv(min(RECV, n - len(out)))
        if not chunk:
            break
        out += chunk
    return out


def read_until_headers(sock: socket.socket, max_total: int = 1024 * 1024) -> bytes:
    data = b""
    while len(data) < max_total:
        chunk = sock.recv(RECV)
        if not chunk:
            break
        data += chunk
        if b"\r\n\r\n" in data:
            break
    return data


def header_list_to_dict(headers: List[Tuple[str, str]]) -> Dict[str, str]:
    d: Dict[str, str] = {}
    for k, v in headers:
        d[k.lower()] = v
    return d


def parse_request(
    raw: bytes,
) -> Tuple[str, str, str, List[Tuple[str, str]]]:
    if b"\r\n\r\n" not in raw:
        raise ValueError("incomplete headers")
    head, _ = raw.split(b"\r\n\r\n", 1)
    lines = head.split(b"\r\n")
    if not lines:
        raise ValueError("empty request")
    first = lines[0].decode("latin-1", errors="replace").strip()
    parts = first.split()
    if len(parts) < 3:
        raise ValueError("bad request line")
    method, target, version = parts[0], parts[1], parts[2]
    headers: List[Tuple[str, str]] = []
    for line in lines[1:]:
        if not line.strip() or b":" not in line:
            continue
        k, v = line.split(b":", 1)
        headers.append((k.decode("latin-1").strip(), v.decode("latin-1").strip()))
    return method, target, version, headers


def read_request_with_body(client: socket.socket, initial: bytes) -> bytes:
    if b"\r\n\r\n" not in initial:
        return initial
    head, rest = initial.split(b"\r\n\r\n", 1)
    hd: Dict[str, str] = {}
    for line in head.split(b"\r\n")[1:]:
        if b":" not in line:
            continue
        k, v = line.split(b":", 1)
        hd[k.decode("latin-1").strip().lower()] = v.decode("latin-1").strip()
    cl = hd.get("content-length")
    if not cl:
        return initial
    try:
        n = int(cl)
    except ValueError:
        return initial
    got = len(rest)
    if got >= n:
        return initial
    rest += read_exact(client, n - got)
    return head + b"\r\n\r\n" + rest


def resolve_target(
    target: str, headers: List[Tuple[str, str]]
) -> Tuple[str, str, int, str]:
    """
    full_url (лог), host, port, path с query (начинается с /)
    """
    if target.lower().startswith("http://"):
        p = urlparse(target)
        if p.scheme != "http":
            raise ValueError("only http")
        host = p.hostname
        if not host:
            raise ValueError("no host")
        port = p.port or 80
        path = p.path or "/"
        if p.query:
            path += "?" + p.query
        full = target.strip()
        return full, host, port, path

    hd = header_list_to_dict(headers)
    hp = hd.get("host", "")
    if not hp:
        raise ValueError("relative uri without Host")
    if hp.count(":") == 1 and not hp.startswith("["):
        host, ps = hp.rsplit(":", 1)
        try:
            port = int(ps)
        except ValueError:
            host, port = hp, 80
    else:
        host, port = hp, 80
    path = target if target.startswith("/") else "/" + target
    full = f"http://{host}:{port}{path}" if port != 80 else f"http://{host}{path}"
    return full, host, port, path


def build_upstream_headers(
    method: str,
    path: str,
    version: str,
    headers: List[Tuple[str, str]],
    host: str,
    port: int,
) -> bytes:
    lines: List[str] = [f"{method} {path} {version}"]
    have_host = False
    for k, v in headers:
        lk = k.lower()
        if lk in HOP_BY_HOP:
            continue
        if lk == "host":
            have_host = True
        lines.append(f"{k}: {v}")
    if not have_host:
        lines.insert(1, f"Host: {host}:{port}" if port != 80 else f"Host: {host}")
    return ("\r\n".join(lines) + "\r\n\r\n").encode("latin-1")


def parse_response_status_and_options(
    header_bytes: bytes,
) -> Tuple[int, bool, Optional[int]]:
    first = header_bytes.split(b"\r\n", 1)[0].decode("latin-1", errors="replace")
    m = re.match(r"HTTP/\d\.\d\s+(\d+)", first, re.I)
    code = int(m.group(1)) if m else 502
    hd: Dict[str, str] = {}
    for line in header_bytes.split(b"\r\n")[1:]:
        if b":" not in line:
            continue
        k, v = line.split(b":", 1)
        hd[k.decode("latin-1").strip().lower()] = v.decode("latin-1").strip()
    te = hd.get("transfer-encoding", "").lower()
    chunked = "chunked" in te
    cl = hd.get("content-length")
    content_len: Optional[int] = None
    if cl and not chunked:
        try:
            content_len = int(cl)
        except ValueError:
            content_len = None
    return code, chunked, content_len


def relay_chunked(src: socket.socket, dst: socket.socket) -> None:
    while True:
        line = read_line(src)
        if not line:
            break
        s = line.strip().split(b";", 1)[0]
        try:
            size = int(s, 16)
        except ValueError:
            break
        if size == 0:
            read_line(src)
            break
        remaining = size
        while remaining > 0:
            chunk = read_exact(src, remaining)
            if not chunk:
                return
            dst.sendall(chunk)
            remaining -= len(chunk)
        read_line(src)


def relay_response_body(
    src: socket.socket,
    dst: socket.socket,
    pre_body: bytes,
    content_length: Optional[int],
    chunked: bool,
) -> None:
    if chunked:
        dst.sendall(pre_body)
        relay_chunked(src, dst)
        return
    if content_length is not None:
        dst.sendall(pre_body)
        need = content_length - len(pre_body)
        while need > 0:
            chunk = src.recv(min(RECV, need))
            if not chunk:
                break
            dst.sendall(chunk)
            need -= len(chunk)
        return
    dst.sendall(pre_body)
    while True:
        chunk = src.recv(RECV)
        if not chunk:
            break
        dst.sendall(chunk)


def handle_client(
    client: socket.socket, addr: tuple, lock: threading.Lock
) -> None:
    try:
        while True:
            buf = read_until_headers(client)
            if not buf or b"\r\n\r\n" not in buf:
                return
            buf = read_request_with_body(client, buf)
            try:
                method, target, version, headers = parse_request(buf)
            except ValueError:
                return
            if method.upper() == "CONNECT":
                try:
                    client.sendall(
                        b"HTTP/1.1 501 Not Implemented (HTTPS)\r\n"
                        b"Content-Length: 0\r\nConnection: close\r\n\r\n"
                    )
                except OSError:
                    pass
                return
            try:
                full_url, host, port, path = resolve_target(target, headers)
            except ValueError:
                return
            _, body = buf.split(b"\r\n\r\n", 1)
            up: Optional[socket.socket] = None
            try:
                up = socket.create_connection((host, port), 20)
            except OSError as e:
                with lock:
                    print(f"{full_url} -> ERR ({e})")
                try:
                    msg = f"HTTP/1.1 502 Bad Gateway\r\nContent-Type: text/plain\r\nConnection: close\r\n\r\n{e!s}"
                    client.sendall(msg.encode("utf-8", errors="replace"))
                except OSError:
                    pass
                return
            try:
                hdr = build_upstream_headers(method, path, version, headers, host, port)
                up.sendall(hdr)
                if body:
                    up.sendall(body)
            except OSError:
                try:
                    up.close()
                except OSError:
                    pass
                return

            acc = b""
            while b"\r\n\r\n" not in acc and len(acc) < 2 * 1024 * 1024:
                ch = up.recv(RECV)
                if not ch:
                    break
                acc += ch
            if b"\r\n\r\n" not in acc:
                with lock:
                    print(f"{full_url} -> 502 (no response headers)")
                try:
                    up.close()
                except OSError:
                    pass
                return
            hb, pre_body = acc.split(b"\r\n\r\n", 1)
            code, chunked, content_len = parse_response_status_and_options(hb)
            with lock:
                print(f"{full_url} -> {code}")
            response_head = hb + b"\r\n\r\n"
            try:
                client.sendall(response_head)
                relay_response_body(up, client, pre_body, content_len, chunked)
            except OSError:
                pass
            try:
                up.close()
            except OSError:
                pass

            hreq = header_list_to_dict(headers)
            if hreq.get("connection", "").lower() == "close":
                return
    finally:
        try:
            client.close()
        except OSError:
            pass


def main() -> None:
    ap = argparse.ArgumentParser(description="HTTP proxy (KSIS lab 4)")
    ap.add_argument("--port", type=int, default=DEFAULT_PORT)
    ap.add_argument("--host", default="0.0.0.0")
    args = ap.parse_args()

    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    srv.bind((args.host, args.port))
    srv.listen(128)
    print(f"HTTP proxy слушает {args.host}:{args.port}")
    print("Браузер: только HTTP-прокси на этот адрес (без системного HTTPS).")
    lock = threading.Lock()
    try:
        while True:
            c, a = srv.accept()
            threading.Thread(
                target=handle_client, args=(c, a, lock), daemon=True
            ).start()
    except KeyboardInterrupt:
        print("\nОстанов.")
    finally:
        try:
            srv.close()
        except OSError:
            pass


if __name__ == "__main__":
    main()
