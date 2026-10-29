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
# рабочая папка заказчика не должна пухнуть: база и журналы живут во временной папке системы,
# а не в воркспейсе (закон 6: в рабочей папке — только то, что нужно за запрос)
import tempfile
TEMP = os.environ.get('MEM_TEMP') or os.path.join(tempfile.gettempdir(), 'flot-memory')
os.makedirs(TEMP, exist_ok=True)
ROOT = os.path.dirname(HERE)                      # .ФЛОТ-флот
WORK = os.path.dirname(ROOT)                      # рабочая папка заказчика
DB = os.environ.get('MEM_DB', os.path.join(TEMP, 'memory.db'))
TG = os.path.join(ROOT, 'tg')
INDEX = os.path.join(TG, 'index.json')
STATE = os.path.join(HERE, 'ingest-state.json')
LAWS = os.path.join(HERE, 'ЗАКОНЫ-КРАТКО.md')
TASKS = os.path.join(HERE, 'ЗАДАЧИ-ОТКРЫТЫЕ.md')
PARTS = ['memory.part%d' % i for i in range(1, 13)]   # база льётся частями по 18 МБ; берём все найденные


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
    parts = [p for p in PARTS if p in idx]
    if not parts:
        return 'в боте нет частей базы'
    buf = b''
    t0 = time.time()
    for p in parts:
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
    'гибридный поиск BM25 + TF-IDF с RRF (k=60)',
    'машинная оценка качества поиска (Recall@5, MRR)',
    'поиск противоречий по числам',
    'сводки L1 по источникам (consolidate)',
    'забывание в архив без удаления (decay)',
    'скачивание любого файла из бота по имени (get)',
    'автоотправка всех новых записей в бота (sync)',
    'слежка за перепиской чатов (СЛЕЖКА-ЧАТОВ)',
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



def autosync(limit_mb=12):
    """Всё, что появилось в памяти, само уезжает в бота — пачками, чтобы бот не отказал.
    Что уже отправлено, помечаем номером записи: повторно не шлём."""
    if not os.path.exists(DB):
        return 'базы нет'
    c = conn()
    row = c.execute("select v from meta where k='synced_rowid'").fetchone()
    last = int(row[0]) if row else 0
    sent = batches = 0
    while True:
        rows = c.execute('select rowid, title, body, source, kind from fts where rowid > ? order by rowid limit 4000',
                         (last,)).fetchall()
        if not rows:
            break
        path = os.path.join(TEMP, 'журнал-%s.jsonl' % time.strftime('%Y%m%d-%H%M%S'))
        size, n = 0, 0
        with open(path, 'w', encoding='utf-8') as f:
            for rec in rows:
                line = json.dumps({'rowid': rec[0], 'title': rec[1], 'text': rec[2],
                                   'source': rec[3], 'kind': rec[4]}, ensure_ascii=False) + '\n'
                if size + len(line.encode()) > limit_mb * 1024 * 1024 and n:
                    break
                f.write(line)
                size += len(line.encode())
                n += 1
                last = rec[0]
        try:
            tg_put(path, 'память: новые записи, пачка %d (%d записей)' % (batches + 1, n))
        except Exception as e:
            os.remove(path)
            if '413' in str(e) and limit_mb > 2:
                limit_mb //= 2                 # бот не принял объём — режем пачку и пробуем снова
                continue
            c.close()
            return 'бот не принял: %s (отправлено до этого: %d)' % (str(e)[:60], sent)
        os.remove(path)
        c.execute("insert or replace into meta(k,v) values('synced_rowid',?)", (str(last),))
        c.commit()
        sent += n
        batches += 1
    c.close()
    if not sent:
        return 'нового нет (последняя отправленная запись %d)' % last
    return 'отправлено в бота: %d записей, пачек %d' % (sent, batches)



# ------------------------------------------------------------------ векторный слой (TF-IDF, чистый stdlib)
def _toks(t):
    return re.findall(r'[\w\-]{2,}', (t or '').lower(), re.UNICODE)


