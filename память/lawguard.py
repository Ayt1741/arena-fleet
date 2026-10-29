#!/usr/bin/env python3
"""lawguard — сторож законов в CI: правило в файле не гарантирует исполнения,
гарантирует проверка на каждом коммите (так пишут в инженерных статьях про rules/hooks).

Проверяет:
 1. ЗАКОНЫ-КРАТКО.md на месте, не длиннее 200 строк, в нём ровно 10 законов;
 2. ЗАДАЧИ-ОТКРЫТЫЕ.md на месте и содержит цифры;
 3. ни в одном файле репозитория нет токенов/паролей/2FA-секретов открытым текстом;
 4. исследование памяти содержит 20 тем;
 5. все программы памяти компилируются.
Любая осечка — код возврата 1, сборка красная.
"""
import ast
import os
import re
import sys

ROOT = os.path.dirname(os.path.abspath(__file__))  # папка «память» в репозитории
SECRETS = [
    (r'github_pat_[A-Za-z0-9_]{20,}', 'токен GitHub'),
    (r'gh[pousr]_[A-Za-z0-9]{20,}', 'токен GitHub'),
    (r'\b[0-9]{8,10}:AA[A-Za-z0-9_-]{25,}', 'токен Telegram-бота'),
    (r'\b[A-Z2-7]{32}\b', '2FA-секрет'),
]
checks = []


def lines(p):
    return open(p, encoding='utf-8', errors='ignore').read().split('\n')


laws = os.path.join(ROOT, 'ЗАКОНЫ-КРАТКО.md')
if os.path.exists(laws):
    L = lines(laws)
    n_laws = len(re.findall(r'^\d+\. ', '\n'.join(L), re.M))
    checks.append(('законы: файл есть, строк %d' % len(L), len(L) <= 200 and n_laws == 10))
else:
    checks.append(('законы: файла нет', False))

tasks = os.path.join(ROOT, 'ЗАДАЧИ-ОТКРЫТЫЕ.md')
has_numbers = os.path.exists(tasks) and len(re.findall(r'\d', open(tasks, encoding='utf-8').read())) > 50
checks.append(('задачи: файл с цифрами', has_numbers))

res = os.path.join(ROOT, 'ИССЛЕДОВАНИЕ-ПАМЯТЬ-20-ТЕМ.md')
n_topics = len(re.findall(r'^## \d\d\. ', open(res, encoding='utf-8').read(), re.M)) if os.path.exists(res) else 0
checks.append(('исследование: 20 тем (найдено %d)' % n_topics, n_topics == 20))

bad = []
for dp, dn, fn in os.walk(ROOT):
    for name in fn:
        if not name.endswith(('.md', '.py', '.json', '.yml', '.txt')):
            continue
        p = os.path.join(dp, name)
        txt = open(p, encoding='utf-8', errors='ignore').read()
        for pat, what in SECRETS:
            if re.search(pat, txt):
                bad.append('%s: %s' % (os.path.relpath(p, ROOT), what))
checks.append(('секретов в файлах нет' + ('' if not bad else ': ' + '; '.join(bad[:3])), not bad))

compiled = []
for dp, dn, fn in os.walk(ROOT):
    for name in fn:
        if name.endswith('.py'):
            p = os.path.join(dp, name)
            try:
                ast.parse(open(p, encoding='utf-8').read())
                compiled.append(os.path.relpath(p, ROOT))
            except SyntaxError as e:
                compiled.append('%s: ОШИБКА СИНТАКСИСА %s' % (os.path.relpath(p, ROOT), e.lineno))
ok_syntax = all('ОШИБКА' not in c for c in compiled)
checks.append(('программы компилируются (%d файлов)' % len(compiled), ok_syntax))

for name, ok in checks:
    print(('OK      ' if ok else 'НАРУШЕНО ') + name)
done = sum(1 for _, ok in checks if ok)
print('ИТОГ: %d из %d = %d %%' % (done, len(checks), round(100 * done / len(checks))))
sys.exit(0 if done == len(checks) else 1)
