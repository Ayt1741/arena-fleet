#!/usr/bin/env python3
"""Воркер флота: один GitHub-раннер = одна виртуальная машина со своим IP.

Что делает:
1) подставляет cookie аккаунта и проверяет вход (`/api/me` = 200);
2) делает бои в Arena: диалоги нумеруются (#01, #02, ...);
3) каждому созданному бою присылает уведомление с ПРЯМОЙ ссылкой на диалог;
4) при окне проверки (капче) — уведомление с аккаунтом и ссылкой, ждёт `CAPTCHA_WAIT` секунд;
5) пишет результат в `result-<TAG>.jsonl` (артефакт GitHub).

Анти-детект (без денег): подмена webdriver/плагинов/языков/WebGL, шум в canvas,
свой UA, экран и часовой пояс на каждый запуск.

Переменные среды:
  ARENA_COOKIE  — значение cookie arena-auth-prod-v1 (обязательно)
  ACCOUNT       — имя аккаунта для уведомлений (например acc-3)
  GOAL          — сколько боёв сделать (по умолчанию 12)
  PROMPT        — текст задания
  TAG           — метка шарда (S01..S20)
  NTFY_TOPIC    — тема ntfy для уведомлений
  PAUSE         — пауза между боями, с (по умолчанию 120)
  CAPTCHA_WAIT  — сколько ждать решения капчи, с (по умолчанию 300; на раннере кликнуть некому)
  DRY           — 1 = только вход и проверка, без боёв
"""
import os
import sys
import json
import time
import random
import asyncio
import pathlib
import subprocess
import urllib.request

ACCOUNT = os.environ.get('ACCOUNT', 'acc')
GOAL = int(os.environ.get('GOAL', '12'))
PROMPT = os.environ.get('PROMPT', 'По документу: перечисли 5 этапов внедрения, коротко и по делу.')
TAG = os.environ.get('TAG', 'S00')
NTFY = os.environ.get('NTFY_TOPIC', '')
PAUSE = int(os.environ.get('PAUSE', '120'))
CAPTCHA_WAIT = int(os.environ.get('CAPTCHA_WAIT', '300'))
DRY = os.environ.get('DRY', '0') == '1'
OUT = pathlib.Path('result-%s.jsonl' % TAG)

_roots = ['/root/.cache/ms-playwright', '/home/user/.cache/ms-playwright']
if not any(list(pathlib.Path(r).glob('chromium-*/chrome-linux*/chrome')) for r in _roots):
    subprocess.run([sys.executable, '-m', 'playwright', 'install', '--with-deps', 'chromium'], check=False)

from playwright.async_api import async_playwright

UAS = [
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36',
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/127.0.0.0 Safari/537.36',
    'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36',
    'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36',
]

# --- анти-детект: то, что обычно выдаёт робота ---
STEALTH = r"""
Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
Object.defineProperty(navigator, 'languages', {get: () => ['ru-RU','ru','en-US','en']});
Object.defineProperty(navigator, 'hardwareConcurrency', {get: () => %d});
Object.defineProperty(navigator, 'deviceMemory', {get: () => %d});
window.chrome = window.chrome || {runtime: {}};
const origQuery = window.navigator.permissions.query;
window.navigator.permissions.query = (p) => (p.name === 'notifications')
  ? Promise.resolve({state: Notification.permission}) : origQuery(p);
const getParameter = WebGLRenderingContext.prototype.getParameter;
WebGLRenderingContext.prototype.getParameter = function (p) {
  if (p === 37445) return 'Intel Inc.';
  if (p === 37446) return 'Intel Iris OpenGL Engine';
  return getParameter.apply(this, [p]);
};
const toBlob = HTMLCanvasElement.prototype.toBlob;
const toDataURL = HTMLCanvasElement.prototype.toDataURL;
const noise = %d;
HTMLCanvasElement.prototype.toDataURL = function () {
  const ctx = this.getContext('2d');
  if (ctx) { const d = ctx.getImageData(0, 0, Math.min(10, this.width), Math.min(10, this.height));
    for (let i = 0; i < d.data.length; i += 97) d.data[i] = (d.data[i] + noise) %% 256;
    ctx.putImageData(d, 0, 0); }
  return toDataURL.apply(this, arguments);
};
"""


def log(rec):
    rec.update(ts=int(time.time()), iso=time.strftime('%H:%M:%S'), acc=ACCOUNT, tag=TAG)
    with open(OUT, 'a', encoding='utf-8') as f:
        f.write(json.dumps(rec, ensure_ascii=False) + '\n')
    print(json.dumps(rec, ensure_ascii=False), flush=True)


def push(title, text, click=None, priority='urgent'):
    if not NTFY:
        return
    try:
        req = urllib.request.Request('https://ntfy.sh/' + NTFY, data=text.encode('utf-8'), method='POST')
        req.add_header('Title', title.encode('ascii', 'replace').decode('ascii'))
        req.add_header('Priority', priority)
        req.add_header('Tags', 'rotating_light')
        if click:
            req.add_header('Click', click)
        urllib.request.urlopen(req, timeout=15).read()
    except Exception as e:
        log({'event': 'notify_fail', 'err': str(e)[:100]})


