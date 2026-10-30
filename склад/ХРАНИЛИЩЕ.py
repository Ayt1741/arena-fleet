# -*- coding: utf-8 -*-
"""ХРАНИЛИЩЕ — общий склад в Telegram для всех агентов.

Один файл, который любой агент подключает строкой:

    import ХРАНИЛИЩЕ as Х
    Х.положить('/путь/файл.md', теги='совет,поиск')   # залить
    Х.взять('файл.md', '/куда/')                      # достать
    Х.список()                                        # что лежит
    Х.найти('память')                                 # поиск по именам, тегам, тексту
    Х.статистика()                                    # сколько файлов и байт

Почему частями: Bot API отдаёт файл не больше 20 МБ (getFile), а принимает до 50 МБ.
Поэтому всё крупнее 19 МБ режется на части, у каждой свой file_id. Сборка обратно —
по номеру части, с проверкой sha256 всего файла.

Бесплатно: места в Telegram не лимитировано, платить не нужно.
Работает на Windows и Linux, только стандартная библиотека Python.
"""
import hashlib
import json
import os
import sqlite3
import sys
import time
import urllib.error
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))          # корень рабочей папки
TG = os.path.join(ROOT, '.ФЛОТ-флот', 'tg')
CONFIG = os.path.join(TG, 'config.json')
STORE = os.path.join(ROOT, '.ФЛОТ-флот', 'хранилище')
DB = os.path.join(STORE, 'индекс.db')
CHUNK = 19 * 1024 * 1024                                # 19 МБ — безопасно для скачивания
API = 'https://api.telegram.org/bot%s/%s'


def _cfg():
    d = json.load(open(CONFIG, encoding='utf-8'))
    if not d.get('token') or not d.get('chat_id'):
        raise RuntimeError('в %s нужны token и chat_id' % CONFIG)
    return d['token'], str(d['chat_id'])


def _call(method, fields=None, token=None, timeout=600):
    token = token or _cfg()[0]
    body = json.dumps(fields or {}).encode()
    req = urllib.request.Request(API % (token, method), data=body, method='POST')
    req.add_header('Content-Type', 'application/json')
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        raise RuntimeError('%s: HTTP %s %s' % (method, e.code, e.read().decode()[:200]))


def _upload(path, caption, token, chat):
    """Одна отправка файла документом (≤ 50 МБ). Возвращает (file_id, размер)."""
    boundary = '----flotstore%d' % int(time.time() * 1000)
    name = os.path.basename(path)
    head = ('--%s\r\nContent-Disposition: form-data; name="chat_id"\r\n\r\n%s\r\n'
            '--%s\r\nContent-Disposition: form-data; name="caption"\r\n\r\n%s\r\n'
            '--%s\r\nContent-Disposition: form-data; name="document"; filename="%s"\r\n'
            'Content-Type: application/octet-stream\r\n\r\n'
            % (boundary, chat, boundary, caption.replace('\n', ' ')[:900], boundary, name))
    tail = '\r\n--%s--\r\n' % boundary
    data = open(path, 'rb').read()
    body = head.encode('utf-8') + data + tail.encode('utf-8')
    req = urllib.request.Request(API % (token, 'sendDocument'), data=body, method='POST')
    req.add_header('Content-Type', 'multipart/form-data; boundary=%s' % boundary)
    with urllib.request.urlopen(req, timeout=1800) as r:
        res = json.loads(r.read().decode())
    if not res.get('ok'):
        raise RuntimeError('sendDocument: %s' % str(res)[:200])
    doc = res['result']['document']
    return doc['file_id'], doc.get('file_size', len(data))


def _download(file_id, out, token):
    info = _call('getFile', {'file_id': file_id}, token=token)
    if not info.get('ok'):
        raise RuntimeError('getFile: %s' % str(info)[:200])
    url = 'https://api.telegram.org/file/bot%s/%s' % (token, info['result']['file_path'])
    with urllib.request.urlopen(url, timeout=1800) as r, open(out, 'wb') as f:
        while True:
            block = r.read(1 << 20)
            if not block:
                break
            f.write(block)
    return os.path.getsize(out)


def _sha256(path):
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        for block in iter(lambda: f.read(1 << 20), b''):
            h.update(block)
    return h.hexdigest()


