#!/usr/bin/env python3
"""СОВЕТ НА LM ARENA — не сторонние модели, а агенты самой Арены.

Одна машина = один аккаунт Арены = один руководитель совета.
Машина входит по почте/паролю, открывает arena.ai/text в браузере, отправляет
задание, забирает ответы моделей через /api/chat/<id>/messages и кладёт материал
в Telegram + JSON. Голосование и обмен — следующими раундами по этим файлам.

  SLOT=1 python3 council.py            # машина 1: аккаунт №01
  GOAL=3 SLOT=1 python3 council.py     # три задания с одной машины
"""
import asyncio
import base64
import json
import os
import random
import re
import urllib.request

os.environ.setdefault('PLAYWRIGHT_BROWSERS_PATH', '/home/user/.cache/ms-playwright')
import pathlib
import subprocess
import sys

if not list(pathlib.Path(os.environ['PLAYWRIGHT_BROWSERS_PATH']).glob('chromium-*/chrome-linux*/chrome')):
    subprocess.run([sys.executable, '-m', 'playwright', 'install', 'chromium'], check=False)

from playwright.async_api import async_playwright

SLOT = int(os.environ.get('SLOT', '1'))
GOAL = int(os.environ.get('GOAL', '1'))
TG_TOKEN = os.environ.get('TG_TOKEN', '')
TG_CHAT = os.environ.get('TG_CHAT', '7023156818')
UA = ('Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) '
      'Chrome/126.0.0.0 Safari/537.36')
ACC = ((SLOT - 1) % 10) + 1                      # 2 машины на аккаунт: 1..10, 11..20 -> 1..10
EMAIL = os.environ.get('ARENA_EMAIL', '')
PASS = os.environ.get('ARENA_PASS', '')
TASK = os.environ.get('TASK', '')                # задание совету
TITLE = os.environ.get('TASK_TAG', 'СОВЕТ')

LEADERS = ['стратег', 'инженер', 'критик', 'исследователь', 'практик',
           'архитектор', 'скептик', 'аналитик', 'методист', 'проверяющий']


def log(rec):
    print(json.dumps(rec, ensure_ascii=False), flush=True)


def push(text, click=''):
    if not TG_TOKEN:
        return
    try:
        data = {'chat_id': TG_CHAT, 'text': text[:3800], 'disable_web_page_preview': True}
        if click:
            data['reply_markup'] = json.dumps({'inline_keyboard': [[{'text': 'открыть диалог', 'url': click}]]})
        r = urllib.request.Request('https://api.telegram.org/bot%s/sendMessage' % TG_TOKEN,
                                   data=json.dumps(data).encode(), method='POST')
        r.add_header('Content-Type', 'application/json')
        urllib.request.urlopen(r, timeout=60).read()
    except Exception as e:
        log({'event': 'tg_error', 'msg': str(e)[:80]})