def cookies_from_env():
    raw = os.environ.get('ARENA_COOKIE', '').strip()
    if not raw:
        raise SystemExit('нет ARENA_COOKIE')
    # Chromium не принимает cookie длиннее 4096 — режем на два куска
    return [
        {'name': 'arena-auth-prod-v1.0', 'value': raw[:3000], 'domain': '.arena.ai', 'path': '/',
         'secure': True, 'httpOnly': True, 'sameSite': 'Lax'},
        {'name': 'arena-auth-prod-v1.1', 'value': raw[3000:], 'domain': '.arena.ai', 'path': '/',
         'secure': True, 'httpOnly': True, 'sameSite': 'Lax'},
    ]


async def api(pg, path):
    return await pg.evaluate("""async (p) => {
        const r = await fetch(p, {headers: {accept: 'application/json'}});
        if (!r.ok) return {status: r.status, entries: []};
        const j = await r.json();
        return {status: r.status, entries: (j.entries || j.history || [])};
    }""", path)


async def challenge_on(pg):
    try:
        txt = await pg.inner_text('body')
        return ('Security Verification' in txt) or ('Verify you are human' in txt) \
            or await pg.locator('#challenge-form').count() > 0
    except Exception:
        return False


async def main():
    ck = cookies_from_env()
    ua = random.choice(UAS)
    tz = random.choice(['Europe/Moscow', 'Europe/Berlin', 'Asia/Almaty'])
    async with async_playwright() as p:
        b = await p.chromium.launch(headless=True, args=[
            '--no-sandbox', '--disable-dev-shm-usage', '--disable-blink-features=AutomationControlled',
            '--disable-features=IsolateOrigins,site-per-process'])
        ctx = await b.new_context(user_agent=ua, locale='ru-RU', timezone_id=tz,
                                  viewport={'width': random.choice([1366, 1440, 1536]),
                                            'height': random.choice([768, 864, 900])})
        await ctx.add_init_script(STEALTH % (random.choice([4, 8, 12]), random.choice([8, 16]),
                                            random.randint(1, 250)))
        await ctx.add_cookies(ck)
        pg = await ctx.new_page()
        await pg.goto('https://arena.ai/text', wait_until='domcontentloaded', timeout=90000)
        await pg.wait_for_timeout(5000)
        me = (await api(pg, '/api/me'))['status']
        log({'event': 'start', 'me': me, 'goal': GOAL, 'ua': ua[-40:], 'tz': tz, 'dry': DRY})
        if me != 200:
            push('Arena: вход не прошёл', 'Аккаунт: %s\n/api/me = %s\nНужна свежая cookie.' % (ACCOUNT, me))
            await b.close()
            return
        if DRY:
            log({'event': 'dry_ok'})
            await b.close()
            return

        seen = {e.get('id') for e in (await api(pg, '/api/history/unified?limit=20&includeArchived=false'))['entries']}
        made, num = 0, 1
        while made < GOAL:
            try:
                await pg.goto('https://arena.ai/text', wait_until='domcontentloaded', timeout=90000)
                await pg.wait_for_timeout(4000)
                if await challenge_on(pg):
                    push('Arena: нужна КАПЧА',
                         'Аккаунт: %s\nДиалог: #%02d\nРаннер %s не может кликнуть сам.\n'
                         'Время: %d мин' % (ACCOUNT, num, TAG, CAPTCHA_WAIT // 60),
                         click='https://arena.ai/text')
                    t0 = time.time()
                    while time.time() - t0 < CAPTCHA_WAIT:
                        await pg.wait_for_timeout(5000)
                        if not await challenge_on(pg):
                            break
                box = pg.locator('textarea').first
                await box.click(timeout=25000)
                await pg.keyboard.type('#%02d ' % num, delay=25)
                await box.fill('#%02d %s' % (num, PROMPT))
                await pg.wait_for_timeout(700)
                await box.press('Enter')
                ok, link = False, None
                for _ in range(20):
                    await pg.wait_for_timeout(5000)
                    entries = (await api(pg, '/api/history/unified?limit=20&includeArchived=false'))['entries']
                    new = [e for e in entries if e.get('id') not in seen]
                    if new:
                        for e in new:
                            seen.add(e['id'])
                            made += 1
                            link = 'https://arena.ai/c/%s' % e['id']
                            log({'event': 'battle', 'dialog': '%02d' % num, 'id': e['id'],
                                 'title': (e.get('title') or '')[:60], 'link': link, 'made': made})
                        ok, num = True, num + 1
                        break
                if ok:
                    push('Arena: бой готов', 'Аккаунт: %s\nДиалог: #%02d\n%s\nВсего: %d/%d'
                         % (ACCOUNT, num - 1, link, made, GOAL), click=link, priority='low')
                await pg.wait_for_timeout(random.randint(PAUSE, PAUSE + 60) * 1000)
            except Exception as e:
                log({'event': 'error', 'dialog': num, 'msg': str(e)[:140]})
                await pg.wait_for_timeout(random.randint(180, 300) * 1000)
        # сохраняем обновлённую сервером cookie: сессия «поворачивается», старая пара умирает
        try:
            live = [c for c in await ctx.cookies() if c['name'].startswith('arena-auth-prod-v1')]
            if live:
                val = ''.join(c['value'] for c in sorted(live, key=lambda x: x['name']))
                pathlib.Path('cookies-%s.txt' % TAG).write_text(val)
                log({'event': 'cookie_saved', 'len': len(val), 'note': 'взять из артефакта, если нужен повтор'})
        except Exception:
            pass
        log({'event': 'finish', 'made': made})
        await b.close()

asyncio.run(main())
