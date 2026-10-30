# -*- coding: utf-8 -*-
"""СТОРОЖ — выключает работу при бездействии, чтобы не тратился лимит.

Зачем: агенты, совет, слежка и бои жгут лимит аккаунтов и запросов, даже когда
ничего не делают. Сторож держит все задачи под надзором и через N минут тишины
(по умолчанию 5) замораживает процесс: он остаётся в памяти, ничего не тратит,
и оживает от первой же активности.

Активность — это любое из трёх:
  1) процесс реально считает (растёт его процессорное время);
  2) изменился файл в папках, которые задача трогает;
  3) агент сам отметился:  import СТОРОЖ; СТОРОЖ.отметить('совет')

Работает на Windows (NtSuspendProcess/NtResumeProcess) и Linux (SIGSTOP/SIGCONT).
Только стандартная библиотека.

Команды:
  СТОРОЖ.cmd                  — запустить надзор по задачам из .ФЛОТ-флот/сторож/задачи.json
  СТОРОЖ.cmd статус           — что заморожено, сколько тишины у каждой
  СТОРОЖ.cmd отметить <имя>   — сказать «эта задача работала сейчас»
  СТОРОЖ.cmd пробудить <имя>  — разморозить руками
  СТОРОЖ.cmd тест             — 20-секундная проверка: заморозка и оживление
"""
import json
import os
import signal
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
DIR = os.path.join(ROOT, '.ФЛОТ-флот', 'сторож')
CFG = os.path.join(DIR, 'задачи.json')
LOG = os.path.join(ROOT, 'ЛОГ-СТОРОЖА.txt')
ACT = os.path.join(DIR, 'активность')
ОЖИДАНИЕ_МИН = 5                      # тишина, после которой задача замораживается
ПРОВЕРКА_С = float(os.environ.get('СТОРОЖ_ПРОВЕРКА', 10))   # как часто сторож смотрит, сек


# ------------------------------------------------------------------ активность
def отметить(имя):
    """Агент говорит: я работаю. Сторож снимет заморозку и обнулит таймер тишины."""
    os.makedirs(ACT, exist_ok=True)
    with open(os.path.join(ACT, имя + '.ts'), 'w') as f:
        f.write(str(time.time()))


def _когда_отмечались(имя):
    p = os.path.join(ACT, имя + '.ts')
    try:
        return float(open(p).read().strip())
    except Exception:
        return 0.0


# ------------------------------------------------------------------ морозилка
def _заморозить(pid):
    if os.name == 'nt':
        import ctypes
        h = ctypes.windll.kernel32.OpenProcess(0x1F0FFF, False, pid)
        ctypes.windll.ntdll.NtSuspendProcess(h)
        ctypes.windll.kernel32.CloseHandle(h)
    else:
        os.kill(pid, signal.SIGSTOP)


def _разморозить(pid):
    if os.name == 'nt':
        import ctypes
        h = ctypes.windll.kernel32.OpenProcess(0x1F0FFF, False, pid)
        ctypes.windll.ntdll.NtResumeProcess(h)
        ctypes.windll.kernel32.CloseHandle(h)
    else:
        os.kill(pid, signal.SIGCONT)


def _жив(pid):
    if os.name == 'nt':
        import ctypes
        h = ctypes.windll.kernel32.OpenProcess(0x1000, False, pid)
        if not h:
            return False
        code = ctypes.c_ulong()
        ctypes.windll.kernel32.GetExitCodeProcess(h, ctypes.byref(code))
        ctypes.windll.kernel32.CloseHandle(h)
        return code.value == 259
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def _процессорное_время(pid):
    """Секунды процессора, сожжённые задачей и всеми её детьми.

    Важно: команду запускает оболочка (cmd.exe / sh), а настоящая работа идёт в дочернем
    процессе — поэтому считаем всё дерево, иначе задача всегда выглядит «спящей».
    """
    try:
        import psutil
        p = psutil.Process(pid)
        total = sum(p.cpu_times()[:2])
        for ch in p.children(recursive=True):
            try:
                total += sum(ch.cpu_times()[:2])
            except Exception:
                pass
        return total
    except ImportError:
        pass
    except Exception:
        return 0.0
    # запасной путь без psutil: складываем дерево по /proc (только Linux)
    try:
        рады, дети = {}, {}
        for имя in os.listdir('/proc'):
            if not имя.isdigit():
                continue
            try:
                d = open('/proc/%s/stat' % имя).read()
            except Exception:
                continue
            тело = d[d.rindex(')') + 2:].split()
            ppid = int(тело[1])
            cpu = (int(тело[11]) + int(тело[12])) / os.sysconf('SC_CLK_TCK')
            рады[int(имя)] = cpu
            дети.setdefault(ppid, []).append(int(имя))
        total, стек = рады.get(pid, 0.0), [pid]
        while стек:
            for ch in дети.get(стек.pop(), []):
                total += рады.get(ch, 0.0)
                стек.append(ch)
        return total
    except Exception:
        return 0.0


def _последняя_правка(папки):
    newest = 0.0
    for папка in папки or []:
        if not os.path.isdir(папка):
            continue
        for root, _, files in os.walk(папка):
            for f in files:
                try:
                    newest = max(newest, os.path.getmtime(os.path.join(root, f)))
                except OSError:
                    pass
    return newest


# ------------------------------------------------------------------ надзор
def _log(строка):
    line = '%s  %s' % (time.strftime('%d.%m %H:%M:%S'), строка)
    print(line)
    try:
        with open(LOG, 'a', encoding='utf-8') as f:
            f.write(line + '\n')
    except Exception:
        pass