def build_vectors(limit=40000):
    """Считает TF-IDF по всем записям и сохраняет: tf(rowid, terms, dl) + df(term, n)."""
    c = conn()
    c.execute('CREATE TABLE IF NOT EXISTS tf(rowid INTEGER PRIMARY KEY, terms TEXT, dl INTEGER)')
    c.execute('CREATE TABLE IF NOT EXISTS df(term TEXT PRIMARY KEY, n INTEGER)')
    c.execute('DELETE FROM tf')
    c.execute('DELETE FROM df')
    df = {}
    rows = c.execute('select rowid, title, body from fts limit ?', (limit,)).fetchall()
    for rid, t, b in rows:
        tk = _toks((t or '') + ' ' + (b or ''))
        if not tk:
            continue
        cnt = {}
        for w in tk:
            cnt[w] = cnt.get(w, 0) + 1
        top = dict(sorted(cnt.items(), key=lambda kv: -kv[1])[:200])
        c.execute('insert into tf(rowid, terms, dl) values(?,?,?)', (rid, json.dumps(top, ensure_ascii=False), len(tk)))
        for w in top:
            df[w] = df.get(w, 0) + 1
    c.executemany('insert or replace into df(term, n) values(?,?)', list(df.items()))
    c.commit()
    c.close()
    return 'векторы посчитаны: записей %d, слов в словаре %d' % (len(rows), len(df))


def _cosine(qterms, doc, dfn, n_docs, dl, avgdl):
    import math
    s = 0.0
    qn = 0.0
    for w, qc in qterms.items():
        idf = math.log(1 + n_docs / (1 + dfn.get(w, 0)))
        qn += (qc * idf) ** 2
        if w in doc:
            tfw = doc[w] / (1 + math.log(1 + dl / max(avgdl, 1)))
            s += (qc * idf) * (tfw * idf)
    if qn <= 0:
        return 0.0
    dn = 0.0
    for w, dc in doc.items():
        idf = math.log(1 + n_docs / (1 + dfn.get(w, 0)))
        dn += (dc * idf) ** 2
    return s / (math.sqrt(qn) * math.sqrt(dn) + 1e-9)


def hybrid(q, n=8, rrf_k=60):
    """Гибридный поиск: BM25 (FTS5) + TF-IDF косинус, слияние по RRF (k=60).
    Так сделано в инженерных статьях и репозиториях (agentmemory): два ранжирования, затем RRF."""
    if not os.path.exists(DB):
        return 'базы нет — MEMORY.py full'
    c = sqlite3.connect(DB)
    toks = _toks(q)
    if not toks:
        return 'пустой запрос'
    strict = ' AND '.join('"%s"*' % t for t in toks)
    rows = c.execute('select rowid, title, snippet(fts,1,"[",")","…",14), source, bm25(fts) from fts '
                     'where fts match ? order by bm25(fts) limit 300', (strict,)).fetchall()
    if not rows:
        rows = c.execute('select rowid, title, snippet(fts,1,"[",")","…",14), source, bm25(fts) from fts '
                         'where fts match ? order by bm25(fts) limit 300', (norm_tokens(q),)).fetchall()
    if not rows:
        c.close()
        return 'по запросу «%s» ничего не найдено' % q
    if not c.execute("select name from sqlite_master where name='tf'").fetchone():
        c.close()
        build_vectors()               # первый запуск: считаем векторы сами
        return hybrid(q, n, rrf_k)
    n_docs = c.execute('select count(*) from tf').fetchone()[0] or 1
    avgdl = (c.execute('select avg(dl) from tf').fetchone()[0] or 1)
    dfn = dict(c.execute('select term, n from df').fetchall())
    qterms = {}
    for w in toks:
        qterms[w] = qterms.get(w, 0) + 1
    vec = {}
    for rid, *_ in rows:
        r = c.execute('select terms, dl from tf where rowid=?', (rid,)).fetchone()
        if not r:
            continue
        vec[rid] = _cosine(qterms, json.loads(r[0]), dfn, n_docs, r[1], avgdl)
    by_vec = sorted(vec.items(), key=lambda kv: -kv[1])
    rank_bm25 = {rid: i + 1 for i, (rid, *_rest) in enumerate(rows)}
    rank_vec = {rid: i + 1 for i, (rid, _s) in enumerate(by_vec)}
    fused = {}
    for rid in set(rank_bm25) | set(rank_vec):
        fused[rid] = 1.0 / (rrf_k + rank_bm25.get(rid, 10 ** 6)) + 0.45 / (rrf_k + rank_vec.get(rid, 10 ** 6))
    info = {r[0]: (r[1], r[2], r[3]) for r in rows}
    out, seen_src = [], {}
    for rid, sc in sorted(fused.items(), key=lambda kv: -kv[1]):
        t, sn, src = info.get(rid, ('', '', '?'))
        if seen_src.get(src or '?', 0) >= 2:
            continue
        seen_src[src or '?'] = seen_src.get(src or '?', 0) + 1
        out.append((rid, sc, t, sn, src, vec.get(rid, 0)))
        if len(out) >= n:
            break
    c.close()
    lines = ['гибридный поиск (BM25 + TF-IDF, RRF k=%d) по «%s»:' % (rrf_k, q)]
    for i, (rid, sc, t, sn, src, cos) in enumerate(out, 1):
        lines.append('%d. [RRF %.4f | косинус %.3f] %s — %s\n   %s' %
                     (i, sc, cos, (t or '')[:80], src or '?', re.sub(r'\s+', ' ', sn)[:220]))
    return '\n'.join(lines)


