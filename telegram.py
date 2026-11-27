#!/usr/bin/env python3
"""Zero-dependency Telegram bridge for shells and AI coding agents: watch, send, ask, and share files.

Config: ~/.config/telegram/config.json {"token", "chat_id"} (legacy fallback:
~/.config/ds/telegram.json), written by `telegram setup` (or env TELEGRAM_BOT_TOKEN /
TELEGRAM_CHAT_ID). Messages are headed with "host · dir" (override: TELEGRAM_LABEL).

Updates are never confirmed on Telegram's side (Telegram keeps them 24h), so multiple
devices can share one bot. Locally, `telegram watch` enforces a single active watcher
with software-driven handoff (active.json + SIGUSR1) so a new session cleanly stops
the previous watcher and tells its agent not to restart.
"""
import argparse
import getpass
import json
import os
import select
import signal
import socket
import sys
import time
import urllib.error
import urllib.request
import uuid

API = os.environ.get('TELEGRAM_API', 'https://api.telegram.org')
STATE_DIR = os.path.expanduser(os.environ.get('TELEGRAM_STATE_DIR', '~/.local/state/telegram'))
DEFAULT_CURSOR = os.path.join(STATE_DIR, 'cursor.json')
DEFAULT_INBOX = os.path.join(STATE_DIR, 'inbox')
INBOX_TTL = int(os.environ.get('TELEGRAM_INBOX_TTL', 86400))  # auto-prune managed inbox files older than 24h
ACTIVE_FILE = os.path.join(STATE_DIR, 'active.json')
LABEL = os.environ.get('TELEGRAM_LABEL') or f'{socket.gethostname()} · {os.path.basename(os.getcwd())}'
MAX_PARTS = 3  # longer text goes as a .txt file instead of a burst of messages
EXIT_STOPPED = 10  # exited cleanly because another session took over or `telegram stop` ran
TOKEN = CHAT = None


def resolve_config_path():
    env_path = os.environ.get('TELEGRAM_CONFIG') or os.environ.get('DS_TELEGRAM_CONFIG')
    if env_path:
        return os.path.expanduser(env_path)
    primary = os.path.expanduser('~/.config/telegram/config.json')
    legacy = os.path.expanduser('~/.config/ds/telegram.json')
    if not os.path.exists(primary) and os.path.exists(legacy):
        return legacy
    return primary


CONFIG = resolve_config_path()

# IPv4 first: urllib tries addresses in order, and a broken IPv6 route (common) stalls every call until timeout
_getaddrinfo = socket.getaddrinfo
socket.getaddrinfo = lambda *a, **k: sorted(_getaddrinfo(*a, **k), key=lambda r: r[0] != socket.AF_INET)


class TgError(Exception):
    def __init__(self, code, desc):
        super().__init__(f'Telegram: {desc}')
        self.code = code or 0


def api(method, data=None, files=None):
    """Call the Bot API. Waits out rate limits and retries server/network errors a few times.
    files: {field: (filename, bytes)}"""
    data = data or {}
    if files:
        boundary = uuid.uuid4().hex
        parts = [f'--{boundary}\r\nContent-Disposition: form-data; name="{k}"\r\n\r\n'.encode()
                 + str(v if isinstance(v, (str, int)) else json.dumps(v)).encode() + b'\r\n'
                 for k, v in data.items()]
        for k, (name, content) in files.items():
            name = name.replace('"', '')
            parts.append(f'--{boundary}\r\nContent-Disposition: form-data; name="{k}"; filename="{name}"\r\n\r\n'.encode()
                         + content + b'\r\n')
        body = b''.join(parts) + f'--{boundary}--\r\n'.encode()
        ctype = f'multipart/form-data; boundary={boundary}'
    else:
        body, ctype = json.dumps(data).encode(), 'application/json'
    req = urllib.request.Request(f'{API}/bot{TOKEN}/{method}', body, {'Content-Type': ctype})
    for attempt in range(4):
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                res = json.load(r)
        except urllib.error.HTTPError as e:  # Telegram puts the reason in a JSON body
            try:
                res = json.load(e)
            except ValueError:
                res = {'error_code': e.code, 'description': f'HTTP {e.code}'}
        except OSError:
            if attempt == 3:
                raise
            time.sleep(2 ** attempt)
            continue
        if res.get('ok'):
            return res['result']
        code = res.get('error_code') or 0
        if attempt < 3 and (code == 429 or code >= 500):
            time.sleep(min(res.get('parameters', {}).get('retry_after', 2 ** attempt), 60))
            continue
        raise TgError(code, res.get('description'))