def sign_in(email, password):
    """Вход по почте/паролю без браузера: отдаёт cookie для браузера."""
    body = json.dumps({'email': email, 'password': password}).encode()
    r = urllib.request.Request('https://arena.ai/nextjs-api/sign-in/email', data=body, method='POST')
    for k, v in {'content-type': 'application/json', 'user-agent': UA,
                 'origin': 'https://arena.ai', 'referer': 'https://arena.ai/text'}.items():
        r.add_header(k, v)
    with urllib.request.urlopen(r, timeout=45) as x:
        raw = ''
        for c in x.headers.get_all('Set-Cookie') or []:
            name, rest = c.split('=', 1)
            if name == 'arena-auth-prod-v1.0':
                raw = rest.split(';')[0]
            if name == 'arena-auth-prod-v1.1':
                raw += rest.split(';')[0]
        payload = json.loads(x.read().decode())
    raw = raw[7:] if raw.startswith('base64-') else raw
    js = json.loads(base64.b64decode(raw + '=' * (-len(raw) % 4)).decode())
    cookies = [{'name': 'arena-auth-prod-v1.0', 'value': 'base64-' + raw[:len(raw) // 2], 'domain': 'arena.ai', 'path': '/'},
               {'name': 'arena-auth-prod-v1.1', 'value': raw[len(raw) // 2:], 'domain': 'arena.ai', 'path': '/'}]
    return js.get('access_token', ''), cookies, payload


def prompt_for(slot, leader):
    head = TASK.strip() or ('Как сделать так, чтобы ИИ-агент никогда не забывал законы заказчика и живые факты? '
                            'Нужны инженерные меры и машинные проверки.')
    return ('#%02d СОВЕТ/%s\n\n%s\n\nТы — %s в совете из 10 руководителей. Дай 5 конкретных мер, '
            'каждую с машинной проверкой, и укажи порядок внедрения. Без общих слов.' % (slot, leader, head, leader))


async def api(pg, path):
    return await pg.evaluate("""async (p) => {
        const r = await fetch(p, {headers:{'accept':'application/json'}});
        if (!r.ok) return {status:r.status, entries:[], data:[]};
        const j = await r.json(); j.status = r.status; return j;
    }""", path)


async def main():
    leader = LEADERS[(SLOT - 1) % len(LEADERS)]
    log({'event': 'start', 'slot': SLOT, 'account': '%02d' % ACC, 'leader': leader, 'goal': GOAL})
    token, cookies, payload = sign_in(EMAIL, PASS)
    log({'event': 'sign_in', 'user': (payload.get('user') or {}).get('email'), 'token': len(token)})
    async with async_playwright() as p:
        b = await p.chromium.launch(headless=True, args=['--no-sandbox', '--disable-dev-shm-usage',
                                                         '--disable-blink-features=AutomationControlled'])
        ctx = await b.new_context(locale='en-US', timezone_id='Europe/Moscow', user_agent=UA,
                                  viewport={'width': random.choice([1366, 1400, 1440]),
                                            'height': random.choice([768, 900])})
        await ctx.add_init_script("Object.defineProperty(navigator,'webdriver',{get:()=>undefined});")
        await ctx.add_cookies(cookies)
        pg = await ctx.new_page()
        stream_calls = []
        pg.on('request', lambda r: stream_calls.append((r.method, r.url, (r.post_data or '')[:300]))
              if '/nextjs-api/stream' in r.url else None)
        await pg.goto('https://arena.ai/text', wait_until='domcontentloaded', timeout=90000)
        await pg.wait_for_timeout(6000)
        me = await api(pg, '/api/me')
        log({'event': 'me', 'status': me.get('status'), 'user': (me.get('user') or {}).get('email')})
        if 'By clicking' in await pg.inner_text('body'):
            await pg.keyboard.press('Enter')
            await pg.wait_for_timeout(2500)
            log({'event': 'terms', 'closed': 'By clicking' not in await pg.inner_text('body')})
        base = {e.get('id') for e in (await api(pg, '/api/history/unified?limit=20&includeArchived=false')).get('entries', [])}
        made = 0
        for num in range(1, GOAL + 1):
            text = prompt_for(num, leader)
            box = pg.locator('textarea').first
            await box.click(timeout=25000)
            await box.fill(text)
            await pg.wait_for_timeout(700)
            await box.press('Enter')
            new = None
            for _ in range(15):
                await pg.wait_for_timeout(5000)
                ents = (await api(pg, '/api/history/unified?limit=20&includeArchived=false')).get('entries', [])
                new = [e for e in ents if e.get('id') not in base]
                if new:
                    break
            if not new:
                log({'event': 'no_dialog', 'num': num, 'stream_calls': len(stream_calls),
                     'hint': 'отправка не прошла', 'body': (await pg.inner_text('body'))[:200]})
                await pg.screenshot(path='fail-%02d.png' % SLOT)
                break
            for e in new:
                base.add(e['id'])
            e = new[0]
            did = e['id']
            link = 'https://arena.ai/c/%s' % did
            msgs = []
            for _ in range(8):
                await pg.wait_for_timeout(5000)
                got = await api(pg, '/api/chat/%s/messages?limit=50' % did)
                msgs = got.get('data') or got.get('messages') or []
                if len(msgs) >= 2:
                    break
            made += 1
            rec = {'slot': SLOT, 'account': '%02d' % ACC, 'leader': leader, 'num': num, 'dialog': did,
                   'link': link, 'title': (e.get('title') or '')[:80], 'messages': msgs}
            json.dump(rec, open('council-%02d-%02d.json' % (SLOT, num), 'w', encoding='utf-8'),
                      ensure_ascii=False, indent=1)
            answers = []
            for m in msgs:
                role = m.get('role') or m.get('author') or '?'
                content = m.get('content') or m.get('text') or ''
                if isinstance(content, list):
                    content = ' '.join(str(c.get('text', '')) if isinstance(c, dict) else str(c) for c in content)
                if role != 'user' and content:
                    answers.append(content)
            push('СОВЕТ #%02d | машина %02d | аккаунт %02d | %s\n%s\nответов моделей: %d\n\n%s' %
                 (num, SLOT, ACC, leader, link, len(answers),
                  '\n\n'.join(a[:1200] for a in answers[:2]) or 'ответов нет'), click=link)
            log({'event': 'collected', 'dialog': did, 'answers': len(answers), 'chars': sum(len(a) for a in answers),
                 'link': link})
            await pg.wait_for_timeout(random.randint(20, 45) * 1000)
        log({'event': 'finish', 'made': made, 'stream_calls': len(stream_calls)})
        await b.close()


if __name__ == '__main__':
    asyncio.run(main())