def _db():
    os.makedirs(STORE, exist_ok=True)
    c = sqlite3.connect(DB)
    c.execute('''CREATE TABLE IF NOT EXISTS файлы(
        имя TEXT PRIMARY KEY, размер INTEGER, sha256 TEXT, частей INTEGER,
        file_ids TEXT, теги TEXT, время INTEGER, текст TEXT)''')
    c.execute('''CREATE VIRTUAL TABLE IF NOT EXISTS поиск USING fts5(имя, теги, текст)''')
    c.execute('''CREATE TABLE IF NOT EXISTS части(
        sha TEXT PRIMARY KEY, file_id TEXT, размер INTEGER, время INTEGER)''')
    c.execute('''CREATE TABLE IF NOT EXISTS версии(
        имя TEXT, sha TEXT, размер INTEGER, file_ids TEXT, время INTEGER)''')
    c.commit()
    return c


def _peek_text(path):
    """Первые 8 КБ текста — чтобы агенты искали по содержимому, а не только по имени."""
    if os.path.splitext(path)[1].lower() not in ('.md', '.txt', '.py', '.json', '.csv', '.cmd', '.js', '.yml', '.yaml'):
        return ''
    try:
        return open(path, encoding='utf-8', errors='ignore').read(8192)
    except Exception:
        return ''


# ------------------------------------------------------------------ то, чем пользуются агенты
def положить(path, теги=''):
    """Залить файл (или папку) в хранилище. Возвращает запись индекса."""
    if os.path.isdir(path):
        return [положить(os.path.join(path, f), теги) for f in sorted(os.listdir(path))
                if os.path.isfile(os.path.join(path, f))]
    token, chat = _cfg()
    size = os.path.getsize(path)
    sha = _sha256(path)
    c = _db()
    row = c.execute('SELECT имя FROM файлы WHERE sha256=?', (sha,)).fetchone()
    if row:
        c.close()
        return {'имя': row[0], 'sha256': sha, 'частей': 0, 'повтор': True}
    имя = os.path.basename(path)
    base, ext = os.path.splitext(имя)
    ids, n, повторно, залито = [], 0, 0, 0
    if size <= CHUNK:
        sha_ч = sha
        row = c.execute('SELECT file_id FROM части WHERE sha=?', (sha_ч,)).fetchone()
        if row:
            ids.append(row[0]); n = 1; повторно += 1
        else:
            fid, _ = _upload(path, '[%s] %s' % (теги or 'склад', имя), token, chat)
            ids.append(fid); n = 1; залито += 1
            c.execute('INSERT OR REPLACE INTO части VALUES(?,?,?,?)', (sha_ч, fid, size, int(time.time())))
    else:
        tmpdir = os.path.join(STORE, '_части')
        os.makedirs(tmpdir, exist_ok=True)
        parts = (size + CHUNK - 1) // CHUNK
        with open(path, 'rb') as f:
            for i in range(parts):
                piece = os.path.join(tmpdir, '%s.part%02d' % (base, i + 1))
                with open(piece, 'wb') as g:
                    g.write(f.read(CHUNK))
                sha_ч = _sha256(piece)
                row = c.execute('SELECT file_id FROM части WHERE sha=?', (sha_ч,)).fetchone()
                if row:                                  # такая часть уже лежит в Telegram
                    ids.append(row[0]); повторно += 1
                else:
                    fid, _ = _upload(piece, '[%s] %s часть %d/%d' % (теги or 'склад', имя, i + 1, parts), token, chat)
                    ids.append(fid); залито += 1
                    c.execute('INSERT OR REPLACE INTO части VALUES(?,?,?,?)',
                              (sha_ч, fid, os.path.getsize(piece), int(time.time())))
                os.remove(piece)
        n = parts
    старая = c.execute('SELECT sha256, размер, file_ids FROM файлы WHERE имя=?', (имя,)).fetchone()
    if старая and старая[0] != sha:                      # новая версия — старую не теряем
        c.execute('INSERT INTO версии VALUES(?,?,?,?,?)', (имя, старая[0], старая[1], старая[2], int(time.time())))
    c.execute('DELETE FROM поиск WHERE имя=?', (имя,))
    c.execute('INSERT OR REPLACE INTO файлы VALUES(?,?,?,?,?,?,?,?)',
              (имя, size, sha, n, json.dumps(ids), теги, int(time.time()), _peek_text(path)))
    c.execute('INSERT INTO поиск(имя, теги, текст) VALUES(?,?,?)', (имя, теги, _peek_text(path)))
    c.commit()
    c.close()
    return {'имя': имя, 'размер': size, 'sha256': sha, 'частей': n,
            'залито_частей': залито, 'повторно_частей': повторно}