def quiet(method, data):
    try:
        api(method, data)
    except (TgError, OSError):
        pass


def load():
    global TOKEN, CHAT
    cfg = {}
    if os.path.exists(CONFIG):
        try:
            with open(CONFIG) as f:
                cfg = json.load(f)
        except ValueError:
            sys.exit(f'Broken config {CONFIG}: run `telegram setup` again')
    TOKEN = os.environ.get('TELEGRAM_BOT_TOKEN') or cfg.get('token')
    CHAT = int(os.environ.get('TELEGRAM_CHAT_ID') or cfg.get('chat_id') or 0)
    if not TOKEN or not CHAT:
        sys.exit('Not set up yet: run `telegram setup`')


def u16(s):  # Telegram measures lengths in UTF-16 code units
    return len(s.encode('utf-16-le')) // 2


def split(text, limit):
    """Pieces of at most `limit` UTF-16 units, cut at a line end where possible."""
    out = []
    while text:
        n = size = 0
        while n < len(text) and size + u16(text[n]) <= limit:
            size += u16(text[n])
            n += 1
        if n < len(text) and text.rfind('\n', 0, n) > 0:
            n = text.rfind('\n', 0, n) + 1
        out.append(text[:n])
        text = text[n:]
    return out


def headed(text, limit):
    """LABEL in bold on the first line, then text cut to fit `limit`: (text, entities)."""
    body = split(text, limit - u16(LABEL) - 1)[0] if text else ''
    return f'{LABEL}\n{body}'.rstrip(), [{'type': 'bold', 'offset': 0, 'length': u16(LABEL)}]


def send_file(name, content, caption=''):
    caption, entities = headed(caption, 1024)
    api('sendDocument', {'chat_id': CHAT, 'caption': caption, 'caption_entities': entities},
        {'document': (name, content)})


def say(text, buttons=None):
    """Send text under the label header; returns the last message (the one with the buttons)."""
    text = text.strip()
    if not text:
        sys.exit('Nothing to send')
    parts = split(text, 4096 - u16(LABEL) - 1)
    if len(parts) > MAX_PARTS and not buttons:
        return send_file('message.txt', text.encode(), parts[0][:300] + '…')
    for i, part in enumerate(parts):
        msg, entities = headed(part, 4096)
        data = {'chat_id': CHAT, 'text': msg, 'entities': entities}
        if buttons and i == len(parts) - 1:
            data['reply_markup'] = {'inline_keyboard': [[{'text': b, 'callback_data': str(j)} for j, b in enumerate(buttons)]]}
        sent = api('sendMessage', data)
    return sent


def updates():
    """Pending updates (last 24h), left unconfirmed so other devices see them too."""
    ups = api('getUpdates')
    while len(ups) == 100:  # one call returns at most 100: drop the oldest half so new ones stay visible
        ups = api('getUpdates', {'offset': ups[50]['update_id']})
    return ups


def text_of(m):
    text = m.get('text') or m.get('caption') or ''
    kind = next((k for k in ('photo', 'document', 'voice', 'video', 'audio', 'sticker') if k in m), None)
    return f'[{kind}] {text}'.strip() if kind else text


def cleanup_inbox(dest_dir, ttl=INBOX_TTL):
    """Remove files older than `ttl` seconds from the managed default inbox."""
    if not dest_dir or ttl <= 0 or not os.path.isdir(dest_dir):
        return
    cutoff = time.time() - ttl
    try:
        for entry in os.scandir(dest_dir):
            try:
                if entry.is_file(follow_symlinks=False) and entry.stat().st_mtime < cutoff:
                    os.unlink(entry.path)
            except OSError:
                pass
    except OSError:
        pass


