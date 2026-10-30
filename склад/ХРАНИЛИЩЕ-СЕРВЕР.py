# -*- coding: utf-8 -*-
"""ХРАНИЛИЩЕ-СЕРВЕР — доступ к складу Telegram с ЛЮБОГО ПК по обычному HTTP.

Зачем: агент может работать на другой машине, в GitHub Actions или на телефоне.
Ему не нужен Python и наши файлы — достаточно curl или requests.

Поднимает HTTP на 0.0.0.0:8099 (порт и токен в .ФЛОТ-флот/хранилище/сервер.json).

Что умеет:
  GET  /здоровье                     — ответ {"ок": true} (проверка живости)
  GET  /статистика                   — сколько файлов и байт
  GET  /список                       — все файлы склада
  GET  /найти?q=слово                — поиск по именам и содержимому
  GET  /файл?имя=имя.md              — скачать файл (собирает из частей, сверяет sha256)
  PUT  /файл?имя=имя.md&теги=теги    — залить файл (тело запроса = содержимое)

Авторизация: заголовок X-Token: <токен>, или Authorization: Bearer <токен>, или ?token=<токен>.
Слушает все интерфейсы — поэтому токен обязателен, без него сервер не отвечает.

Запуск: ХРАНИЛИЩЕ-СЕРВЕР.cmd
"""
import json
import os
import sys
import threading
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
СТОРОНА = os.path.join(ROOT, '.ФЛОТ-флот', 'хранилище')
КОНФИГ = os.path.join(СТОРОНА, 'сервер.json')
ВРЕМЕННО = os.path.join(СТОРОНА, '_сервер')
sys.path.insert(0, HERE)
import ХРАНИЛИЩЕ as Х  # noqa: E402


def конфиг():
    os.makedirs(СТОРОНА, exist_ok=True)
    if not os.path.exists(КОНФИГ):
        import secrets
        json.dump({'порт': 8099, 'токен': secrets.token_urlsafe(24)},
                  open(КОНФИГ, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    return json.load(open(КОНФИГ, encoding='utf-8'))


КФГ = конфиг()


class Обработчик(BaseHTTPRequestHandler):
    server_version = 'flot-store/1.0'

    def _ответ(self, код, данные, тип='application/json'):
        if isinstance(данные, (dict, list)):
            данные = json.dumps(данные, ensure_ascii=False).encode()
        elif isinstance(данные, str):
            данные = данные.encode()
        self.send_response(код)
        self.send_header('Content-Type', тип + '; charset=utf-8')
        self.send_header('Content-Length', str(len(данные)))
        self.end_headers()
        self.wfile.write(данные)

    def _токен_верен(self, разбор):
        параметры = urllib.parse.parse_qs(разбор.query)
        # имя заголовка только латиницей: HTTP не пропускает кириллицу в именах заголовков
        прислан = (self.headers.get('X-Token') or self.headers.get('Authorization', '').replace('Bearer ', '')
                   or (параметры.get('token') or параметры.get('токен') or [''])[0])
        return прислан == КФГ['токен']

    def do_GET(self):
        разбор = urllib.parse.urlparse(self.path)
        путь = urllib.parse.unquote(разбор.path).rstrip('/') or '/'
        if путь in ('/здоровье', '/health'):
            return self._ответ(200, {'ок': True, 'склад': Х.статистика()['файлов']})
        if not self._токен_верен(разбор):
            return self._ответ(403, {'ошибка': 'нужен верный токен'})
        if путь in ('/статистика', '/stat'):
            return self._ответ(200, Х.статистика())
        if путь in ('/список', '/list'):
            return self._ответ(200, Х.список())
        if путь in ('/найти', '/find'):
            п = urllib.parse.parse_qs(разбор.query)
            q = (п.get('q') or п.get('запрос') or [''])[0]
            return self._ответ(200, Х.найти(q))
        if путь in ('/файл', '/file'):
            п = urllib.parse.parse_qs(разбор.query)
            имя = (п.get('name') or п.get('имя') or [''])[0]
            if not имя:
                return self._ответ(400, {'ошибка': 'нужно ?имя=файл'})
            os.makedirs(ВРЕМЕННО, exist_ok=True)
            try:
                r = Х.взять(имя, ВРЕМЕННО)
            except Exception as e:
                return self._ответ(404, {'ошибка': str(e)[:200]})
            данные = open(r['файл'], 'rb').read()
            os.remove(r['файл'])
            return self._ответ(200, данные, 'application/octet-stream')
        return self._ответ(404, {'ошибка': 'не знаю такой адрес',
                                 'есть': ['/health', '/stat', '/list', '/find?q=', '/file?name=', 'PUT /file?name=&tags=']})

    def do_PUT(self):
        разбор = urllib.parse.urlparse(self.path)
        if urllib.parse.unquote(разбор.path).rstrip('/') not in ('/файл', '/file'):
            return self._ответ(404, {'ошибка': 'PUT только на /файл'})
        if not self._токен_верен(разбор):
            return self._ответ(403, {'ошибка': 'нужен верный токен'})
        п = urllib.parse.parse_qs(разбор.query)
        имя = (п.get('name') or п.get('имя') or [''])[0]
        теги = (п.get('tags') or п.get('теги') or ['с-сервера'])[0]
        if not имя:
            return self._ответ(400, {'ошибка': 'нужно ?имя=файл'})
        длина = int(self.headers.get('Content-Length') or 0)
        os.makedirs(ВРЕМЕННО, exist_ok=True)
        путь = os.path.join(ВРЕМЕННО, os.path.basename(имя))
        осталось = длина
        with open(путь, 'wb') as f:
            while осталось > 0:
                блок = self.rfile.read(min(1 << 20, осталось))
                if not блок:
                    break
                f.write(блок)
                осталось -= len(блок)
        try:
            r = Х.положить(путь, теги)
        finally:
            if os.path.exists(путь):
                os.remove(путь)
        return self._ответ(200, r)

    def do_POST(self):
        return self.do_PUT()

    def log_message(self, формат, *аргументы):
        строка = '%s  %s' % (self.address_string(), формат % аргументы)
        try:
            with open(os.path.join(ROOT, 'ЛОГ-ХРАНИЛИЩА-СЕРВЕРА.txt'), 'a', encoding='utf-8') as f:
                f.write(строка + '\n')
        except Exception:
            pass


def поднять(порт=None):
    порт = int(порт or КФГ['порт'])
    сервер = ThreadingHTTPServer(('0.0.0.0', порт), Обработчик)
    print('ХРАНИЛИЩЕ-СЕРВЕР поднят: http://0.0.0.0:%d' % порт)
    print('токен: %s' % КФГ['токен'])
    print('проверка: curl "http://127.0.0.1:%d/здоровье"' % порт)
    print('с другого ПК — тот же адрес, но с токеном в заголовке X-Токен')
    try:
        сервер.serve_forever()
    except KeyboardInterrupt:
        print('остановлен')
    return 0


if __name__ == '__main__':
    sys.exit(поднять(sys.argv[1] if len(sys.argv) > 1 else None))
