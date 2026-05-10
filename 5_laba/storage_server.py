"""
ЛР5 — файловое хранилище (REST API по HTTP).

Запуск:
  cd /d "D:\\бугор\\ksis\\5_laba"
  py -m pip install -r requirements.txt
  py storage_server.py

По умолчанию: http://127.0.0.1:8765/ ; файлы в каталоге ./storage_data рядом со скриптом.

Примеры curl:
  curl -T hello.txt http://127.0.0.1:8765/docs/readme.txt
  curl http://127.0.0.1:8765/docs/
  curl -I http://127.0.0.1:8765/docs/readme.txt
  curl -X DELETE http://127.0.0.1:8765/docs/readme.txt

Браузер: URL файла — скачивание/просмотр; URL каталога со слэшем в конце — JSON-список.
Доп. задание (X-Copy-From) не реализовано.
"""
from __future__ import annotations

import mimetypes
import shutil
from datetime import datetime, timezone
from email.utils import formatdate
from pathlib import Path

from flask import Flask, Response, abort, jsonify, request, send_file

DEFAULT_HOST = "0.0.0.0"
DEFAULT_PORT = 8765
STORAGE_ROOT = Path(__file__).resolve().parent / "storage_data"


def http_code_caption(code: int) -> str:
    """Краткая расшифровка HTTP-кода для строки в консоли."""
    table = {
        200: "OK — успешно",
        201: "Created — ресурс создан",
        204: "No Content — без тела ответа (часто DELETE)",
        304: "Not Modified — не изменялось (кэш)",
        400: "Bad Request — плохой запрос",
        403: "Forbidden — доступ запрещён (выход за пределы хранилища)",
        404: "Not Found — нет файла или каталога",
        405: "Method Not Allowed — метод не поддерживается для ресурса",
        409: "Conflict — конфликт (например PUT на путь-каталог)",
        500: "Internal Server Error — ошибка сервера",
        501: "Not Implemented — не реализовано",
        502: "Bad Gateway — ошибка шлюза",
    }
    if code in table:
        return table[code]
    family = code // 100
    return {
        1: "1xx — информационный ответ",
        2: "2xx — успех",
        3: "3xx — перенаправление",
        4: "4xx — ошибка клиента",
        5: "5xx — ошибка сервера",
    }.get(family, "см. RFC 9110")


app = Flask(__name__)


@app.after_request
def _log_response(response: Response) -> Response:
    print(
        f"{request.method} {request.path} -> {response.status_code} "
        f"({http_code_caption(response.status_code)})"
    )
    return response


def resolved_target(rel: str) -> Path:
    """Путь внутри хранилища; защита от выхода за пределы STORAGE_ROOT."""
    rel = rel.replace("\\", "/").strip("/")
    base = STORAGE_ROOT.resolve()
    target = (base / rel).resolve()
    try:
        target.relative_to(base)
    except ValueError:
        abort(403)
    return target


def ensure_storage_root() -> None:
    STORAGE_ROOT.mkdir(parents=True, exist_ok=True)


@app.route("/", methods=["GET", "PUT", "HEAD", "DELETE"])
def root() -> Response:
    return dispatch("")


@app.route("/<path:subpath>", methods=["GET", "PUT", "HEAD", "DELETE"])
def with_path(subpath: str) -> Response:
    return dispatch(subpath)


def dispatch(rel: str) -> Response:
    ensure_storage_root()
    p = resolved_target(rel)

    if request.method == "PUT":
        return do_put(p)

    if request.method == "DELETE":
        return do_delete(p)

    if request.method == "HEAD":
        return do_head(p)

    return do_get(p)


def do_put(p: Path) -> Response:
    if p.exists() and p.is_dir():
        abort(409)
    existed = p.is_file()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(request.get_data())
    return Response(status=200 if existed else 201)


def do_delete(p: Path) -> Response:
    if not p.exists():
        abort(404)
    if p.is_file():
        p.unlink()
    elif p.is_dir():
        shutil.rmtree(p)
    else:
        abort(404)
    return Response(status=204)


def do_head(p: Path) -> Response:
    if not p.exists():
        abort(404)
    if p.is_dir():
        abort(405)
    st = p.stat()
    ctype, _ = mimetypes.guess_type(p.name)
    if not ctype:
        ctype = "application/octet-stream"
    return Response(
        status=200,
        headers={
            "Content-Length": str(st.st_size),
            "Content-Type": ctype,
            "Last-Modified": formatdate(st.st_mtime, usegmt=True),
        },
    )


def do_get(p: Path) -> Response:
    if not p.exists():
        abort(404)
    if p.is_dir():
        return list_dir_json(p)
    ctype, _ = mimetypes.guess_type(p.name)
    return send_file(
        p,
        mimetype=ctype or "application/octet-stream",
        as_attachment=False,
        download_name=p.name,
        conditional=True,
    )


def list_dir_json(p: Path) -> Response:
    items = []
    for child in sorted(p.iterdir(), key=lambda x: (not x.is_dir(), x.name.lower())):
        st = child.stat()
        items.append(
            {
                "name": child.name,
                "type": "directory" if child.is_dir() else "file",
                "size": None if child.is_dir() else st.st_size,
                "modified": datetime.fromtimestamp(
                    st.st_mtime, tz=timezone.utc
                ).isoformat(),
            }
        )
    return jsonify(items)


if __name__ == "__main__":
    print(f"Корень хранилища: {STORAGE_ROOT}")
    print(f"http://127.0.0.1:{DEFAULT_PORT}/")
    app.run(host=DEFAULT_HOST, port=DEFAULT_PORT, threaded=True)