def download_media(m, dest_dir):
    """Download photo/document/voice/audio from a message into dest_dir; returns local path or None."""
    if not dest_dir:
        return None
    file_id = name = None
    if m.get('photo'):
        file_id = m['photo'][-1]['file_id']
        name = f"{m['message_id']}.jpg"
    elif m.get('document'):
        file_id = m['document']['file_id']
        name = f"{m['message_id']}-{os.path.basename(m['document'].get('file_name') or 'file')}"
    elif m.get('voice'):
        file_id = m['voice']['file_id']
        name = f"{m['message_id']}.ogg"
    elif m.get('audio'):
        file_id = m['audio']['file_id']
        name = f"{m['message_id']}-{os.path.basename(m['audio'].get('file_name') or 'audio.mp3')}"
    if not file_id:
        return None
    try:
        info = api('getFile', {'file_id': file_id})
        fp = info.get('file_path')
        if not fp:
            return None
        os.makedirs(dest_dir, exist_ok=True)
        out_path = os.path.join(dest_dir, name.replace('/', '_'))
        with urllib.request.urlopen(f'{API}/file/bot{TOKEN}/{fp}', timeout=30) as r:
            data = r.read()
        with open(out_path, 'wb') as f:
            f.write(data)
        return out_path
    except (TgError, OSError):
        return None


def atomic_write_json(path, payload):
    d = os.path.dirname(path)
    if d:
        os.makedirs(d, exist_ok=True)
    tmp = f'{path}.{os.getpid()}.{uuid.uuid4().hex[:6]}.tmp'
    with open(tmp, 'w') as f:
        json.dump(payload, f)
    os.replace(tmp, path)


def read_json(path):
    try:
        with open(path) as f:
            data = json.load(f)
            return data if isinstance(data, dict) else None
    except (OSError, ValueError, TypeError):
        return None


def read_cursor(path):
    data = read_json(path)
    if not data:
        return None
    try:
        return int(data['last_update_id'])
    except (KeyError, ValueError, TypeError):
        return None


def write_cursor(path, update_id):
    atomic_write_json(path, {'last_update_id': int(update_id), 'ts': int(time.time())})


def default_owner():
    return (
        os.environ.get('TELEGRAM_OWNER')
        or os.environ.get('OPENCODE_SESSION_ID')
        or os.environ.get('CLAUDE_SESSION_ID')
        or f'cwd:{os.getcwd()}'
    )


def pid_alive(pid):
    if not isinstance(pid, int) or pid <= 1 or pid == os.getpid():
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    cmdline = f'/proc/{pid}/cmdline'
    if os.path.exists(cmdline):
        try:
            with open(cmdline, 'rb') as f:
                raw = f.read().decode('utf-8', 'ignore')
            if 'telegram' not in raw and 'python' not in raw:
                return False
        except OSError:
            pass
    return True


def terminate_watcher(pid, grace=2.5):
    """Ask an existing watcher to emit [STOP] and exit via SIGUSR1; fall back to SIGTERM if hung."""
    if not pid_alive(pid):
        return False
    try:
        os.kill(pid, signal.SIGUSR1)
    except ProcessLookupError:
        return False
    except OSError:
        return False
    deadline = time.time() + grace
    while time.time() < deadline:
        if not pid_alive(pid):
            return True
        time.sleep(0.05)
    try:
        os.kill(pid, signal.SIGTERM)
    except OSError:
        pass
    deadline = time.time() + 0.5
    while time.time() < deadline:
        if not pid_alive(pid):
            return True
        time.sleep(0.05)
    return True


def emit_stop(as_json, reason, by_label=None, by_owner=None):
    if reason == 'stopped':
        msg = f'Telegram watch was stopped{f" by {by_label}" if by_label else ""}. Stop listening and do NOT restart telegram watch.'
    else:
        who = by_label or by_owner or 'another session'
        msg = f'Telegram watch handed off to another session ({who}). Stop listening and do NOT restart telegram watch.'
    if as_json:
        payload = {'event': 'stop', 'reason': reason, 'message': msg}
        if by_label:
            payload['by'] = by_label
        if by_owner:
            payload['owner'] = by_owner
        print(json.dumps(payload, ensure_ascii=False), flush=True)
    else:
        print(f'[STOP] {msg}', flush=True)
    sys.exit(EXIT_STOPPED)