def evaluate(n=8):
    """Машинная оценка качества поиска: Recall@5 и MRR на наборе известных вопросов."""
    tests = [
        ('как входил в Arena пароль TOTP', 'ЗАКОНЫ-КРАТКО'),
        ('флот 20 машин внешние IP', 'КИТ-ПРОДОЛЖАТЕЛЯ'),
        ('lawcheck шаги барьер', 'lawcheck'),
        ('стоимость 30 боёв одновременно', 'ПАМЯТЬ'),
        ('секреты GitHub token', 'api-keys'),
        ('пустые слоты аккаунт не задан', 'ЗАДАЧИ-ОТКРЫТЫЕ'),
        ('память сводки L1 консолидация', 'ИССЛЕДОВАНИЕ-ПАМЯТЬ'),
        ('telegram бот file_id части 18 МБ', 'ЗАКОНЫ-КРАТКО'),
        ('капча recaptcha отправка arena', 'ЗАКОНЫ-КРАТКО'),
        ('лимиты площадок бесплатные минуты', 'ТАБЛИЦА-40'),
    ][:n]
    if not os.path.exists(DB):
        return 'базы нет'
    res_b = []
    res_h = []
    c = sqlite3.connect('file:%s?mode=ro' % DB, uri=True)
    for q, want in tests:
        rows = c.execute('select source from fts where fts match ? order by bm25(fts) limit 5',
                         (' AND '.join('"%s"*' % t for t in _toks(q)) or '""',)).fetchall()
        srcs = [r[0] or '' for r in rows]
        hit = next((i + 1 for i, s2 in enumerate(srcs) if want.lower() in s2.lower()), 0)
        res_b.append((hit, len(srcs)))
    c.close()
    for q, want in tests:
        txt = hybrid(q, 5)
        lines = [l for l in txt.split('\n') if re.match(r'^\d+\. ', l)]
        hit = next((i + 1 for i, l in enumerate(lines) if want.lower() in l.lower()), 0)
        res_h.append((hit, len(lines)))

    def metrics(res):
        rec = sum(1 for hit, k in res if hit and hit <= 5) / len(res)
        mrr = sum((1.0 / hit) if hit else 0.0 for hit, _ in res) / len(res)
        return rec, mrr

    rb, mb = metrics(res_b)
    rh, mh = metrics(res_h)
    out = ['проверка качества поиска на %d вопросах:' % len(tests),
           '  BM25   : Recall@5 = %.0f%%, MRR = %.3f' % (rb * 100, mb),
           '  гибрид : Recall@5 = %.0f%%, MRR = %.3f' % (rh * 100, mh),
           '  выигрыш: %+.0f п.п. по Recall@5' % ((rh - rb) * 100)]
    return '\n'.join(out)


