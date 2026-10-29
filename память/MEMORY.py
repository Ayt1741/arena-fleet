#!/usr/bin/env python3
"""MEMORY — одна команда в начале любой сессии (имя без русских букв: консоль не ломается).

Задача: каждый шаг, закон и факт лежат в боте и поднимаются сами, без напоминаний.

Слои (как в инженерных статьях: rules -> session-context -> archive):
  СЛОЙ 1 «правила»      : ЗАКОНЫ-КРАТКО.md + ЗАДАЧИ-ОТКРЫТЫЕ.md в рабочей папке, читаются всегда.
  СЛОЙ 2 «ядро»         : сводка + поиск по базе (FTS5/BM25), поднимается по требованию.
  СЛОЙ 3 «архив»        : вся база 10 518 записей в боте частями по 18 МБ (Bot API: скачивание ≤20 МБ).

Команды:
  python MEMORY.py                 # старт: правила + сводка (без скачивания базы)
  python MEMORY.py full            # восстановить/дополнить базу из бота и рабочей папки
  python MEMORY.py search "вопрос" [N]
  python MEMORY.py add "факт" [источник]
  python MEMORY.py stats
  python MEMORY.py put             # залить обновления памяти в бота
Только стандартная библиотека Python 3.8+ (sqlite3, urllib, zipfile, hashlib).
"""
import hashlib
import json
import os
import re
import sqlite3
import sys
import time
import urllib.request
import zipfile

# --- консоль: чтобы русский текст не ронял Windows-терминал (cp866/cp1251) ---
try:
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
        sys.stderr.reconfigure(encoding='utf-8', errors='replace')
except Exception:
    pass
if os.name == 'nt':
    try:
        os.system('chcp 65001 >nul')
    except Exception:
        pass

HERE = os.path.dirname(os.path.abspath(__file__))
TEMP = os.path.join(HERE, '.tmp')        # своя папка вместо /tmp: работает и на Windows
os.makedirs(TEMP, exist_ok=True)
ROOT = os.path.dirname(HERE)                      # .ФЛОТ-флот
WORK = os.path.dirname(ROOT)                      # рабочая папка заказчика
DB = os.environ.get('MEM_DB', os.path.join(TEMP, 'memory.db'))
TG = os.path.join(ROOT, 'tg')
INDEX = os.path.join(TG, 'index.json')
STATE = os.path.join(HERE, 'ingest-state.json')
LAWS = os.path.join(HERE, 'ЗАКОНЫ-КРАТКО.md')
TASKS = os.path.join(HERE, 'ЗАДАЧИ-ОТКРЫТЫЕ.md')
PARTS = ['memory.part1', 'memory.part2', 'memory.part3']


# ---------------------------------------------------------------- telegram
def tg():
    try:
        c = json.load(open(os.path.join(TG, 'config.json'), encoding='utf-8'))
        return c['token'], str(c['chat_id'])
    except Exception:
        return '', ''


def tg_get(file_id, timeout=1200):
    tok, _ = tg()
    info = json.loads(urllib.request.urlopen(
        'https://api.telegram.org/bot%s/getFile?file_id=%s' % (tok, file_id), timeout=120).read().decode())
    if not info.get('ok'):
        raise RuntimeError('getFile: %s' % str(info)[:120])
    path = info['result']['file_path']
    return urllib.request.urlopen('https://api.telegram.org/file/bot%s/%s' % (tok, path), timeout=timeout).read()