def cmd_stop(a):
    prev = read_json(ACTIVE_FILE)
    atomic_write_json(ACTIVE_FILE, {
        'stopped': True,
        'by': LABEL,
        'ts': int(time.time()),
    })
    if prev and not prev.get('stopped') and pid_alive(prev.get('pid')):
        terminate_watcher(prev['pid'])
        print(f"Stopped active watcher ({prev.get('label') or prev.get('owner')}, pid {prev['pid']}).")
    else:
        print('No active watcher running.')


def cmd_watch(a):
    """Block until one or more new messages arrive; enforces single active local watcher with clean handoff."""
    cursor_path = os.path.expanduser(a.cursor)
    download_dir = '' if a.no_download else os.path.expanduser(a.download)
    if download_dir and os.path.abspath(download_dir) == os.path.abspath(DEFAULT_INBOX):
        cleanup_inbox(download_dir)
    my_owner = a.owner or default_owner()
    my_token = uuid.uuid4().hex
    prev = read_json(ACTIVE_FILE)

    if a.resume:
        # Only resume if this session still owns the slot AND no other watcher is already live
        if not prev or prev.get('stopped'):
            emit_stop(a.json, 'stopped', prev.get('by') if prev else None)
        if prev.get('owner') != my_owner or pid_alive(prev.get('pid')):
            emit_stop(a.json, 'handed_off', prev.get('label'), prev.get('owner'))

    # Atomically claim ownership BEFORE signaling the previous watcher so it immediately reads who took over
    atomic_write_json(ACTIVE_FILE, {
        'pid': os.getpid(),
        'token': my_token,
        'owner': my_owner,
        'label': LABEL,
        'started_at': int(time.time()),
    })

    if prev and not prev.get('stopped') and prev.get('pid') != os.getpid():
        if terminate_watcher(prev.get('pid')):
            who = prev.get('label') or prev.get('owner') or f"pid {prev.get('pid')}"
            print(f'Took over watch from {who} (pid {prev.get("pid")}).', file=sys.stderr, flush=True)

    # Async-signal-safe wakeup pipe so SIGUSR1 interrupts sleep in <1ms (bypasses PEP 475 sleep retry)
    wake_r, wake_w = os.pipe()
    os.set_blocking(wake_r, False)
    os.set_blocking(wake_w, False)
    prev_wakeup_fd = signal.set_wakeup_fd(wake_w, warn_on_full_buffer=False)
    signaled = {'usr1': False}

    def on_usr1(_sig, _frame):
        signaled['usr1'] = True

    signal.signal(signal.SIGUSR1, on_usr1)

    def check_ownership():
        cur = read_json(ACTIVE_FILE)
        if signaled['usr1'] or not cur or cur.get('token') != my_token:
            if cur and cur.get('stopped'):
                emit_stop(a.json, 'stopped', cur.get('by'))
            emit_stop(a.json, 'handed_off', cur.get('label') if cur else None, cur.get('owner') if cur else None)

    def sleep_or_wake(seconds):
        if seconds <= 0:
            check_ownership()
            return
        try:
            ready, _, _ = select.select([wake_r], [], [], seconds)
            if ready:
                try:
                    os.read(wake_r, 64)
                except BlockingIOError:
                    pass
        except InterruptedError:
            pass
        check_ownership()

    try:
        last_id = a.since if a.since is not None else read_cursor(cursor_path)

        def fetch_safe():
            backoff = a.interval
            while True:
                check_ownership()
                try:
                    ups = updates()
                    check_ownership()
                    return ups
                except OSError:
                    sleep_or_wake(backoff)
                    backoff = min(backoff * 1.5, 15.0)
                except TgError as e:
                    if e.code not in (409, 429) and e.code < 500:
                        raise
                    sleep_or_wake(backoff)
                    backoff = min(backoff * 1.5, 15.0)

        if last_id is None:
            ups = fetch_safe()
            last_id = max((u['update_id'] for u in ups), default=0)
            write_cursor(cursor_path, last_id)

        deadline = (time.time() + a.timeout) if a.timeout > 0 else None
        batch_until = None
        collected = []

        while True:
            ups = fetch_safe()
            fresh = [
                u for u in ups
                if u['update_id'] > last_id and u.get('message', {}).get('chat', {}).get('id') == CHAT
            ]
            if fresh:
                collected.extend(fresh)
                last_id = max(u['update_id'] for u in fresh)
                write_cursor(cursor_path, last_id)
                if batch_until is None:
                    batch_until = time.time() + a.batch
            if collected and (a.batch <= 0 or time.time() >= batch_until):
                out = []
                for u in collected:
                    m = u['message']
                    saved = download_media(m, download_dir)
                    r = m.get('reply_to_message')
                    item = {
                        'update_id': u['update_id'],
                        'message_id': m['message_id'],
                        'date': m['date'],
                        'text': text_of(m),
                    }
                    if saved:
                        item['file'] = saved
                    if r:
                        item['reply_to'] = (r.get('text') or r.get('caption') or '').split('\n', 1)[-1][:120]
                    out.append(item)
                if a.json:
                    print(json.dumps(out, ensure_ascii=False), flush=True)
                else:
                    for it in out:
                        line = time.strftime('%F %T', time.localtime(it['date'])) + '  ' + it['text']
                        if 'file' in it:
                            line += f"  [file: {it['file']}]"
                        if 'reply_to' in it:
                            line += f"  (reply to: {it['reply_to']})"
                        print(line, flush=True)
                return
            if deadline is not None and time.time() >= deadline:
                sys.exit(124)
            sleep_or_wake(0.5 if collected else a.interval)
    finally:
        signal.set_wakeup_fd(prev_wakeup_fd)
        for fd in (wake_r, wake_w):
            try:
                os.close(fd)
            except OSError:
                pass


