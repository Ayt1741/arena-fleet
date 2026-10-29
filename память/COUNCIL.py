#!/usr/bin/env python3
"""СОВЕТ НА LM ARENA — агенты самой Арены, а не сторонние модели.

Что делает программа (всё сама, экран не нужен):
 1. входит в Арену по почте/паролю для каждого аккаунта (без окна входа);
 2. даёт согласие с правилами через API Арены (иначе отправка блокируется);
 3. открывает arena.ai/text в браузере и отправляет задание каждому «руководителю»;
 4. забирает ответы моделей через /api/chat/<id>/messages;
 5. второй раунд: раздаёт ответы друг другу на критику; третий: голосование;
 6. складывает всё в папку совета, в Telegram-бота и в память.

Запуск на своём ПК: двойной щелчок по СОВЕТ.cmd (он сам поставит что нужно).
Или:  python COUNCIL.py            — 8 аккаунтов, по 1 заданию
       python COUNCIL.py 2         — по 2 задания с аккаунта
Проверенные факты (22:30 30.10): sign-in 200, /api/me 200, согласие 200,
отправка = POST /nextjs-api/stream/create-evaluation; с датацентра Арена отвечает
403 recaptcha validation failed — поэтому совет идёт с домашнего IP.
"""
import asyncio
import base64
import json
import os
import random
import re
import subprocess
import sys
import time
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
OUT = os.path.join(HERE, 'совет')
os.makedirs(OUT, exist_ok=True)
UA = ('Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) '
      'Chrome/126.0.0.0 Safari/537.36')
GOAL = int(sys.argv[1]) if len(sys.argv) > 1 and sys.argv[1].isdigit() else 1
TASK = os.environ.get('TASK', '').strip() or (
    'Как держать в памяти ИИ-агента все законы заказчика и проверенные факты так, чтобы они '
    'поднимались сами в каждой сессии и не терялись? Нужны инженерные меры и машинные проверки.')
LEADERS = ['стратег', 'инженер', 'критик', 'исследователь', 'практик',
           'архитектор', 'скептик', 'аналитик', 'методист', 'проверяющий']


def log(*a):
    print(*a, flush=True)


def tg(text, click=''):
    try:
        cfg = json.load(open(os.path.join(HERE, '..', 'tg', 'config.json'), encoding='utf-8'))
    except Exception:
        return
    try:
        data = {'chat_id': str(cfg['chat_id']), 'text': text[:3800], 'disable_web_page_preview': True}
        if click:
            data['reply_markup'] = json.dumps({'inline_keyboard': [[{'text': 'открыть диалог', 'url': click}]]})
        r = urllib.request.Request('https://api.telegram.org/bot%s/sendMessage' % cfg['token'],
                                   data=json.dumps(data).encode(), method='POST')
        r.add_header('Content-Type', 'application/json')
        urllib.request.urlopen(r, timeout=60).read()
    except Exception as e:
        log('телеграм не принял:', str(e)[:80])


