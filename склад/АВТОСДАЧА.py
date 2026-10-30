# -*- coding: utf-8 -*-
"""АВТОСДАЧА — всё, что появилось в рабочей папке, само уезжает в хранилище Telegram.

Ничего не надо нажимать: проходит круг, сравнивает sha256 с индексом склада, заливает новое
и изменённое. Файлы не удаляются — старые версии остаются в индексе под своим sha256.

  АВТОСДАЧА.cmd              — работать по кругу (пауза 60 с), пока не закроют окно
  АВТОСДАЧА.cmd --один_раз   — один круг и выход
  АВТОСДАЧА.cmd --пауза 300  — пауза между кругами 300 с

Пропускает: системный кэш, .git, node_modules, __pycache__, .pyc/.log/.tmp.
Пишет ЛОГ-АВТОСДАЧИ.txt и отмечается сторожу как «автосдача» — лимит зря не жжётся.
"""
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
LOG = os.path.join(ROOT, 'ЛОГ-АВТОСДАЧИ.txt')
ПАУЗА = 60


def _log(строка):
    line = '%s  %s' % (time.strftime('%d.%m %H:%M:%S'), строка)
    print(line)
    try:
        with open(LOG, 'a', encoding='utf-8') as f:
            f.write(line + '\n')
        if os.path.getsize(LOG) > 400000:
            open(LOG, 'w', encoding='utf-8').write(line + '\n')
    except Exception:
        pass


def круг():
    sys.path.insert(0, HERE)
    import ХРАНИЛИЩЕ as Х
    try:
        import СТОРОЖ as С
        С.отметить('автосдача')
    except Exception:
        pass
    было = Х.статистика()['файлов']
    итог = Х.синхронизировать(ROOT, 'автосдача')
    стало = Х.статистика()['файлов']
    if итог['залито']:
        _log('круг: залито %d, пропущено таких же %d, всего на складе %d (было %d)'
             % (итог['залито'], итог['пропущено_таких_же'], стало, было))
    return итог


def main(argv):
    глобально = globals()
    if '--пауза' in argv:
        i = argv.index('--пауза')
        if i + 1 < len(argv) and argv[i + 1].isdigit():
            глобально['ПАУЗА'] = int(argv[i + 1])
    один = '--один_раз' in argv or '--один' in argv
    _log('старт: папка %s, пауза %d с, режим %s' % (ROOT, ПАУЗА, 'один круг' if один else 'по кругу'))
    while True:
        try:
            круг()
        except Exception as e:
            _log('сбой круга: %s' % str(e)[:160])
        if один:
            break
        try:
            time.sleep(ПАУЗА)
        except KeyboardInterrupt:
            _log('остановлено вручную')
            break
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