def cmd_send(a):
    if not a.text and sys.stdin.isatty():
        sys.exit('usage: telegram send TEXT  (or pipe text in)')
    say(' '.join(a.text) if a.text else sys.stdin.read())


def cmd_file(a):
    if not os.path.isfile(a.path):
        sys.exit(f'No such file: {a.path}')
    with open(a.path, 'rb') as f:
        send_file(os.path.basename(a.path), f.read(), a.caption or '')


def cmd_ask(a):
    q = say('❓ ' + a.question, a.option)
    qid = q['message_id']

    def close(outcome=None):  # replace the buttons with the outcome so a late tap does nothing
        if a.option:
            row = [[{'text': outcome, 'callback_data': '-'}]] if outcome else []
            quiet('editMessageReplyMarkup', {'chat_id': CHAT, 'message_id': qid, 'reply_markup': {'inline_keyboard': row}})

    end = time.time() + a.timeout
    while time.time() < end:
        try:
            ups = updates()
        except OSError:
            ups = []
        except TgError as e:  # 409: another device polled at the same moment
            if e.code not in (409, 429) and e.code < 500:
                raise
            ups = []
        for u in ups:
            cb, m = u.get('callback_query'), u.get('message')
            if cb and cb['from']['id'] == CHAT and cb.get('message', {}).get('message_id') == qid and cb['data'] != '-':
                answer = a.option[int(cb['data'])]
                quiet('answerCallbackQuery', {'callback_query_id': cb['id']})
                close('✅ ' + answer)
                return print(answer)
            if m and m['chat']['id'] == CHAT:
                r = m.get('reply_to_message')
                # a reply to this question, or a plain message sent after it (replies to other questions are theirs)
                if (r['message_id'] == qid) if r else m['date'] >= q['date']:
                    close()
                    return print(text_of(m))
        time.sleep(3)
    close('⌛ no answer')
    sys.exit(f'No answer within {a.timeout}s')


def cmd_list(a):
    msgs = [u['message'] for u in updates() if u.get('message', {}).get('chat', {}).get('id') == CHAT]
    if not msgs:
        print('No messages from you in the last 24h.')
    for m in msgs[-a.n:]:
        line = time.strftime('%F %T', time.localtime(m['date'])) + '  ' + text_of(m)
        r = m.get('reply_to_message')
        if r:
            line += '   (reply to: ' + (r.get('text') or '').split('\n', 1)[-1][:60] + ')'
        print(line)