def надзор():
    if not os.path.exists(CFG):
        os.makedirs(DIR, exist_ok=True)
        json.dump([{'имя': 'пример', 'команда': '', 'папка': '.', 'минут_тишины': 5}],
                  open(CFG, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
        _log('создал шаблон %s — впиши задачи' % CFG)
        return 1
    задачи = json.load(open(CFG, encoding='utf-8'))
    os.makedirs(ACT, exist_ok=True)
    живые = {}
    for з in задачи:
        if not з.get('команда'):
            continue
        p = subprocess.Popen(з['команда'], shell=True, cwd=з.get('папка') or ROOT)
        живые[з['имя']] = {'proc': p, 'з': з, 'cpu': 0.0, 'мороз': False,
                           'последняя': time.time(), 'папки': з.get('папки') or []}
        _log('запущена задача «%s» (pid %d, лимит тишины %s мин)'
             % (з['имя'], p.pid, з.get('минут_тишины', ОЖИДАНИЕ_МИН)))
    if not живые:
        _log('нет задач с командой — нечего сторожить')
        return 1
    try:
        while True:
            time.sleep(ПРОВЕРКА_С)
            сейчас = time.time()
            for имя, з in list(живые.items()):
                p = з['proc']
                if p.poll() is not None:
                    _log('задача «%s» завершилась сама, код %s' % (имя, p.returncode))
                    живые.pop(имя)
                    continue
                cpu = _процессорное_время(p.pid)
                отметка = _когда_отмечались(имя)
                правка = _последняя_правка(з['папки'])
                работал = (cpu > з['cpu'] + 0.05) or (отметка > з['последняя']) or (правка > з['последняя'])
                if работал:
                    з['последняя'] = сейчас
                    if з['мороз']:
                        _разморозить(p.pid)
                        з['мороз'] = False
                        _log('«%s» ожил — есть активность' % имя)
                elif not з['мороз']:
                    тишина = (сейчас - з['последняя']) / 60
                    лимит = з['з'].get('минут_тишины', ОЖИДАНИЕ_МИН)
                    if тишина >= лимит:
                        _заморозить(p.pid)
                        з['мороз'] = True
                        _log('«%s» заморожен: %.1f мин тишины (лимит %s), лимит не тратится'
                             % (имя, тишина, лимит))
                з['cpu'] = cpu
    except (KeyboardInterrupt, SystemExit):
        for имя, з in живые.items():
            if з['мороз']:
                _разморозить(з['proc'].pid)
            try:
                з['proc'].kill()
            except Exception:
                pass
        _log('сторож остановлен вручную, все задачи разморожены')
    return 0


def статус():
    строки = []
    if not os.path.exists(CFG):
        return 'задач нет: файла %s ещё нет' % CFG
    for з in json.load(open(CFG, encoding='utf-8')):
        имя = з.get('имя', '?')
        тишина = (time.time() - _когда_отмечались(имя)) / 60 if _когда_отмечались(имя) else None
        строки.append('%-16s лимит %-3s мин  отметка %s'
                      % (имя, з.get('минут_тишины', ОЖИДАНИЕ_МИН),
                         ('%.1f мин назад' % тишина) if тишина is not None else 'не было'))
    return '\n'.join(строки)


def тест():
    """45 секунд: задача работает 12 с, потом молчит; сторож должен её заморозить и оживить."""
    import shutil
    os.makedirs(DIR, exist_ok=True)
    скрипт = os.path.join(DIR, 'сторож_тест.py')
    with open(скрипт, 'w', encoding='utf-8') as f:
        f.write('import time\n'
                't = time.time()\n'
                'while time.time() - t < 12:\n'
                '    time.sleep(0.05)\n'
                "    open(r'%s', 'a').write('x')\n" % os.path.join(DIR, 'тест.txt') +
                'time.sleep(600)\n')
    back = json.dump(['сохранение'], open('/dev/null', 'w'))
    было = json.load(open(CFG, encoding='utf-8')) if os.path.exists(CFG) else []
    json.dump([{'имя': 'тест', 'команда': '%s "%s"' % (sys.executable, скрипт),
                'папка': ROOT, 'папки': [DIR], 'минут_тишины': 0.15}],   # 9 секунд тишины
              open(CFG, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    print('тест: задача работает 12 с, затем молчит. Лимит 9 с, проверка каждые 4 с. Всего 48 с.')
    if os.path.exists(LOG):
        os.remove(LOG)
    среда = dict(os.environ, СТОРОЖ_ПРОВЕРКА='4')
    p = subprocess.Popen([sys.executable, os.path.abspath(__file__), '_надзор'],
                         start_new_session=True, env=среда)
    time.sleep(36)
    отметить('тест')
    print('отметил активность — задача должна ожить')
    time.sleep(12)
    try:
        os.killpg(os.getpgid(p.pid), signal.SIGKILL)
    except Exception:
        p.kill()
    subprocess.run(['pkill', '-f', 'сторож_тест.py'], capture_output=True)
    json.dump(было, open(CFG, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    print('--- лог теста ---')
    print(open(LOG, encoding='utf-8').read() if os.path.exists(LOG) else 'лог пуст')
    return 0


def main(argv):
    cmd = argv[0] if argv else 'надзор'
    if cmd in ('надзор', 'start', 'запустить'):
        return надзор()
    if cmd == '_надзор':
        return надзор()
    if cmd in ('статус', 'status'):
        print(статус())
        return 0
    if cmd in ('отметить', 'touch'):
        отметить(argv[1])
        print('отметил «%s»' % argv[1])
        return 0
    if cmd in ('пробудить', 'resume'):
        print('разморозка идёт автоматически по активности; отметил «%s»' % argv[1])
        отметить(argv[1])
        return 0
    if cmd in ('тест', 'test'):
        return тест()
    print(__doc__)
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
