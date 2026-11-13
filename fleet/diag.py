#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ДИАГНОСТИКА: почему Арена отвечает «Something went wrong while generating».

Печатает профиль аккаунта, кредиты/лимиты, и перехватывает ответ сервера
на отправку сообщения (URL, статус, начало тела). Ничего не меняет.
"""
import asyncio
import json
import os
import pathlib
import subprocess
import sys
import urllib.request

os.environ.setdefault('PLAYWRIGHT_BROWSERS_PATH', os.path.expanduser('~/.cache/ms-playwright'))
if not list(pathlib.Path(os.environ['PLAYWRIGHT_BROWSERS_PATH']).glob('chromium-*/chrome-linux*/chrome')):
    subprocess.run([sys.executable, '-m', 'playwright', 'install', 'chromium'], check=False)

from playwright.async_api import async_playwright

SLOT = int(os.environ.get('SLOT', '1'))
ACC = ((SLOT - 1) % 10) + 1
UA = ('Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) '
      'Chrome/126.0.0.0 Safari/537.36')
EMAIL = os.environ.get('ARENA_EMAIL', '')
PASS = os.environ.get('ARENA_PASS', '')
if not EMAIL:
    _p = os.environ.get('A%02d' % ACC, '').strip()
    if ':' in _p:
        EMAIL, PASS = _p.split(':', 1)
    elif '|' in _p:
        EMAIL, PASS = _p.split('|', 1)
МОДЕЛЬ = os.environ.get('MODEL', 'muse-spark-1.3-xhigh')
ВОПРОС = os.environ.get('Q', 'Ответь одним словом: работает?')


def log(r):
    print(json.dumps(r, ensure_ascii=False), flush=True)


def sign_in(email, password, tries=3):
    last = None
    for i in range(tries):
        try:
            body = json.dumps({'email': email, 'password': password}).encode()
            r = urllib.request.Request('https://arena.ai/nextjs-api/sign-in/email', data=body, method='POST')
            for k, v in {'content-type': 'application/json', 'user-agent': UA,
                         'origin': 'https://arena.ai', 'referer': 'https://arena.ai/direct'}.items():
                r.add_header(k, v)
            with urllib.request.urlopen(r, timeout=45) as x:
                ck = []
                for c in x.headers.get_all('Set-Cookie') or []:
                    n, rest = c.split('=', 1)
                    ck.append((n, rest.split(';')[0]))
                payload = json.loads(x.read().decode())
            raw = ''.join(v for n, v in ck if n.startswith('arena-auth'))
            raw = raw[7:] if raw.startswith('base64-') else raw
            js = json.loads(base64.b64decode(raw + '=' * (-len(raw) % 4)).decode())
            return js.get('access_token', ''), [
                {'name': 'arena-auth-prod-v1.0', 'value': 'base64-' + raw[:len(raw) // 2],
                 'domain': 'arena.ai', 'path': '/'},
                {'name': 'arena-auth-prod-v1.1', 'value': raw[len(raw) // 2:],
                 'domain': 'arena.ai', 'path': '/'}], payload
        except Exception as e:
            last = e
            log({'event': 'sign_in_retry', 'err': str(e)[:120]})
    raise last


async def api(pg, path):
    return await pg.evaluate("""async (p) => {
        const r = await fetch(p, {headers:{'accept':'application/json'}});
        if (!r.ok) return {status:r.status, body: (await r.text()).slice(0,400)};
        const t = await r.text();
        try { return Object.assign({status:r.status}, JSON.parse(t)); }
        catch(e) { return {status:r.status, body:t.slice(0,400)}; }
    }""", path)


async def main():
    token, cookies, payload = sign_in(EMAIL, PASS)
    log({'event': 'sign_in', 'user': (payload.get('user') or {}).get('email')})
    log({'event': 'profile', 'payload': json.dumps(payload, ensure_ascii=False)[:1500]})
    async with async_playwright() as p:
        b = await p.chromium.launch(headless=True, args=['--no-sandbox', '--disable-dev-shm-usage'])
        ctx = await b.new_context(user_agent=UA, locale='en-US', viewport={'width': 1400, 'height': 900})
        await ctx.add_cookies(cookies)
        pg = await ctx.new_page()
        перехват = []

        async def ловить(resp):
            u = resp.url
            if 'arena.ai' not in u or 'analytics' in u or 'google' in u:
                return
            if not any(k in u for k in ('/api/', '/nextjs-api/', '/rpc/')):
                return
            тело = ''
            try:
                тело = (await resp.text())[:600]
            except Exception:
                pass
            перехват.append({'status': resp.status, 'url': u[:160], 'body': тело[:400]})

        pg.on('response', lambda r: asyncio.ensure_future(ловить(r)))
        await pg.goto('https://arena.ai/direct', wait_until='domcontentloaded', timeout=90000)
        for _ in range(40):
            await pg.wait_for_timeout(1500)
            if await pg.locator('textarea').count():
                break
            if await pg.get_by_role('button', name='Direct', exact=False).count():
                break
        await pg.wait_for_timeout(2500)
        к = pg.get_by_role('button', name='Direct', exact=False).first
        if await к.count():
            try:
                await к.click(timeout=8000)
                await pg.wait_for_timeout(3000)
            except Exception:
                pass
        for надпись in ('Max', 'Router', 'Select model'):
            b2 = pg.get_by_role('button', name=надпись, exact=False).first
            if await b2.count():
                try:
                    await b2.click(timeout=8000)
                    await pg.wait_for_timeout(2500)
                    break
                except Exception:
                    pass
        выбрана = False
        for e in await pg.query_selector_all('[role=option]'):
            t = (await e.inner_text()).strip().split('\n')[0].strip()
            if t == МОДЕЛЬ:
                await e.click(timeout=8000)
                выбрана = True
                break
        log({'event': 'model_pick', 'model': МОДЕЛЬ, 'ok': выбрана})
        await pg.wait_for_timeout(2000)
        for путь in ('/api/me', '/api/me/pulse', '/api/user/balance', '/api/credits',
                     '/api/history/unified?limit=3&includeArchived=false'):
            r = await api(pg, путь)
            log({'event': 'probe', 'path': путь, 'status': r.get('status'),
                 'body': json.dumps(r, ensure_ascii=False)[:700]})
        коробка = pg.locator('textarea').first
        await коробка.click(timeout=20000)
        await коробка.fill(ВОПРОС)
        await pg.wait_for_timeout(600)
        await коробка.press('Enter')
        for _ in range(12):
            await pg.wait_for_timeout(5000)
            текст = await pg.inner_text('body')
            if 'Something went wrong' in текст or len(текст) > 900:
                break
        for запись in перехват[-40:]:
            log({'event': 'http', **запись})
        await pg.screenshot(path='diag-%02d.png' % SLOT)
        await b.close()


asyncio.run(main())
