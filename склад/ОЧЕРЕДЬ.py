# -*- coding: utf-8 -*-
"""ОЧЕРЕДЬ — много агентов разом: N исполнителей берут задачи из очереди и работают параллельно.

Зачем: «30 боёв одновременно», «40 агентов разом», «флот ищет 100 улучшений» — это одна и та же
задача: запустить много работ сразу и не потерять ни один результат. Очередь делает это без
внешних программ (никаких Redis и Celery): файл задач, несколько исполнителей, журнал результатов.

Формат задачи (одна строка JSON):
  {"имя": "поиск-1", "команда": "python3 скрипт.py аргумент", "таймаут": 600, "повторы": 1}

  ОЧЕРЕДЬ.cmd задачи.jsonl            — выполнить все задачи, 4 исполнителя
  ОЧЕРЕДЬ.cmd задачи.jsonl 8          — 8 исполнителей
  ОЧЕРЕДЬ.cmd --тест                  — самопроверка: 6 задач по 3 с, проверить, что время ~2×3 с, а не 6×3

Результаты: ОЧЕРЕДЬ-РЕЗУЛЬТАТЫ.jsonl и отметка сторожу на каждую задачу.
"""
import json
import os
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
РЕЗУЛЬТАТЫ = os.path.join(ROOT, 'ОЧЕРЕДЬ-РЕЗУЛЬТАТЫ.jsonl')
LOG = os.path.join(ROOT, 'ЛОГ-ОЧЕРЕДИ.txt')


def _log(т):
    s = '%s  %s' % (time.strftime('%d.%m %H:%M:%S'), т)
    print(s)
    try:
        with open(LOG, 'a', encoding='utf-8') as f:
            f.write(s + '\n')
    except Exception:
        pass


def _отметить(имя):
    try:
        sys.path.insert(0, HERE)
        import СТОРОЖ
        СТОРОЖ.отметить('очередь-' + имя)
    except Exception:
        pass


def выполнить(задача):
    имя = задача.get('имя') or 'задача'
    команда = задача['команда']
    таймаут = int(задача.get('таймаут', 1800))
    повторов = int(задача.get('повторы', 1))
    начало = time.time()
    for попытка in range(1, повторов + 1):
        _отметить(имя)
        try:
            r = subprocess.run(команда, shell=True, cwd=задача.get('папка') or ROOT,
                               capture_output=True, text=True, timeout=таймаут)
            итог = {'имя': имя, 'код': r.returncode, 'попытка': попытка,
                    'секунд': round(time.time() - начало, 1),
                    'вывод': (r.stdout or '')[-2000:], 'ошибки': (r.stderr or '')[-1000:]}
        except subprocess.TimeoutExpired:
            итог = {'имя': имя, 'код': 'таймаут', 'попытка': попытка,
                    'секунд': таймаут, 'вывод': '', 'ошибки': 'не уложилась в %d с' % таймаут}
        if итог['код'] == 0:
            break
    with open(РЕЗУЛЬТАТЫ, 'a', encoding='utf-8') as f:
        f.write(json.dumps(итог, ensure_ascii=False) + '\n')
    _log('«%s»: код %s за %s с' % (имя, итог['код'], итог['секунд']))
    return итог


def запустить(путь, исполнителей=4):
    задачи = []
    for строка in open(путь, encoding='utf-8'):
        строка = строка.strip()
        if not строка or строка.startswith('#'):
            continue
        задачи.append(json.loads(строка))
    _log('очередь: %d задач, исполнителей %d' % (len(задачи), исполнителей))
    т0 = time.time()
    with ThreadPoolExecutor(max_workers=исполнителей) as пул:
        итоги = list(пул.map(выполнить, задачи))
    все_ок = sum(1 for и in итоги if и['код'] == 0)
    _log('итог: успешно %d из %d за %.1f с' % (все_ок, len(итоги), time.time() - т0))
    return 0 if все_ок == len(итоги) else 1


def тест():
    """Доказывает, что работы идут параллельно: 6 задач по 3 с при 3 исполнителях = ~6 с, не 18."""
    путь = os.path.join(ROOT, 'ОЧЕРЕДЬ-ТЕСТ.jsonl')
    with open(путь, 'w', encoding='utf-8') as f:
        for i in range(6):
            f.write(json.dumps({'имя': 'проба-%d' % (i + 1),
                                'команда': '%s -c "import time; time.sleep(3); print(\'готово %d\')"'
                                           % (sys.executable, i + 1)}, ensure_ascii=False) + '\n')
    т0 = time.time()
    запустить(путь, 3)
    прошло = time.time() - т0
    print('=' * 60)
    print('6 задач по 3 с при 3 исполнителях заняли %.1f с' % прошло)
    print('последовательно было бы 18 с. Параллельность: %s'
          % ('РАБОТАЕТ' if прошло < 11 else 'НЕ РАБОТАЕТ'))
    try:
        sys.path.insert(0, HERE)
        import АГЕНТ
        АГЕНТ.сдать(РЕЗУЛЬТАТЫ, 'очередь,результаты')
        АГЕНТ.сдать(путь, 'очередь,тест')
        print('результаты отправлены на склад')
    except Exception as e:
        print('на склад не ушло:', str(e)[:100])
    return 0 if прошло < 11 else 1


if __name__ == '__main__':
    args = [a for a in sys.argv[1:]]
    if '--тест' in args or '--test' in args:
        sys.exit(тест())
    if not args:
        print(__doc__)
        sys.exit(2)
    путь = args[0]
    исполнителей = int(args[1]) if len(args) > 1 and args[1].isdigit() else 4
    sys.exit(запустить(путь, исполнителей))