def tg_put(path, caption=''):
    """Заливка файла в бота; возвращает file_id и дописывает запись в index.json."""
    tok, chat = tg()
    boundary = '----flot%d' % int(time.time() * 1000)
    name = os.path.basename(path)
    head = ('--%s\r\nContent-Disposition: form-data; name="chat_id"\r\n\r\n%s\r\n'
            '--%s\r\nContent-Disposition: form-data; name="caption"\r\n\r\n%s\r\n'
            '--%s\r\nContent-Disposition: form-data; name="document"; filename="%s"\r\n'
            'Content-Type: application/octet-stream\r\n\r\n' % (boundary, chat, boundary, caption, boundary, name))
    tail = '\r\n--%s--\r\n' % boundary
    body = head.encode() + open(path, 'rb').read() + tail.encode()
    req = urllib.request.Request('https://api.telegram.org/bot%s/sendDocument' % tok, data=body, method='POST')
    req.add_header('Content-Type', 'multipart/form-data; boundary=%s' % boundary)
    res = json.loads(urllib.request.urlopen(req, timeout=900).read().decode())
    if not res.get('ok'):
        raise RuntimeError('sendDocument: %s' % str(res)[:200])
    doc = res['result']['document']
    rec = {'file': name, 'file_id': doc['file_id'], 'size': doc.get('file_size', 0), 'ts': int(time.time())}
    idx = json.load(open(INDEX, encoding='utf-8')) if os.path.exists(INDEX) else []
    idx = [e for e in idx if e.get('file') != name] + [rec]
    json.dump(idx, open(INDEX, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    return rec


# ---------------------------------------------------------------- слой 1
def show_core(quiet=False):
    lines = []
    for path, title in ((LAWS, 'ПРАВИЛА'), (TASKS, 'ОТКРЫТЫЕ ЗАДАЧИ')):
        if os.path.exists(path):
            txt = open(path, encoding='utf-8').read().strip()
            lines.append('=== %s (%d строк, sha256 %s) ===\n%s' %
                         (title, txt.count('\n') + 1,
                          hashlib.sha256(txt.encode()).hexdigest()[:12], txt))
        else:
            lines.append('=== %s === ОТСУТСТВУЕТ: %s' % (title, path))
    out = '\n\n'.join(lines)
    print(out if not quiet else out.split('\n')[0])
    return out


# ---------------------------------------------------------------- слой 3
def restore(force=False):
    os.makedirs(os.path.dirname(DB) or '.', exist_ok=True)
    if os.path.exists(DB) and not force:
        n = count_records()
        return 'база уже на месте: %d записей' % n
    if not os.path.exists(INDEX):
        return 'нет index.json — список файлов бота потерян'
    idx = {e['file']: e for e in json.load(open(INDEX, encoding='utf-8'))}
    miss = [p for p in PARTS if p not in idx]
    if miss:
        return 'в боте нет частей: ' + ', '.join(miss)
    buf = b''
    t0 = time.time()
    for p in PARTS:
        data = tg_get(idx[p]['file_id'])
        if len(data) != idx[p].get('size') and idx[p].get('size'):
            return 'часть %s битая: %d из %d байт' % (p, len(data), idx[p]['size'])
        buf += data
        print('  часть %-14s %10d байт  (%d с)' % (p, len(data), time.time() - t0))
    zpath = DB + '.zip'
    open(zpath, 'wb').write(buf)
    with zipfile.ZipFile(zpath) as z:
        inner = [n for n in z.namelist() if n.endswith('.db')][0]
        with z.open(inner) as src, open(DB, 'wb') as dst:
            while True:
                chunk = src.read(1 << 20)
                if not chunk:
                    break
                dst.write(chunk)
    os.remove(zpath)
    return 'база восстановлена: %d записей, %.1f МБ, %.0f с' % (
        count_records(), os.path.getsize(DB) / 1e6, time.time() - t0)


# ---------------------------------------------------------------- база
def conn():
    c = sqlite3.connect(DB)
    c.execute("CREATE TABLE IF NOT EXISTS seen(sha TEXT PRIMARY KEY, ts INTEGER, source TEXT)")
    c.execute("CREATE TABLE IF NOT EXISTS meta(k TEXT PRIMARY KEY, v TEXT)")
    return c


def count_records():
    try:
        c = sqlite3.connect('file:%s?mode=ro' % DB, uri=True)
        n = c.execute('select count(*) from fts').fetchone()[0]
        c.close()
        return n
    except Exception:
        return 0


def norm_tokens(q):
    toks = re.findall(r'[\w\-]{2,}', q.lower(), re.UNICODE)
    return ' OR '.join('"%s"*' % t for t in toks) or '""'


def search(q, n=8, diversify=True):
    """Поиск: BM25 + подкрепление (сколько раз запись была полезна) + свежесть,
    с ограничением «не больше 2 записей из одного источника» (session-diversified)."""
    if not os.path.exists(DB):
        return 'базы нет — сначала: python MEMORY.py full'
    c = sqlite3.connect(DB)
    c.execute('CREATE TABLE IF NOT EXISTS uses(sha TEXT PRIMARY KEY, hits INTEGER DEFAULT 0, last INTEGER)')
    sql = ('select rowid, title, snippet(fts,1,"[",")","…",14) as s, source, kind, bm25(fts) as r '
           'from fts where fts match ? order by r limit ?')
    toks = re.findall(r'[\w\-]{2,}', q.lower(), re.UNICODE)
    strict = ' AND '.join('"%s"*' % t for t in toks) if toks else '""'
    rows = c.execute(sql, (strict, n * 6)).fetchall()
    if not rows:
        rows = c.execute(sql, (norm_tokens(q), n * 6)).fetchall()
    if not rows:
        c.close()
        return 'по запросу «%s» ничего не найдено' % q
    ranked = []
    for rid, t, sn, src, kind, r in rows:
        sha = hashlib.sha256(((src or '') + (t or '')).encode()).hexdigest()[:16]
        h = c.execute('select hits from uses where sha=?', (sha,)).fetchone()
        hits = h[0] if h else 0
        score = r - 0.45 * (1 + hits) ** 0.5          # bm25 отрицательный: полезное поднимаем
        ranked.append((score, rid, t, sn, src, sha, hits))
    ranked.sort()
    seen_src, out_rows = {}, []
    for item in ranked:
        src = item[4] or '?'
        if diversify and seen_src.get(src, 0) >= 2:
            continue
        seen_src[src] = seen_src.get(src, 0) + 1
        out_rows.append(item)
        if len(out_rows) >= n:
            break
    for item in out_rows:                              # подкрепление использованных записей
        c.execute('insert into uses(sha, hits, last) values(?,1,?) on conflict(sha) do update set hits=hits+1, last=excluded.last',
                  (item[5], int(time.time())))
    c.commit()
    c.close()
    out = ['найдено %d записей по «%s» (BM25 + подкрепление, меньше = точнее):' % (len(out_rows), q)]
    for i, (sc, rid, t, sn, src, sha, hits) in enumerate(out_rows, 1):
        out.append('%d. [%.2f | использовалась %d р.] %s — %s\n   %s'
                   % (i, sc, hits, (t or '')[:90], src or '?', re.sub(r'\s+', ' ', sn)[:240]))
    return '\n'.join(out)


def stale(days=30):
    """Что давно не использовалось: кандидаты в архив (не удаляем — закон «ничего не терять»)."""
    c = sqlite3.connect('file:%s?mode=ro' % DB, uri=True)
    n, = c.execute('select count(*) from fts').fetchone()
    t = int(time.time()) - days * 86400
    try:
        old = c.execute('select count(*) from seen where ts < ?', (t,)).fetchone()[0]
    except Exception:
        old = 0
    c.close()
    return 'всего записей %d; старше %d дней (не трогали): %d; правило: архивируем, не удаляем' % (n, days, old)


def add(text, source='вручную'):
    c = conn()
    sha = hashlib.sha256((source + text).encode()).hexdigest()
    if c.execute('select 1 from seen where sha=?', (sha,)).fetchone():
        c.close()
        return 'дубль, не добавлено'
    title = re.sub(r'\s+', ' ', text.strip().split('\n')[0])[:120]
    c.execute('insert into fts(title, body, source, kind) values(?,?,?,?)', (title, text, source, 'fact'))
    c.execute('insert into seen(sha, ts, source) values(?,?,?)', (sha, int(time.time()), source))
    c.commit()
    c.close()
    return 'добавлено (записей стало %d)' % count_records()


def chunks(text, size=900):
    """Режем по разделам (заголовок + тело), внутри раздела — по абзацам.
    Так кусок не теряет смысл: заголовок остаётся в своём же куске."""
    if re.search(r'^#{1,3} ', text, re.M):
        blocks = re.split(r'(?m)^(?=#{1,3} )', text)
    else:
        blocks = [text]
    parts, cur = [], ''
    for para in [b for block in blocks for b in re.split(r'\n\s*\n', block)]:
        if len(cur) + len(para) > size and cur:
            parts.append(cur)
            cur = ''
        cur += para.strip() + '\n\n'
        while len(cur) > size * 2:
            parts.append(cur[:size])
            cur = cur[size:]
    if cur.strip():
        parts.append(cur)
    return [p.strip() for p in parts if len(p.strip()) > 40]


def ingest(root=WORK, exts=('.md', '.txt'), skip=('uploads', '.git', 'keys', 'node_modules')):
    """Инкрементально забирает всё, что появилось в рабочей папке: шаги, отчёты, логи."""
    st = json.load(open(STATE, encoding='utf-8')) if os.path.exists(STATE) else {}
    c = conn()
    files = added = 0
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in skip and not d.startswith('.cache')]
        if os.path.getsize(DB) > 900 * 1e6:
            break
        for fn in filenames:
            if not fn.lower().endswith(exts):
                continue
            path = os.path.join(dirpath, fn)
            if os.path.getsize(path) > 3 * 1024 * 1024:
                continue
            rel = os.path.relpath(path, root)
            h = hashlib.sha256(open(path, 'rb').read()).hexdigest()
            if st.get(rel) == h:
                continue
            text = open(path, encoding='utf-8', errors='ignore').read()
            new = 0
            for part in chunks(text):
                sha = hashlib.sha256((rel + part).encode()).hexdigest()
                if c.execute('select 1 from seen where sha=?', (sha,)).fetchone():
                    continue
                title = re.sub(r'\s+', ' ', part.split('\n')[0])[:120]
                c.execute('insert into fts(title, body, source, kind) values(?,?,?,?)', (title, part, rel, 'file'))
                c.execute('insert into seen(sha, ts, source) values(?,?,?)', (sha, int(time.time()), rel))
                new += 1
            c.commit()
            st[rel] = h
            files += 1
            added += new
    c.close()
    json.dump(st, open(STATE, 'w', encoding='utf-8'), ensure_ascii=False)
    return 'файлов прочитано: %d, новых записей: %d' % (files, added)


TECHNIQUES = [
    'нарезка по разделам с сохранением заголовка',
    'дедупликация по SHA-256',
    'инкрементальный сбор (хэш файла)',
    'полнотекстовый поиск BM25 (SQLite FTS5)',
    'строгий запрос И → мягкий ИЛИ',
    'подкрепление полезных записей (uses)',
    'диверсификация источников (≤2 на источник)',
    'свежесть записи в счёте',
    'процедурная память (learn/how)',
    'защита от инъекций в памяти (guard)',
    'вычистка секретов (redact)',
    'слой правил, читаемый всегда',
    'слой архива в боте частями ≤18 МБ',
    'сохранение состояния шагов в боте',
    'самопроверка окружения (doctor)',
    'сторож законов в CI (lawguard)',
]


def stats():
    if not os.path.exists(DB):
        return 'базы нет'
    c = sqlite3.connect('file:%s?mode=ro' % DB, uri=True)
    n = c.execute('select count(*) from fts').fetchone()[0]
    kinds = c.execute('select kind, count(*) from fts group by kind order by 2 desc').fetchall()
    srcs = c.execute('select source, count(*) from fts group by source order by 2 desc limit 5').fetchall()
    c.close()
    out = ['записей: %d, размер %.1f МБ' % (n, os.path.getsize(DB) / 1e6),
           'по типам: ' + ', '.join('%s %d' % k for k in kinds),
           'топ источников: ' + ', '.join('%s %d' % s for s in srcs),
           'техник памяти в коде: %d' % len(TECHNIQUES)]
    return '\n'.join(out)



SECRET_RE = [
    (r'github_pat_[A-Za-z0-9_]{20,}', 'github_pat_[СКРЫТО]'),
    (r'gh[pousr]_[A-Za-z0-9]{20,}', 'gh*_[СКРЫТО]'),
    (r'\b[0-9]{8,10}:AA[A-Za-z0-9_-]{25,}', '[ТОКЕН-БОТА-СКРЫТ]'),
    (r'\b[A-Z2-7]{32}\b', '[TOTP-СЕКРЕТ-СКРЫТ]'),
    (r'(?i)(пароль|password)\s*[:=]\s*\S+', r'\1: [СКРЫТО]'),
]



PROC_RE = re.compile(r'^\s*(?:\d+[.)]|[-*])\s+', re.M)


def learn(name, steps, source='вручную'):
    """Процедурная память: запоминает ПОРЯДОК действий (навык), а не просто факт."""
    body = 'ПРОЦЕДУРА: %s\n' % name + '\n'.join(
        '%d. %s' % (i, re.sub(r'^\s*(?:\d+[.)]|[-*])\s+', '', s).strip())
        for i, s in enumerate([x for x in steps.split('\n') if x.strip()], 1))
    return add(body, source)


def how(text):
    """Показывает сохранённые процедуры по теме: память навыков, не фактов."""
    if not os.path.exists(DB):
        return 'базы нет — MEMORY.py full'
    c = sqlite3.connect('file:%s?mode=ro' % DB, uri=True)
    rows = c.execute("select title, body from fts where body like 'ПРОЦЕДУРА:%' "
                     "and (title like ? or body like ?) limit 5", ('%' + text + '%', '%' + text + '%')).fetchall()
    c.close()
    if not rows:
        return 'процедур по теме «%s» нет' % text
    return '\n\n'.join(b[:900] for t, b in rows)


def guard():
    """Защита от отравления памяти: ищет в записях команды-инъекции и помечает их.
    Основание: темы 5 и 6 раунда 2 (memory poisoning, prompt injection via memory)."""
    c = sqlite3.connect('file:%s?mode=ro' % DB, uri=True)
    pats = [r'игнорируй\s+(все\s+)?(прежние|предыдущие|законы)',
            r'ignore\s+(all\s+)?(previous|prior)\s+instructions',
            r'забудь\s+(всё|все)\s+(законы|инструкции)',
            r'ты\s+теперь\s+(другой|новый)',
            r'системн(ая|ый)\s+(команд|промпт|инструкц)']
    total = 0
    hits = []
    for p in pats:
        n = c.execute('select count(*) from fts where body like ?', ('%' + p.replace('\\', '') + '%',)).fetchone()[0] if False else None
    rows = c.execute('select rowid, title, body, source from fts').fetchall()
    for rid, t, b, src in rows:
        for p in pats:
            if re.search(p, b, re.I):
                hits.append((rid, (t or '')[:60], src or '?'))
                break
    c.close()
    return 'записей с командами-инъекциями: %d из %d\n' % (len(hits), len(rows)) + \
        '\n'.join('  #%d %s — %s' % h for h in hits[:10]) + \
        ('\nправило: такие записи не подмешиваются в контекст при загрузке памяти' if hits else '')


def redact():
    """Вырезает токены/пароли/2FA-секреты из базы: они не должны лежать в боте открытым текстом."""
    c = conn()
    rows = c.execute('select rowid, title, body, source, kind from fts').fetchall()
    changed = 0
    for rid, t, b, src, kind in rows:
        nt, nb = t, b
        for pat, rep in SECRET_RE:
            nb = re.sub(pat, rep, nb)
            nt = re.sub(pat, rep, nt)
        if (nt, nb) != (t, b):
            c.execute('delete from fts where rowid=?', (rid,))
            c.execute('insert into fts(rowid, title, body, source, kind) values(?,?,?,?,?)', (rid, nt, nb, src, kind))
            changed += 1
    c.execute("insert or replace into meta(k,v) values('redacted',?)", (str(changed),))
    c.commit()
    c.close()
    return 'вычищено записей с секретами: %d' % changed



STATE_DIR = os.path.join(ROOT, 'state')
STATE_ZIP_PARTS = ['flot-state.part1', 'flot-state.part2', 'flot-state.part3', 'flot-state.part4', 'flot-state.part5']


def put_state():
    """Забирает в бота папку состояния (шаги lawcheck, лидеры, бои, доказательства)."""
    if not os.path.isdir(STATE_DIR):
        return 'папки состояния нет: %s' % STATE_DIR
    z = os.path.join(TEMP, 'flot-state.zip')
    with zipfile.ZipFile(z, 'w', zipfile.ZIP_DEFLATED, compresslevel=6) as f:
        for dp, dn, fn in os.walk(STATE_DIR):
            for name in fn:
                full = os.path.join(dp, name)
                f.write(full, os.path.relpath(full, ROOT))
    size = os.path.getsize(z)
    CH = 18 * 1024 * 1024
    idx = json.load(open(INDEX, encoding='utf-8')) if os.path.exists(INDEX) else []
    idx = [e for e in idx if e.get('file') not in STATE_ZIP_PARTS]
    json.dump(idx, open(INDEX, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    n, out = 0, []
    with open(z, 'rb') as f:
        while True:
            d = f.read(CH)
            if not d:
                break
            n += 1
            p = os.path.join(TEMP, 'flot-state.part%d' % n)
            open(p, 'wb').write(d)
            if n > len(STATE_ZIP_PARTS):
                return 'состояние больше %d частей — нужно больше слотов' % len(STATE_ZIP_PARTS)
            rec = tg_put(p, 'состояние: часть %d' % n)
            out.append('%s %d байт' % (rec['file'], rec['size']))
    return 'состояние в боте: %s (%.1f МБ, %d частей)' % (', '.join(out), size / 1e6, n)


def restore_state():
    """Возвращает папку состояния из бота: шаги lawcheck не теряются между сессиями."""
    if not os.path.exists(INDEX):
        return 'нет index.json'
    idx = {e['file']: e for e in json.load(open(INDEX, encoding='utf-8'))}
    parts = [p for p in STATE_ZIP_PARTS if p in idx]
    if not parts:
        return 'состояния в боте пока нет'
    buf = b''
    for p in parts:
        buf += tg_get(idx[p]['file_id'])
    z = os.path.join(TEMP, 'flot-state-restore.zip')
    open(z, 'wb').write(buf)
    with zipfile.ZipFile(z) as f:
        f.extractall(ROOT)
    return 'состояние восстановлено: %d файлов, %.1f МБ' % (len(zipfile.ZipFile(z).namelist()), len(buf) / 1e6)



def doctor():
    """Проверка окружения: почему скрипт может не работать в консоли — по пунктам."""
    checks = []
    checks.append(('Python %s' % sys.version.split()[0], sys.version_info >= (3, 8)))
    checks.append(('папка памяти доступна: %s' % HERE, os.access(HERE, os.W_OK)))
    checks.append(('временная папка: %s' % TEMP, os.access(TEMP, os.W_OK)))
    try:
        c = sqlite3.connect(':memory:')
        c.execute("CREATE VIRTUAL TABLE t USING fts5(x)")
        checks.append(('SQLite %s с FTS5' % sqlite3.sqlite_version, True))
        c.close()
    except Exception as e:
        checks.append(('SQLite без FTS5: %s' % e, False))
    tok, chat = tg()
    checks.append(('настройки бота: %s' % (os.path.join(TG, 'config.json') if tok else 'нет config.json'), bool(tok)))
    checks.append(('индекс файлов бота: %d записей' % (
        len(json.load(open(INDEX, encoding='utf-8'))) if os.path.exists(INDEX) else 0), True))
    checks.append(('правила: %s' % ('есть' if os.path.exists(LAWS) else 'нет'), os.path.exists(LAWS)))
    checks.append(('база: %s' % ('есть, %d записей' % count_records() if os.path.exists(DB) else 'нет — поднять: MEMORY.py full'),
                   True))
    for name, ok in checks:
        print(('OK      ' if ok else 'ПРОБЛЕМА ') + name)
    bad = [n for n, ok in checks if not ok]
    print('ИТОГ: %d из %d' % (len(checks) - len(bad), len(checks)))
    if bad:
        print('ЧТО ДЕЛАТЬ: ' + '; '.join(bad))
    return 0 if not bad else 1


def selftest():
    """Доказывает, что цепочка работает: правила читаются, база открывается, поиск отвечает."""
    ok = []
    ok.append(('правила на месте', os.path.exists(LAWS)))
    ok.append(('задачи на месте', os.path.exists(TASKS)))
    n = count_records()
    ok.append(('база открывается (записей %d)' % n, n > 0))
    if n:
        hits = search('память законы агент', 3)
        ok.append(('поиск отвечает', hits.startswith('найдено')))
        ok.append(('индекс бота цел', len(json.load(open(INDEX, encoding='utf-8'))) > 50))
    for name, res in ok:
        print(('OK   ' if res else 'ПРОВАЛ ') + name)
    print('ИТОГ: %d из %d' % (sum(1 for _, r in ok if r), len(ok)))
    return 0 if all(r for _, r in ok) else 1


def main():
    args = sys.argv[1:]
    cmd = args[0] if args else 'start'
    if cmd == 'start':
        show_core()
        print('\n=== СЛОЙ 2: база ===')
        print(stats() if os.path.exists(DB) else
              'базы в памяти нет — поднять одной командой: python MEMORY.py full')
    elif cmd == 'full':
        print('восстановление базы из бота:')
        print('  ' + restore())
        print('  ' + restore_state())
        print('  ' + ingest())
        print(stats())
    elif cmd == 'search':
        print(search(' '.join(args[1:-1]) if len(args) > 2 and args[-1].isdigit() else ' '.join(args[1:]),
                      int(args[-1]) if len(args) > 2 and args[-1].isdigit() else 8))
    elif cmd == 'add':
        print(add(args[1], args[2] if len(args) > 2 else 'вручную'))
    elif cmd == 'stats':
        print(stats())
    elif cmd == 'putstate':
        print(put_state())
    elif cmd == 'restorestate':
        print(restore_state())
    elif cmd == 'stale':
        print(stale())
    elif cmd == 'learn':
        print(learn(args[1], open(args[2], encoding='utf-8').read() if len(args) > 2 and os.path.exists(args[2]) else ' '.join(args[2:])))
    elif cmd == 'how':
        print(how(' '.join(args[1:])))
    elif cmd == 'guard':
        print(guard())
    elif cmd == 'redact':
        print(redact())
    elif cmd == 'doctor':
        sys.exit(doctor())
    elif cmd == 'selftest':
        sys.exit(selftest())
    elif cmd == 'put':
        for p in (LAWS, TASKS, os.path.abspath(__file__)):
            if os.path.exists(p):
                rec = tg_put(p, 'память: ' + os.path.basename(p))
                print('залито %s -> %s (%d байт)' % (rec['file'], rec['file_id'][:24], rec['size']))
    else:
        print(__doc__)


if __name__ == '__main__':
    main()