def cmd_setup(a):
    global TOKEN, CHAT
    TOKEN = a.token or getpass.getpass('Bot token (from @BotFather): ').strip()
    bot = api('getMe')['username']
    CHAT = a.chat_id
    if not CHAT:
        print(f'Now send any message to @{bot} from your Telegram account (waiting 3 min)...')
        end = time.time() + 180
        while not CHAT and time.time() < end:
            private = [u['message'] for u in api('getUpdates')
                       if u.get('message', {}).get('chat', {}).get('type') == 'private']
            if private:
                CHAT = private[-1]['chat']['id']
                print(f"Got it from {private[-1]['from'].get('first_name', '?')}")
            else:
                time.sleep(2)
        if not CHAT:
            sys.exit('No message arrived.')
    os.makedirs(os.path.dirname(CONFIG), exist_ok=True)
    with open(os.open(CONFIG, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600), 'w') as f:
        json.dump({'token': TOKEN, 'chat_id': CHAT}, f)
    os.chmod(CONFIG, 0o600)
    say('✅ Connected. This machine can reach you here now.')
    print(f'Linked @{bot} to chat {CHAT}, saved {CONFIG}')
    print(f'Other devices: copy that file, or run: telegram setup <token> {CHAT}')


def add_watch_parser(sub, name, help_text):
    s = sub.add_parser(name, help=help_text)
    s.add_argument('--resume', action='store_true', help='continue watching only if this session still owns the watch lock')
    s.add_argument('--owner', default=None, help='session owner id (default: TELEGRAM_OWNER / OPENCODE_SESSION_ID / CLAUDE_SESSION_ID / cwd)')
    s.add_argument('--cursor', default=DEFAULT_CURSOR, help=f'cursor file path (default: {DEFAULT_CURSOR})')
    s.add_argument('--since', type=int, default=None, help='override last seen update_id')
    s.add_argument('-t', '--timeout', type=float, default=0, help='max seconds to wait (0 = forever, default)')
    s.add_argument('--interval', type=float, default=2.5, help='poll interval seconds (default 2.5)')
    s.add_argument('--batch', type=float, default=1.5, help='seconds to batch rapid consecutive messages')
    s.add_argument('--download', default=DEFAULT_INBOX, help=f'directory for incoming media (default: {DEFAULT_INBOX})')
    s.add_argument('--no-download', action='store_true', help='do not download incoming photos/documents/voice')
    s.add_argument('--json', action='store_true', help='print incoming messages (or stop events) as JSON')
    s.set_defaults(fn=cmd_watch)


def main():
    p = argparse.ArgumentParser(
        prog='telegram',
        description='Zero-dependency Telegram bridge for shells & AI agents. Running `telegram` with no subcommand starts `watch`.',
    )
    sub = p.add_subparsers(dest='cmd', required=True)
    add_watch_parser(sub, 'watch', '(default) watch for incoming messages with single-session handoff')
    add_watch_parser(sub, 'wait', argparse.SUPPRESS)  # backward-compatible alias for `watch`
    s = sub.add_parser('stop', help='gracefully stop any active local watcher')
    s.set_defaults(fn=cmd_stop)
    s = sub.add_parser('send', help='send a message (args, or piped stdin); very long text goes as a .txt file')
    s.add_argument('text', nargs='*')
    s.set_defaults(fn=cmd_send)
    s = sub.add_parser('file', help='send a file')
    s.add_argument('path')
    s.add_argument('caption', nargs='?')
    s.set_defaults(fn=cmd_file)
    s = sub.add_parser('ask', help='ask and wait; prints the answer (button or typed reply)')
    s.add_argument('question')
    s.add_argument('-o', '--option', action='append', help='answer button, repeatable')
    s.add_argument('-t', '--timeout', type=int, default=1800, help='seconds to wait (default 1800)')
    s.set_defaults(fn=cmd_ask)
    s = sub.add_parser('list', help='your messages of the last 24h')
    s.add_argument('n', nargs='?', type=int, default=10)
    s.set_defaults(fn=cmd_list)
    s = sub.add_parser('setup', help='save the bot token and link your chat')
    s.add_argument('token', nargs='?')
    s.add_argument('chat_id', nargs='?', type=int)
    s.set_defaults(fn=cmd_setup)

    known = {'watch', 'wait', 'stop', 'send', 'file', 'ask', 'list', 'setup', '-h', '--help'}
    argv = sys.argv[1:]
    if not argv or argv[0] not in known:
        argv = ['watch'] + argv
    a = p.parse_args(argv)

    if a.cmd not in ('setup', 'stop'):
        load()
    try:
        a.fn(a)
    except (TgError, OSError) as e:
        sys.exit(str(e))
    except KeyboardInterrupt:
        sys.exit(130)


if __name__ == '__main__':
    main()
