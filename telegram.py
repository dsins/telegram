#!/usr/bin/env python3
"""Reach me on Telegram from any shell or Claude Code session: notify, send files, ask and wait.

Config: ~/.config/ds/telegram.json {"token", "chat_id"}, written by `telegram setup`
(or env TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID). Messages are headed with "host · dir"
(override: TELEGRAM_LABEL) so it is clear which machine and project is talking.

Nothing is stored locally and updates are never confirmed (Telegram keeps them 24h),
so any number of devices can share one bot. Only messages from the linked chat count.
"""
import argparse
import getpass
import json
import os
import socket
import sys
import time
import urllib.error
import urllib.request
import uuid

API = os.environ.get('TELEGRAM_API', 'https://api.telegram.org')
CONFIG = os.path.expanduser(os.environ.get('DS_TELEGRAM_CONFIG', '~/.config/ds/telegram.json'))
LABEL = os.environ.get('TELEGRAM_LABEL') or f'{socket.gethostname()} · {os.path.basename(os.getcwd())}'
MAX_PARTS = 3  # longer text goes as a .txt file instead of a burst of messages
TOKEN = CHAT = None

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


def read_cursor(path):
    try:
        with open(path) as f:
            return int(json.load(f).get('last_update_id', 0))
    except (OSError, ValueError, TypeError):
        return None


def write_cursor(path, update_id):
    d = os.path.dirname(path)
    if d:
        os.makedirs(d, exist_ok=True)
    tmp = f'{path}.{os.getpid()}.tmp'
    with open(tmp, 'w') as f:
        json.dump({'last_update_id': int(update_id), 'ts': int(time.time())}, f)
    os.replace(tmp, path)


def cmd_wait(a):
    """Block until one or more new messages arrive from the linked chat; resilient to 409/network blips."""
    cursor_path = os.path.expanduser(a.cursor)
    last_id = a.since if a.since is not None else read_cursor(cursor_path)

    def fetch_safe():
        backoff = a.interval
        while True:
            try:
                return updates()
            except OSError:
                time.sleep(backoff)
                backoff = min(backoff * 1.5, 15.0)
            except TgError as e:
                if e.code not in (409, 429) and e.code < 500:
                    raise
                time.sleep(backoff)
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
                saved = download_media(m, a.download)
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
                print(json.dumps(out, ensure_ascii=False))
            else:
                for it in out:
                    line = time.strftime('%F %T', time.localtime(it['date'])) + '  ' + it['text']
                    if 'file' in it:
                        line += f"  [file: {it['file']}]"
                    if 'reply_to' in it:
                        line += f"  (reply to: {it['reply_to']})"
                    print(line)
            return
        if deadline is not None and time.time() >= deadline:
            sys.exit(124)
        time.sleep(0.5 if collected else a.interval)


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


def main():
    p = argparse.ArgumentParser(prog='telegram', description='Reach me on Telegram: notify, send files, ask and wait for an answer.')
    sub = p.add_subparsers(dest='cmd', required=True)
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
    s = sub.add_parser('wait', help='wait continuously for new incoming messages (persists cursor, retries errors)')
    s.add_argument('--cursor', default='~/.local/state/ds-telegram/cursor.json', help='cursor file path')
    s.add_argument('--since', type=int, default=None, help='override last seen update_id')
    s.add_argument('-t', '--timeout', type=float, default=0, help='max seconds to wait (0 = forever, default)')
    s.add_argument('--interval', type=float, default=2.5, help='poll interval seconds (default 2.5)')
    s.add_argument('--batch', type=float, default=1.5, help='seconds to batch rapid consecutive messages')
    s.add_argument('--download', default='', help='directory to save incoming photos/documents/voice')
    s.add_argument('--json', action='store_true', help='print incoming messages as JSON')
    s.set_defaults(fn=cmd_wait)
    s = sub.add_parser('setup', help='save the bot token and link your chat')
    s.add_argument('token', nargs='?')
    s.add_argument('chat_id', nargs='?', type=int)
    s.set_defaults(fn=cmd_setup)
    a = p.parse_args()

    if a.cmd != 'setup':
        load()
    try:
        a.fn(a)
    except (TgError, OSError) as e:
        sys.exit(str(e))
    except KeyboardInterrupt:
        sys.exit(130)


if __name__ == '__main__':
    main()