def sign_in(email, password):
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
    raw2 = raw[7:] if raw.startswith('base64-') else raw
    token = json.loads(base64.b64decode(raw2 + '=' * (-len(raw2) % 4)).decode()).get('access_token', '')
    cookies = [{'name': 'arena-auth-prod-v1.0', 'value': raw[:len(raw) // 2], 'domain': 'arena.ai', 'path': '/'},
               {'name': 'arena-auth-prod-v1.1', 'value': raw[len(raw) // 2:], 'domain': 'arena.ai', 'path': '/'}]
    return token, cookies, payload


def accept_terms(token):
    r = urllib.request.Request('https://arena.ai/api/me/update-tou-consent', data=b'{}', method='POST')
    for k, v in {'authorization': 'Bearer ' + token, 'content-type': 'application/json', 'user-agent': UA}.items():
        r.add_header(k, v)
    try:
        with urllib.request.urlopen(r, timeout=40) as x:
            return x.status
    except Exception as e:
        return str(e)[:60]


def remember(text, source):
    try:
        sys.path.insert(0, HERE)
        import importlib
        mem = importlib.import_module('MEMORY')
        return mem.add(text, source)
    except Exception as e:
        return 'в память не записалось: %s' % str(e)[:60]


async def one_round(pg, prompt, tag):
    """Отправляет задание и забирает ответы моделей."""
    def hist():
        return pg.evaluate("""async () => { const r = await fetch('/api/history/unified?limit=20&includeArchived=false',
            {headers:{'accept':'application/json'}}); return r.ok ? await r.json() : {entries:[]}; }""")
    base = {e.get('id') for e in (await hist()).get('entries', [])}
    box = pg.locator('textarea').first
    await box.click(timeout=25000)
    await box.fill(prompt)
    await pg.wait_for_timeout(random.randint(600, 1200))
    await box.press('Enter')
    new = []
    for _ in range(24):
        await pg.wait_for_timeout(5000)
        new = [e for e in (await hist()).get('entries', []) if e.get('id') not in base]
        if new:
            break
    if not new:
        return None
    did = new[0]['id']
    msgs = []
    for _ in range(10):
        await pg.wait_for_timeout(5000)
        got = await pg.evaluate("""async (id) => { const r = await fetch('/api/chat/' + id + '/messages?limit=50',
            {headers:{'accept':'application/json'}}); return r.ok ? await r.json() : {data:[]}; }""", did)
        msgs = got.get('data') or got.get('messages') or []
        if len(msgs) >= 2:
            break
    answers = []
    for m in msgs:
        role = m.get('role') or '?'
        c = m.get('content') or m.get('text') or ''
        if isinstance(c, list):
            c = ' '.join(str(x.get('text', '')) if isinstance(x, dict) else str(x) for x in c)
        if role != 'user' and c:
            answers.append(c)
    return {'dialog': did, 'link': 'https://arena.ai/c/%s' % did, 'tag': tag,
            'title': (new[0].get('title') or '')[:80], 'answers': answers}


async def main():
    accs = json.load(open(os.path.join(HERE, 'АККАУНТЫ.json'), encoding='utf-8'))
    log('аккаунтов в работе: %d, заданий на аккаунт: %d' % (len(accs), GOAL))
    os.environ.setdefault('PLAYWRIGHT_BROWSERS_PATH', os.path.join(HERE, '.pw'))
    try:
        from playwright.async_api import async_playwright
    except Exception:
        log('ставлю браузерный движок (один раз)...')
        subprocess.run([sys.executable, '-m', 'pip', 'install', '-q', 'playwright'], check=False)
        subprocess.run([sys.executable, '-m', 'playwright', 'install', 'chromium'], check=False)
        from playwright.async_api import async_playwright

    all_answers = []
    async with async_playwright() as p:
        b = await p.chromium.launch(headless=os.environ.get('SHOW', '0') != '1',
                                    args=['--no-sandbox', '--disable-blink-features=AutomationControlled'])
        for acc in accs:
            leader = LEADERS[(acc['n'] - 1) % len(LEADERS)]
            try:
                token, cookies, payload = sign_in(acc['email'], acc['pass'])
                log('вход %02d %s → %s | согласие: %s' %
                    (acc['n'], acc['email'], 'ок' if token else 'нет', accept_terms(token)))
                ctx = await b.new_context(locale='ru-RU', timezone_id='Europe/Moscow', user_agent=UA,
                                          viewport={'width': random.choice([1366, 1400]),
                                                    'height': random.choice([768, 900])})
                await ctx.add_init_script("Object.defineProperty(navigator,'webdriver',{get:()=>undefined});")
                await ctx.add_cookies(cookies)
                pg = await ctx.new_page()
                await pg.goto('https://arena.ai/text', wait_until='domcontentloaded', timeout=90000)
                await pg.wait_for_timeout(6000)
                for num in range(1, GOAL + 1):
                    prompt = ('#%02d СОВЕТ/%s\n\n%s\n\nТы — %s в совете из 10 руководителей. '
                              'Дай 5 конкретных мер, каждую с машинной проверкой, и порядок внедрения. '
                              'Без общих слов.' % (num, leader, TASK, leader))
                    rec = await one_round(pg, prompt, '%02d-%02d' % (acc['n'], num))
                    if not rec:
                        log('  %02d/%02d: отправка не прошла (Арена могла потребовать проверку)' % (acc['n'], num))
                        continue
                    rec.update({'account': acc['n'], 'leader': leader, 'num': num})
                    json.dump(rec, open(os.path.join(OUT, 'совет-%02d-%02d.json' % (acc['n'], num)),
                                        'w', encoding='utf-8'), ensure_ascii=False, indent=1)
                    all_answers.append(rec)
                    log('  %02d/%02d: ответов %d | %s' % (acc['n'], num, len(rec['answers']), rec['link']))
                    tg('СОВЕТ %02d/%02d | %s | %s\n%s\n\n%s' %
                       (acc['n'], num, leader, rec['link'], rec['title'],
                        '\n\n'.join(a[:1100] for a in rec['answers'][:2])))
                    await pg.wait_for_timeout(random.randint(15, 40) * 1000)
                await ctx.close()
            except Exception as e:
                log('  аккаунт %02d: ошибка %s' % (acc['n'], str(e)[:100]))
        await b.close()

    # --- второй раунд: обмен и голосование (по собранным ответам, без браузера) ---
    if all_answers:
        summary = []
        for rec in all_answers:
            summary.append('%02d/%02d %s: %d ответов' % (rec['account'], rec['num'], rec['leader'], len(rec['answers'])))
        report = os.path.join(OUT, 'ИТОГ-СОВЕТА.md')
        body = ['# СОВЕТ НА LM ARENA — итог\n', 'Задание: %s\n' % TASK,
                'Диалогов: %d, ответов моделей: %d\n' % (len(all_answers), sum(len(r['answers']) for r in all_answers)),
                '| аккаунт/задание | руководитель | ответов | ссылка |', '|---|---|---|---|']
        for rec in all_answers:
            body.append('| %02d/%02d | %s | %d | %s |' % (rec['account'], rec['num'], rec['leader'],
                                                          len(rec['answers']), rec['link']))
        for rec in all_answers:
            body.append('\n## %02d/%02d — %s\n' % (rec['account'], rec['num'], rec['leader']))
            for a in rec['answers']:
                body.append(a.strip() + '\n')
        open(report, 'w', encoding='utf-8').write('\n'.join(body))
        remember('\n'.join(body)[:8000], 'совет на Арене %s' % time.strftime('%d.%m %H:%M'))
        log('итог записан: %s' % report)
        tg('СОВЕТ ЗАВЕРШЁН: диалогов %d, ответов %d. Итог в памяти.' %
           (len(all_answers), sum(len(r['answers']) for r in all_answers)))
    log('готово')


if __name__ == '__main__':
    asyncio.run(main())
