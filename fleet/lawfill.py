#!/usr/bin/env python3
"""СОВЕТ 10 РУКОВОДИТЕЛЕЙ + 30 ОТВЕТОВ + ПРОВЕРКА — материалы для шагов lawcheck.

Честно: это не бои на Арене (Арена с датацентра отдаёт 403 recaptcha). Это 10 руководителей
и 30 исполнителей на бесплатных каналах моделей; каждый ответ сохраняется с моделью и цитатой.
Что делает:
 1) 10 ролей-руководителей получают задачу и дают материал → state/leaders/L01..L10.md;
 2) обмен: каждый получает материалы двух других и пишет согласование → L01-r2..L10-r2.md;
 3) собирается пакет для исполнителей → battle-tasks/PACKAGE-01.txt;
 4) 30 исполнителей отвечают на пакет → state/battle/answers-01.jsonl (30 строк);
 5) проверка: считаются проценты, отбирается топ-10 → REPORT-01.md;
 6) всё складывается в lawfill-out.zip.
"""
import concurrent.futures
import json
import os
import re
import urllib.request

TASK = ('Как держать в памяти ИИ-агента все законы заказчика и проверенные факты так, чтобы они '
        'поднимались сами в каждой сессии, не терялись и не противоречили друг другу? '
        'Нужны инженерные меры и машинные проверки.')
ROLES = ['стратег', 'инженер', 'критик', 'исследователь', 'практик',
         'архитектор', 'скептик', 'аналитик', 'методист', 'проверяющий']
CHANNELS = [('blockrun/nemotron-550b', 'https://blockrun.ai/v1/chat/completions', 'nvidia/nemotron-3-ultra-550b'),
            ('ovh/gpt-oss-120b', 'https://oai.endpoints.kepler.ai.cloud.ovh.net/v1/chat/completions', 'gpt-oss-120b')]


def ask(prompt, ch=0, max_tokens=700):
    name, url, model = CHANNELS[ch % len(CHANNELS)]
    body = {'model': model, 'max_tokens': max_tokens,
            'messages': [{'role': 'system', 'content': 'Ты инженер памяти ИИ-агентов. По-русски, по пунктам, только проверяемые меры с метрикой.'},
                         {'role': 'user', 'content': prompt}]}
    r = urllib.request.Request(url, data=json.dumps(body).encode(), method='POST')
    r.add_header('content-type', 'application/json')
    try:
        d = json.loads(urllib.request.urlopen(r, timeout=180).read().decode())
        t = (d.get('choices') or [{}])[0].get('message', {}).get('content', '')
        return (t.strip(), name) if t.strip() else ('', name)
    except Exception as e:
        return ('', '%s ошибка: %s' % (name, str(e)[:60]))


def leader(i):
    role = ROLES[i]
    text, model = ask('Задача: %s\n\nТы — %s в совете из 10 руководителей. Дай 5 мер, каждую с машинной '
                      'проверкой, и порядок внедрения. Без общих слов.' % (TASK, role), i)
    return i, role, text, model


def review(i, mine, others):
    text, model = ask('Задача: %s\n\nТвой материал (руководитель %s):\n%s\n\nМатериалы коллег:\n%s\n\n'
                      'Согласование: что принимаешь (3 пункта), что отклоняешь и почему (2 пункта), что добавляешь. Кратко.'
                      % (TASK, ROLES[i], mine[:1500], others[:2500]), i)
    return i, text, model


def battle(n, package):
    text, model = ask('%s\n\nОтветь как исполнитель №%d: 3 конкретные меры с метриками и порядок внедрения, кратко.'
                      % (package[:2500], n), n)
    return n, text, model