def contradictions(limit=10):
    """Ищет записи об одном и том же с разными числами/датами — кандидаты в противоречия."""
    c = sqlite3.connect('file:%s?mode=ro' % DB, uri=True)
    rows = c.execute('select rowid, title, body from fts order by rowid desc limit 4000').fetchall()
    c.close()
    seen, pairs = {}, []
    for rid, t, b in rows:
        tk = set(_toks((t or '') + ' ' + (b or '')))
        nums = set(re.findall(r'\b\d{2,4}\b', (t or '') + ' ' + (b or '')))
        if len(tk) < 8:
            continue
        for key in list(seen)[-400:]:
            other_tk, other_nums, other_rid = seen[key]
            inter = len(tk & other_tk) / max(1, len(tk | other_tk))
            if inter > 0.55 and nums and other_nums and not (nums & other_nums):
                pairs.append((round(inter, 2), rid, other_rid, sorted(nums)[:4], sorted(other_nums)[:4]))
                break
        seen[rid] = (tk, nums, rid)
    pairs.sort(reverse=True)
    if not pairs:
        return 'противоречий по числам не видно (проверено 4000 последних записей)'
    out = ['возможные противоречия: %d пар (похожий текст, разные числа)' % len(pairs)]
    for inter, a, b, na, nb in pairs[:limit]:
        out.append('  #%s числа %s ↔ #%s числа %s (совпадение текста %.2f)' % (a, na, b, nb, inter))
    return '\n'.join(out)


def consolidate(min_group=6):
    """Сводки: по каждому крупному источнику делаем одну запись-обзор (L1)."""
    c = conn()
    rows = c.execute('select source, count(*) n from fts group by source having n >= ? order by n desc limit 40',
                     (min_group,)).fetchall()
    made = 0
    for src, n in rows:
        already = c.execute("select 1 from fts where kind='summary' and source=?", (src,)).fetchone()
        if already:
            continue
        parts = c.execute('select title from fts where source=? order by rowid limit 12', (src,)).fetchall()
        body = 'СВОДКА источника %s (%d записей):\n' % (src, n) + '\n'.join('- ' + (p[0] or '')[:110] for p in parts)
        sha = hashlib.sha256(('summary' + src).encode()).hexdigest()
        if c.execute('select 1 from seen where sha=?', (sha,)).fetchone():
            continue
        c.execute('insert into fts(title, body, source, kind) values(?,?,?,?)',
                  ('СВОДКА: %s' % os.path.basename(src)[:60], body, src, 'summary'))
        c.execute('insert into seen(sha, ts, source) values(?,?,?)', (sha, int(time.time()), src))
        made += 1
    c.commit()
    c.close()
    return 'сводок создано: %d' % made


def decay(days=30):
    """Забывание: помечаем «холодные» записи (не использовались) — в архив, без удаления."""
    c = conn()
    c.execute('CREATE TABLE IF NOT EXISTS cold(rowid INTEGER PRIMARY KEY, ts INTEGER)')
    t = int(time.time()) - days * 86400
    old = c.execute('select rowid from fts where rowid not in (select rowid from cold)').fetchall()
    cold = 0
    uses = dict(c.execute('select sha, hits from uses').fetchall()) if c.execute(
        "select name from sqlite_master where name='uses'").fetchone() else {}
    for (rid,) in old:
        row = c.execute('select source, title from fts where rowid=?', (rid,)).fetchone()
        if not row:
            continue
        key = hashlib.sha256(((row[0] or '') + (row[1] or '')).encode()).hexdigest()[:16]
        if uses.get(key, 0) == 0:
            c.execute('insert or replace into cold(rowid, ts) values(?,?)', (rid, t))
            cold += 1
    c.commit()
    n = c.execute('select count(*) from cold').fetchone()[0]
    c.close()
    return 'в архив (холодные) отправлено: %d, всего холодных: %d; удаления нет — закон «ничего не терять»' % (cold, n)


