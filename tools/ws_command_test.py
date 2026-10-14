import asyncio
import json
import requests
import websockets

LOGIN_URL = 'http://127.0.0.1:8010/api/auth/login'
TOKEN = 'demo-panel-token'

COMMANDS = [
    'Masaüstündeki klasörleri listele',
    'Geçerli dizindeki dosyaların sayısını söyle',
    'Rastgele bir dosya oluştur ve adını söyle',
]


def assert_expected_response(payload, sent_command):
    # Robust heuristic checks: accept 'message', 'task_update', and 'task_finished'
    t = payload.get('type')
    # handle FastAPI websocket message events with nested payloads
    if t == 'message':
        body = payload.get('payload', {})
        # assistant messages include `content`
        content = body.get('content')
        if content and isinstance(content, str) and content.strip():
            return True
        return False

    if t in {'task_update', 'task_finished'}:
        body = payload.get('payload') or {}
        # support both direct summary field and nested message/result keys
        summary = body.get('summary') or body.get('result') or body.get('output')
        # some implementations include message text under 'message' or 'details'
        if summary and isinstance(summary, str) and summary.strip():
            return True
        details = body.get('details')
        if details and isinstance(details, list) and any(isinstance(d, str) and d.strip() for d in details):
            return True
        return False

    return False


async def send_commands():
    r = requests.post(LOGIN_URL, json={'token': TOKEN}, timeout=10)
    print('LOGIN_STATUS', r.status_code)
    print('LOGIN_BODY', r.text)
    r.raise_for_status()
    session_id = r.json()['session_id']
    uri = f'ws://127.0.0.1:8010/ws/frontend?session_id={session_id}'
    async with websockets.connect(uri, ping_interval=None) as ws:
        print('CONNECTED')
        # consume initial event(s)
        try:
            first = await asyncio.wait_for(ws.recv(), timeout=2)
            print('FIRST', first)
        except Exception:
            pass
        for cmd in COMMANDS:
            print('\nSENDING:', cmd)
            await ws.send(json.dumps({'type': 'chat_message', 'message': cmd}))
            # gather events for this command
            for _ in range(10):
                try:
                    msg = await asyncio.wait_for(ws.recv(), timeout=10)
                except asyncio.TimeoutError:
                    print('No more messages for command')
                    break
                print('EVENT', msg)
                try:
                    payload = json.loads(msg)
                except Exception:
                    continue
                try:
                    ok = assert_expected_response(payload, cmd)
                    if ok and payload.get('type') == 'task_finished':
                        print('Command finished OK')
                        break
                except AssertionError as e:
                    print('Assertion failed for response:', e)


if __name__ == '__main__':
    asyncio.run(send_commands())
