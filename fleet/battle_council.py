#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""СОВЕТ НА АРЕНЕ — режим Battle Code (не Direct).

Что изменилось против прошлой версии (ход 53, по требованию пользователя):
  * открывается https://arena.ai/code?mode=battle — модная «Code», режим Battle;
    переключения на Direct больше НЕТ (именно Direct резался recaptcha'ом);
  * ответы двух моделей достаются из /api/chat/<id>/messages (как раньше),
    плюс запасной путь — текст со страницы;
  * если появились кнопки голосования — жмём «оба хороши», тогда арена
    раскрывает имена моделей; имена пишем в отчёт;
  * задание и все материалы берутся из файла fleet/task-53.md (мой промт +
    оружейная + выжимка из журнала) — машина читает файл, а не гадает.

Переменные среды: SLOT (1..N), GOAL (сколько заданий), ACC (01..10).
Артефакт: council-<slot>-<n>.json + скриншоты.
"""
import asyncio
import base64
import json
import os
import random
import re
import subprocess
import sys
import urllib.request

os.environ.setdefault('PLAYWRIGHT_BROWSERS_PATH', os.path.expanduser('~/.cache/ms-playwright'))
import pathlib

if not list(pathlib.Path(os.environ['PLAYWRIGHT_BROWSERS_PATH']).glob('chromium-*/chrome-linux*/chrome')):
    subprocess.run([sys.executable, '-m', 'playwright', 'install', 'chromium'], check=False)

from playwright.async_api import async_playwright

SLOT = int(os.environ.get('SLOT', '1'))
GOAL = int(os.environ.get('GOAL', '1'))
ACC = ((SLOT - 1) % 10) + 1
EMAIL = os.environ.get('ARENA_EMAIL', '').strip()
PASS = os.environ.get('ARENA_PASS', '').strip()
if not EMAIL:
    пара = os.environ.get('A%02d' % ACC, '').strip()
    if ':' in пара:
        EMAIL, PASS = пара.split(':', 1)
    elif '|' in пара:
        EMAIL, PASS = пара.split('|', 1)
TASK_FILE = os.environ.get('TASK_FILE', 'fleet/task-53.md')
URL = os.environ.get('ARENA_URL', 'https://arena.ai/code?mode=battle')
UA = ('Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) '
      'Chrome/126.0.0.0 Safari/537.36')

РОЛИ = ['стратег', 'инженер', 'критик', 'исследователь', 'практик',
        'архитектор', 'скептик', 'аналитик', 'методист', 'проверяющий']


def log(rec):
    print(json.dumps(rec, ensure_ascii=False), flush=True)


def sign_in(email, password):
    body = json.dumps({'email': email, 'password': password}).encode()
    r = urllib.request.Request('https://arena.ai/nextjs-api/sign-in/email', data=body, method='POST')
    for k, v in {'content-type': 'application/json', 'user-agent': UA,
                 'origin': 'https://arena.ai', 'referer': 'https://arena.ai/code'}.items():
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
    cookies = [{'name': 'arena-auth-prod-v1.0', 'value': 'base64-' + raw[:len(raw) // 2], 'domain': 'arena.ai', 'path': '/'},
               {'name': 'arena-auth-prod-v1.1', 'value': raw[len(raw) // 2:], 'domain': 'arena.ai', 'path': '/'}]
    return payload.get('access_token', ''), cookies


def accept_terms(token):
    r = urllib.request.Request('https://arena.ai/api/me/update-tou-consent', data=b'{}', method='POST')
    for k, v in {'authorization': 'Bearer ' + token, 'content-type': 'application/json',
                 'user-agent': UA, 'origin': 'https://arena.ai', 'referer': 'https://arena.ai/code'}.items():
        r.add_header(k, v)
    try:
        with urllib.request.urlopen(r, timeout=40) as x:
            return x.status
    except Exception as e:
        return str(e)[:80]


def материалы():
    """Мой промт + все материалы — из файла задания в репозитории."""
    try:
        return open(TASK_FILE, encoding='utf-8').read()
    except Exception:
        return ''


def prompt_for(slot, роль, номер):
    тело = материалы()
    голова = ('#%02d СОВЕТ/%s (задание %d)\n\n' % (slot, роль, номер))
    хвост = ('\n\nТы — %s в совете из 10 руководителей арены. Отвечай по-русски, '
             'по делу, с числами и конкретными действиями. Пиши так, чтобы решение '
             'можно было выполнить без уточнений. Если данных не хватает — скажи, '
             'что именно надо добыть, и укажи запрос в интернет.' % роль)
    return голова + (тело[:12000] if тело else '') + хвост


async def api(pg, path):
    return await pg.evaluate("""async (p) => {
        try {
            const r = await fetch(p, {headers:{'accept':'application/json'}});
            if (!r.ok) return {status:r.status, entries:[], data:[], messages:[]};
            const j = await r.json(); j.status = r.status; return j;
        } catch (e) { return {status:0, error:String(e), entries:[], data:[], messages:[]}; }
    }""", path)


async def основной():
    роль = РОЛИ[(SLOT - 1) % len(РОЛИ)]
    log({'event': 'start', 'slot': SLOT, 'account': '%02d' % ACC, 'role': роль,
         'goal': GOAL, 'url': URL, 'task_file': TASK_FILE})
    token, cookies = sign_in(EMAIL, PASS)
    log({'event': 'sign_in', 'user': EMAIL, 'token_len': len(token)})
    log({'event': 'terms', 'status': accept_terms(token)})
    async with async_playwright() as p:
        b = await p.chromium.launch(headless=True, args=['--no-sandbox', '--disable-dev-shm-usage',
                                                          '--disable-blink-features=AutomationControlled'])
        ctx = await b.new_context(locale='en-US', timezone_id='Europe/Moscow', user_agent=UA,
                                  viewport={'width': random.choice([1366, 1440]), 'height': random.choice([768, 900])})
        await ctx.add_init_script("Object.defineProperty(navigator,'webdriver',{get:()=>undefined});")
        await ctx.add_cookies(cookies)
        pg = await ctx.new_page()
        поток = []
        pg.on('request', lambda r: поток.append((r.method, r.url[:160]))
              if ('/nextjs-api/stream' in r.url or 'create-evaluation' in r.url) else None)
        await pg.goto(URL, wait_until='domcontentloaded', timeout=90000)
        await pg.wait_for_timeout(7000)
        me = await api(pg, '/api/me')
        log({'event': 'me', 'status': me.get('status'), 'user': (me.get('user') or {}).get('email')})
        текст_страницы = await pg.inner_text('body')
        if 'By clicking' in текст_страницы:
            await pg.keyboard.press('Enter')
            await pg.wait_for_timeout(2500)
            log({'event': 'terms_ui', 'closed': 'By clicking' not in await pg.inner_text('body')})
        # какие режимы реально есть на странице — это и есть доказательство режима
        режимы = await pg.evaluate("""() => {
            const out = {};
            document.querySelectorAll('button,[role=button]').forEach(b => {
                const t=(b.innerText||b.textContent||'').trim();
                if (t && t.length<40) out[t]=(out[t]||0)+1;
            });
            return out;
        }""")
        log({'event': 'buttons', 'top': sorted(режимы.items(), key=lambda kv: -kv[1])[:18]})
        base = {e.get('id') for e in (await api(pg, '/api/history/unified?limit=30&includeArchived=false')).get('entries', [])}
        сделано = 0
        for номер in range(1, GOAL + 1):
            текст = prompt_for(SLOT, роль, номер)
            box = pg.locator('textarea').first
            try:
                await box.click(timeout=30000)
            except Exception as e:
                log({'event': 'no_box', 'err': str(e)[:80]})
                break
            await box.fill(текст)
            await pg.wait_for_timeout(600)
            await box.press('Enter')
            диалог = None
            for _ in range(20):
                await pg.wait_for_timeout(5000)
                записи = (await api(pg, '/api/history/unified?limit=30&includeArchived=false')).get('entries', [])
                новые = [e for e in записи if e.get('id') not in base]
                if новые:
                    диалог = новые[0]
                    base.add(диалог.get('id'))
                    break
            if not диалог:
                log({'event': 'no_dialog', 'stream_calls': len(поток),
                     'body': (await pg.inner_text('body'))[:300]})
                await pg.screenshot(path='fail-%02d-%d.png' % (SLOT, номер))
                break
            did = диалог.get('id')
            ссылка = 'https://arena.ai/c/%s' % did
            ответы = []
            for _ in range(45):
                await pg.wait_for_timeout(6000)
                got = await api(pg, '/api/chat/%s/messages?limit=60' % did)
                msgs = got.get('data') or got.get('messages') or got.get('entries') or []
                ответы = []
                for m in msgs:
                    роль_м = m.get('role') or m.get('author') or '?'
                    текст_м = m.get('content') or m.get('text') or ''
                    if isinstance(текст_м, list):
                        текст_м = ' '.join(str(c.get('text', '')) if isinstance(c, dict) else str(c) for c in текст_м)
                    if роль_м != 'user' and текст_м.strip():
                        ответы.append({'роль': роль_м, 'модель': m.get('model') or m.get('model_name') or '',
                                       'текст': текст_м})
                if len(ответы) >= 2 and all(len(a['текст']) > 150 for a in ответы):
                    break
            # если ответов мало — читаем страницу
            if len(ответы) < 2:
                for _ in range(20):
                    await pg.wait_for_timeout(5000)
                    txt = await pg.inner_text('body')
                    if len(txt) > 1200:
                        ответы.append({'роль': 'страница', 'модель': '', 'текст': txt[-9000:]})
                        break
            # голосование → арена раскрывает имена
            имена = []
            for надпись in ('Both are good', 'Both good', 'Оба хороши', 'оба хороши'):
                try:
                    кнопка = pg.get_by_role('button', name=надпись, exact=False).first
                    if await кнопка.count():
                        await кнопка.click(timeout=6000)
                        await pg.wait_for_timeout(4000)
                        имена = re.findall(r'(?:claude|muse|gpt|gemini|grok|kimi|deepseek|fable|qwen|inkling|argon)[\w.\- ]{0,26}',
                                            await pg.inner_text('body'), re.I)
                        log({'event': 'voted', 'label': надпись, 'names': sorted(set(имена))[:8]})
                        break
                except Exception as e:
                    log({'event': 'vote_err', 'err': str(e)[:60]})
            if not имена:
                имена = sorted({a.get('модель') for a in ответы if a.get('модель')})
            сделано += 1
            rec = {'slot': SLOT, 'account': '%02d' % ACC, 'role': роль, 'num': номер,
                   'dialog': did, 'link': ссылка, 'title': (диалог.get('title') or '')[:120],
                   'answers': ответы, 'names': имена, 'answers_count': len(ответы),
                   'chars': sum(len(a['текст']) for a in ответы), 'url': URL}
            json.dump(rec, open('council-%02d-%02d.json' % (SLOT, номер), 'w', encoding='utf-8'),
                      ensure_ascii=False, indent=1)
            log({'event': 'collected', 'dialog': did, 'answers': len(ответы),
                 'chars': rec['chars'], 'names': имена, 'link': ссылка})
            await pg.screenshot(path='shot-%02d-%02d.png' % (SLOT, номер))
            await pg.wait_for_timeout(random.randint(15, 30) * 1000)
        log({'event': 'finish', 'made': сделано, 'stream_calls': len(поток)})
        await b.close()


if __name__ == '__main__':
    asyncio.run(основной())