def взять(имя, куда='.'):
    """Скачать файл из хранилища и собрать из частей. Проверяет sha256."""
    token, _ = _cfg()
    c = _db()
    row = c.execute('SELECT размер, sha256, частей, file_ids FROM файлы WHERE имя=?', (имя,)).fetchone()
    c.close()
    if not row:
        raise RuntimeError('в хранилище нет файла %s' % имя)
    size, sha, parts, ids = row
    ids = json.loads(ids)
    os.makedirs(куда, exist_ok=True)
    out = os.path.join(куда, имя)
    if len(ids) == 1:
        _download(ids[0], out, token)
    else:
        tmpdir = os.path.join(STORE, '_сборка')
        os.makedirs(tmpdir, exist_ok=True)
        pieces = []
        for i, fid in enumerate(ids, 1):
            p = os.path.join(tmpdir, 'p%02d' % i)
            _download(fid, p, token)
            pieces.append(p)
        with open(out, 'wb') as g:
            for p in pieces:
                g.write(open(p, 'rb').read())
                os.remove(p)
    got = _sha256(out)
    return {'файл': out, 'размер': os.path.getsize(out), 'sha256_совпал': got == sha}


def список(шаблон='%'):
    c = _db()
    rows = c.execute('SELECT имя, размер, частей, теги, время FROM файлы WHERE имя LIKE ? ORDER BY время DESC',
                     (шаблон,)).fetchall()
    c.close()
    return [{'имя': r[0], 'размер': r[1], 'частей': r[2], 'теги': r[3],
             'когда': time.strftime('%d.%m %H:%M', time.localtime(r[4]))} for r in rows]


def найти(текст, предел=20):
    c = _db()
    try:
        rows = c.execute('''SELECT имя, размер, теги FROM файлы WHERE rowid IN
                            (SELECT rowid FROM поиск WHERE поиск MATCH ?) LIMIT ?''',
                         ('%s*' % текст.replace('"', ''), предел)).fetchall()
    except sqlite3.OperationalError:
        rows = c.execute('SELECT имя, размер, теги FROM файлы WHERE имя LIKE ? LIMIT ?',
                         ('%%%s%%' % текст, предел)).fetchall()
    c.close()
    return [{'имя': r[0], 'размер': r[1], 'теги': r[2]} for r in rows]


def проверить(имя=None):
    """Сверяет содержимое частей в Telegram с индексом: скачивает и считает sha256."""
    token, _ = _cfg()
    c = _db()
    запрос = 'SELECT имя, sha256, file_ids FROM файлы' + (' WHERE имя=?' if имя else '')
    строки = c.execute(запрос, ((имя,) if имя else ())).fetchall()
    c.close()
    итог = []
    for имя_ф, sha_ф, ids in строки:
        ids = json.loads(ids)
        tmp = os.path.join(STORE, '_проверка')
        os.makedirs(tmp, exist_ok=True)
        части = []
        for i, fid in enumerate(ids, 1):
            p = os.path.join(tmp, 'p%02d' % i)
            _download(fid, p, token)
            части.append(p)
        путь = os.path.join(tmp, 'целиком')
        with open(путь, 'wb') as g:
            for p in части:
                g.write(open(p, 'rb').read())
                os.remove(p)
        ок = _sha256(путь) == sha_ф
        os.remove(путь)
        итог.append({'имя': имя_ф, 'частей': len(ids), 'целиком_совпало': ок})
    return итог


def версии(имя):
    c = _db()
    строки = c.execute('SELECT sha, размер, время FROM версии WHERE имя=? ORDER BY время DESC', (имя,)).fetchall()
    c.close()
    return [{'sha256': r[0], 'размер': r[1], 'когда': time.strftime('%d.%m %H:%M', time.localtime(r[2]))}
            for r in строки]