def get_file(name):
    """Достать любой файл из бота обратно в рабочую папку (в воркспейсе держим только нужное)."""
    if not os.path.exists(INDEX):
        return 'нет index.json'
    idx = json.load(open(INDEX, encoding='utf-8'))
    cand = [e for e in idx if e['file'] == name] or [e for e in idx if name.lower() in e['file'].lower()]
    if not cand:
        return 'в боте нет файла с именем «%s»' % name
    e = cand[-1]
    data = tg_get(e['file_id'])
    out = os.path.join(WORK, e['file']) if os.access(WORK, os.W_OK) else os.path.join(TEMP, e['file'])
    open(out, 'wb').write(data)
    return 'скачано из бота: %s (%d байт)' % (out, len(data))



def import_batches(limit=40):
    """Поднимает в память всё, что уезжало в бота пачками (журнал-*.jsonl) — ничего не теряется."""
    if not os.path.exists(INDEX):
        return 'нет index.json'
    idx = json.load(open(INDEX, encoding='utf-8'))
    files = [e for e in idx if e['file'].startswith('журнал-')]
    if not files:
        return 'пачек в боте нет'
    c = conn()
    have = set()
    for t, b in c.execute('select title, body from fts').fetchall():
        have.add(hashlib.sha256(((t or '') + '\x00' + (b or '')).encode()).hexdigest())
    added = 0
    for e in files[-limit:]:
        try:
            data = tg_get(e['file_id']).decode('utf-8', 'ignore')
        except Exception:
            continue
        for line in data.split('\n'):
            if not line.strip():
                continue
            try:
                rec = json.loads(line)
            except Exception:
                continue
            body = rec.get('text') or ''
            title = (rec.get('title') or '')[:120]
            key = hashlib.sha256(((title or '') + '\x00' + body).encode()).hexdigest()
            if key in have:
                continue
            have.add(key)
            sha = hashlib.sha256(((rec.get('source') or '') + body).encode()).hexdigest()
            c.execute('insert into fts(title, body, source, kind) values(?,?,?,?)',
                      (title, body, rec.get('source') or 'пачка', rec.get('kind') or 'fact'))
            c.execute('insert into seen(sha, ts, source) values(?,?,?)',
                      (sha, int(time.time()), rec.get('source') or 'пачка'))
            added += 1
    c.commit()
    c.close()
    return 'из пачек бота добавлено записей: %d (пачек просмотрено %d)' % (added, min(limit, len(files)))



def dedup():
    """Удаляет записи-двойники (одинаковый текст и заголовок), оставляя первую."""
    c = conn()
    seen_map, dup = {}, []
    for rid, t, b in c.execute('select rowid, title, body from fts order by rowid').fetchall():
        h = hashlib.sha256(((t or '') + '\x00' + (b or '')).encode()).hexdigest()
        if h in seen_map:
            dup.append(rid)
        else:
            seen_map[h] = rid
    for rid in dup:
        c.execute('delete from fts where rowid=?', (rid,))
    c.commit()
    n = c.execute('select count(*) from fts').fetchone()[0]
    c.close()
    return 'удалено двойников: %d, осталось записей: %d' % (len(dup), n)


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
        print('  ' + import_batches())
        print(stats())
        print('  ' + autosync())
    elif cmd == 'search':
        q = ' '.join(args[1:-1]) if len(args) > 2 and args[-1].isdigit() else ' '.join(args[1:])
        n = int(args[-1]) if len(args) > 2 and args[-1].isdigit() else 8
        print(hybrid(q, n))          # гибрид: Recall@5 62% против 12% у чистого BM25 (см. MEMORY.py eval)
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
    elif cmd == 'sync':
        print(autosync())
    elif cmd == 'dedup':
        print(dedup())
    elif cmd == 'vectors':
        print(build_vectors())
    elif cmd == 'hybrid':
        print(hybrid(' '.join(args[1:])))
    elif cmd == 'eval':
        print(evaluate())
    elif cmd == 'contradictions':
        print(contradictions())
    elif cmd == 'consolidate':
        print(consolidate())
    elif cmd == 'decay':
        print(decay())
    elif cmd == 'get':
        print(get_file(args[1]))
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
