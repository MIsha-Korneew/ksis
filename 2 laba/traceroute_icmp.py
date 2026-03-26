# traceroute_icmp.py — аналог tracert (ICMP), для лабы
# Запуск: py traceroute_icmp.py <хост>
# Запускать от имени администратора!

import socket
import struct
import time
import sys
import os

ICMP_ECHO = 8
ICMP_ECHO_REPLY = 0
ICMP_TIME_EXCEEDED = 11


def checksum(data: bytes) -> int:
    """Контрольная сумма ICMP (RFC 792)."""
    n = len(data)
    i = 0
    total = 0
    while i < n - 1:
        total += (data[i] << 8) + data[i + 1]
        i += 2
    if i < n:
        total += data[i] << 8
    total = (total >> 16) + (total & 0xFFFF)
    total += total >> 16
    return ~total & 0xFFFF


def make_echo_packet(identifier: int, sequence: int) -> bytes:
    """Собирает ICMP Echo Request (ручная сборка, без готовых библиотек)."""
    header = struct.pack(
        "!BBHHH",
        ICMP_ECHO,  # type
        0,          # code
        0,          # checksum (пока 0)
        identifier,
        sequence
    )
    payload = bytes(32)  # данные
    packet = header + payload
    chk = checksum(packet)
    packet = struct.pack("!BBHHH", ICMP_ECHO, 0, chk, identifier, sequence) + payload
    return packet


def traceroute(host: str, max_hops: int = 30, probes: int = 3, debug: bool = False):
    print(f"ICMP Traceroute до {host} ({probes} пробы на hop)\n")

    try:
        dest_ip = socket.gethostbyname(host)
    except socket.gaierror:
        print("Не удалось разрешить имя хоста")
        return

    print(f"IP цели: {dest_ip}\n")

    try:
        # Один сокет для отправки и приёма — на Windows два raw-сокета могут конфликтовать
        sock = socket.socket(socket.AF_INET, socket.SOCK_RAW, socket.IPPROTO_ICMP)
        sock.settimeout(5 if debug else 2)
        # Привязка к 0.0.0.0 — на Windows без bind пакеты могут не доходить
        sock.bind(("0.0.0.0", 0))
    except PermissionError:
        print("Запустите скрипт от имени администратора.")
        sys.exit(1)

    ident = os.getpid() & 0xFFFF

    try:
        for ttl in range(1, max_hops + 1):
            sock.setsockopt(socket.IPPROTO_IP, socket.IP_TTL, ttl)
            print(f"{ttl:2d} ", end="")
            reached = False

            for seq in range(probes):
                pkt = make_echo_packet(ident, ttl * probes + seq)
                start = time.time()
                sock.sendto(pkt, (dest_ip, 0))

                try:
                    data, addr = sock.recvfrom(1024)
                    rtt_ms = (time.time() - start) * 1000

                    # IP header: 20 bytes, then ICMP
                    icmp_offset = 20
                    if len(data) < icmp_offset + 8:
                        if debug:
                            print(f"[? короткий пакет от {addr[0]}] ", end="")
                        else:
                            print("* ", end="")
                        continue

                    icmp_type = data[icmp_offset]
                    if debug:
                        print(f"[тип={icmp_type} от {addr[0]}] ", end="")

                    # Time Exceeded (от роутера) или Echo Reply (от цели)
                    if icmp_type == ICMP_TIME_EXCEEDED:
                        if not debug:
                            print(f"{addr[0]:<15} {rtt_ms:4.0f} ms ", end="")
                        reached = True
                    elif icmp_type == ICMP_ECHO_REPLY and addr[0] == dest_ip:
                        if not debug:
                            print(f"{addr[0]:<15} {rtt_ms:4.0f} ms  *** ЦЕЛЬ ***", end="")
                        reached = True
                        break
                    elif not debug:
                        print("* ", end="")

                except socket.timeout:
                    if debug:
                        print("[timeout] ", end="")
                    else:
                        print("* ", end="")

            print()
            if reached and addr[0] == dest_ip:
                break
    finally:
        sock.close()


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Использование: py traceroute_icmp.py <хост>  [-d]")
        print("  -d  отладочный режим (показывает все приходящие пакеты)")
        sys.exit(1)
    debug = "-d" in sys.argv or "--debug" in sys.argv
    host = [a for a in sys.argv[1:] if not a.startswith("-")][0]
    traceroute(host, debug=debug)

# -----------------------------------------------------------------------------
# Команды для запуска (запускать от имени администратора — иначе raw-сокет не откроется)
#
# --- CMD (командная строка) ---
#   cd <папка_с_скриптом>
#   py traceroute_icmp.py google.com
#   py traceroute_icmp.py google.com -d          # режим отладки
#
# --- Терминал PyCharm ---
#   cd <папка_с_скриптом>
#   py traceroute_icmp.py google.com
# -----------------------------------------------------------------------------