def статистика():
    c = _db()
    n, s = c.execute('SELECT COUNT(*), COALESCE(SUM(размер),0) FROM файлы').fetchone()
    ч, ч_байт = c.execute('SELECT COUNT(*), COALESCE(SUM(размер),0) FROM части').fetchone()
    в = c.execute('SELECT COUNT(*) FROM версии').fetchone()[0]
    c.close()
    return {'файлов': n, 'байт': s, 'МБ': round(s / 1048576, 1),
            'уникальных_частей': ч,
            'старых_версий': в, 'индекс': DB}


def синхронизировать(папка, теги=''):
    """Залить только новое и изменённое: сравнивает sha256 с индексом."""
    c = _db()
    known = dict(c.execute('SELECT sha256, имя FROM файлы').fetchall())
    c.close()
    ПРОПУСК = {'.cache', '.local', '.npm', '.venv', '__pycache__', 'node_modules',
              '.git', 'dist', 'build', 'out', 'target', '.playwright-cli', '.mypy_cache'}
    done, skipped = [], 0
    for root, dirs, files in os.walk(папка):
        dirs[:] = [d for d in dirs if d not in ПРОПУСК]
        for f in sorted(files):
            p = os.path.join(root, f)
            if os.path.getsize(p) == 0 or f.endswith(('.pyc', '.log', '.tmp')):
                continue
            if _sha256(p) in known:
                skipped += 1
                continue
            done.append(положить(p, теги))
    return {'залито': len(done), 'пропущено_таких_же': skipped}


def test():
    token, chat = _cfg()
    me = _call('getMe', token=token)
    chat_info = _call('getChat', {'chat_id': chat}, token=token)
    c = _db()
    n = c.execute('SELECT COUNT(*) FROM файлы').fetchone()[0]
    c.close()
    return {'бот': me.get('result', {}).get('username'), 'чат': chat_info.get('result', {}).get('title'),
            'записей в индексе': n}


# ------------------------------------------------------------------ командная строка
def _main(argv):
    if not argv or argv[0] in ('-h', '--help', 'помощь'):
        print(__doc__)
        return 0
    cmd = argv[0]
    try:
        if cmd in ('put', 'положить'):
            r = положить(argv[1], argv[2] if len(argv) > 2 else '')
            print(json.dumps(r, ensure_ascii=False, indent=1))
        elif cmd in ('get', 'взять'):
            r = взять(argv[1], argv[2] if len(argv) > 2 else '.')
            print(json.dumps(r, ensure_ascii=False, indent=1))
        elif cmd in ('ls', 'список'):
            for r in список(argv[1] if len(argv) > 1 else '%'):
                print('%-44s %9d Б  частей %-3d %-18s %s' % (r['имя'][:44], r['размер'], r['частей'], r['когда'], r['теги']))
        elif cmd in ('find', 'найти'):
            for r in найти(argv[1]):
                print('%-44s %9d Б  %s' % (r['имя'][:44], r['размер'], r['теги']))
        elif cmd in ('stat', 'статистика'):
            print(json.dumps(статистика(), ensure_ascii=False, indent=1))
        elif cmd in ('sync', 'синхронизировать'):
            print(json.dumps(синхронизировать(argv[1], argv[2] if len(argv) > 2 else ''), ensure_ascii=False))
        elif cmd in ('проверить', 'verify'):
            for r in проверить(argv[1] if len(argv) > 1 else None):
                print('%-44s частей %-3d целостность: %s' % (r['имя'][:44], r['частей'], 'СОВПАЛО' if r['целиком_совпало'] else 'БИТО'))
        elif cmd in ('версии', 'versions'):
            for r in версии(argv[1]):
                print('%s  %9d Б  %s' % (r['sha256'][:16], r['размер'], r['когда']))
        elif cmd == 'test':
            print(json.dumps(test(), ensure_ascii=False, indent=1))
        else:
            print('не знаю команду %s' % cmd)
            return 2
    except Exception as e:
        print('ОШИБКА: %s' % e)
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(_main(sys.argv[1:]))