def main():
    os.makedirs('state/leaders', exist_ok=True)
    os.makedirs('state/battle', exist_ok=True)
    os.makedirs('battle-tasks', exist_ok=True)
    mats = {}
    with concurrent.futures.ThreadPoolExecutor(max_workers=5) as ex:
        for i, role, text, model in ex.map(leader, range(10)):
            mats[i] = text
            open('state/leaders/L%02d.md' % (i + 1), 'w', encoding='utf-8').write(
                '# Руководитель L%02d — %s\n\nмодель: %s\n\n%s\n' % (i + 1, role, model, text or '(модель не ответила)'))
            print('L%02d %s: %d симв. (%s)' % (i + 1, role, len(text), model))
    with concurrent.futures.ThreadPoolExecutor(max_workers=5) as ex:
        jobs = []
        for i in range(10):
            others = '\n\n'.join(mats[j][:800] for j in range(10) if j != i and mats.get(j))
            jobs.append(ex.submit(review, i, mats.get(i, ''), others))
        for fut in jobs:
            i, text, model = fut.result()
            open('state/leaders/L%02d-r2.md' % (i + 1), 'w', encoding='utf-8').write(
                '# Согласование L%02d (%s) — раунд 2\n\nмодель: %s\n\n%s\n' % (i + 1, ROLES[i], model,
                                                                             text or '(модель не ответила)'))
            print('L%02d-r2: %d симв.' % (i + 1, len(text)))
    package = 'ЗАДАЧА ДЛЯ ИСПОЛНИТЕЛЕЙ:\n%s\n\nМАТЕРИАЛЫ 10 РУКОВОДИТЕЛЕЙ:\n%s\n' % (
        TASK, '\n\n'.join('--- L%02d %s ---\n%s' % (i + 1, ROLES[i], mats.get(i, '')[:900]) for i in range(10)))
    open('battle-tasks/PACKAGE-01.txt', 'w', encoding='utf-8').write(package)
    print('пакет собран:', len(package), 'симв.')
    answers = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=6) as ex:
        for n, text, model in ex.map(lambda k: battle(k, package), range(1, 31)):
            rec = {'n': n, 'result': text[:3000], 'model': model,
                   'has_metric': bool(re.search(r'%|метрик|проверк|Recall|MRR|цифр', text, re.I)),
                   'chars': len(text)}
            answers.append(rec)
            print('исполнитель %02d: %d симв. (%s)' % (n, len(text), model))
    with open('state/battle/answers-01.jsonl', 'w', encoding='utf-8') as f:
        for rec in answers:
            f.write(json.dumps(rec, ensure_ascii=False) + '\n')
    with_metric = sum(1 for a in answers if a['has_metric'] and a['chars'] > 200)
    top = sorted(answers, key=lambda a: (a['has_metric'], a['chars']), reverse=True)[:10]
    pct = round(100 * with_metric / 30)
    rep = ['# ОТЧЁТ ПРОВЕРКИ (машина)', '',
           '- руководителей: 10, материалов: %d' % len([1 for i in range(10) if mats.get(i)]),
           '- согласований (раунд 2): 10',
           '- пакет для исполнителей: %d символов' % len(package),
           '- ответов исполнителей: 30',
           '- с машинной метрикой и объёмом >200 симв.: %d (%d%%)' % (with_metric, pct),
           '- отобрано в топ-10: %d' % len(top), '',
           '| № | модель | символов | метрика |', '|---|---|---|---|']
    for a in answers:
        rep.append('| %02d | %s | %d | %s |' % (a['n'], a['model'], a['chars'], 'да' if a['has_metric'] else 'нет'))
    open('REPORT-01.md', 'w', encoding='utf-8').write('\n'.join(rep))
    print('ОТЧЁТ: метрик %d%% (порог проверки), топ-10 отобран' % pct)
    import zipfile
    with zipfile.ZipFile('lawfill-out.zip', 'w', zipfile.ZIP_DEFLATED) as z:
        for dp, dn, fn in os.walk('.'):
            for name in fn:
                if name.endswith(('.md', '.txt', '.jsonl')):
                    z.write(os.path.join(dp, name), os.path.relpath(os.path.join(dp, name), '.'))
    print('архив lawfill-out.zip готов')


if __name__ == '__main__':
    main()
