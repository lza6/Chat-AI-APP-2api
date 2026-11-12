# -*- coding: utf-8 -*-
"""
Chat_AI v241.0 (com.msc.ai.chat.bot.aichat) reverse-engineered multi-channel 2API
Ports:
  begamob v2  - local HS256 JWT (secret recovered from APK) + SSE stream -> main TEXT
  goatchat    - free device registration -> permanent JWT -> Journey AI IMAGE gen
  vulcan      - free device_id JWT (30min) -> fallback TEXT (same family as AI ChatBot v10)
OpenAI-compatible endpoints:
  POST /v1/chat/completions      (stream: true/false)
  POST /v1/images/generations
  GET  /v1/models
  GET  /health /stats
  GET  / (demo.html)
"""
import json
import time
import uuid
import hmac
import hashlib
import base64
import threading
import logging
import os
import re
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from urllib.request import Request, build_opener, ProxyHandler
from urllib.error import HTTPError, URLError

PORT = int(os.environ.get('CHAT_AI_PORT', '8918'))
BASE = os.path.dirname(os.path.abspath(__file__))

# Outbound proxy (optional). Set CHAT_AI_PROXY_HOST empty to connect directly.
_proxy_host = os.environ.get('CHAT_AI_PROXY_HOST', '')
_proxy_port = os.environ.get('CHAT_AI_PROXY_PORT', '10808')
if _proxy_host:
    opener = build_opener(ProxyHandler({'https': f'http://{_proxy_host}:{_proxy_port}',
                                        'http': f'http://{_proxy_host}:{_proxy_port}'}))
else:
    opener = build_opener()

logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')
log = logging.getLogger('chatai241')

# ---------------------------------------------------------------- begamob v2
BG_SECRET = 'stteam-ikameglobal-chatapiopenai'
BG_BUNDLE = 'com.chat.chatai.chatbot.aichatbot'
BG_VER = '1.2.2'
BG_OSVER = '29'
BG_URL = 'https://chat-ai.begamob.com/api/v2/chatStream'

def b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b'=').decode()

def bg_jwt() -> str:
    hdr = b64url(b'{"alg":"HS256","typ":"JWT"}')
    now = int(time.time())
    payload = json.dumps({
        'iat': now, 'exp': now + 900,
        'bundleId': BG_BUNDLE, 'os': 'Android',
        'versionApp': BG_VER,
        'timezone': 'Asia/Shanghai'
    }, separators=(',', ':'))
    pl = b64url(payload.encode())
    sig = hmac.new(BG_SECRET.encode(), f'{hdr}.{pl}'.encode(), hashlib.sha256).digest()
    return f'{hdr}.{pl}.{b64url(sig)}'

_BG_DEV = ''.join('0123456789ABCDEF'[i % 16] for i in range(64))
_BG_LOCK = threading.Lock()

def bg_headers() -> dict:
    with _BG_LOCK:
        jwt = bg_jwt()
    uid = uuid.uuid4().hex
    return {
        'Authorization': f'Bearer {jwt}',
        'user-header': f'bundleId:{BG_BUNDLE}/versionApp:{BG_VER}/OS:Android/osVersion:{BG_OSVER}/{uid}/{_BG_DEV}',
        'Content-Type': 'application/json',
    }

def bg_chat_stream(messages, web_search=False):
    """Yield text chunks from begamob v2 SSE. messages = OpenAI-format list."""
    out = []
    for m in messages:
        content = m.get('content')
        if isinstance(content, list):
            texts = [p.get('text', '') for p in content if isinstance(p, dict) and p.get('type') == 'text']
            content = ''.join(texts)
        out.append({'role': m.get('role', 'user'), 'content': [{'type': 'text', 'text': content}]})
    body = {
        'messages': out,
        'model': 'gpt-4o-mini',
        'response_length': '',
        'response_tone': '',
        'topic_type': '',
        'image_and_analytic': True,
    }
    if web_search:
        body['tools'] = ['search_web']
    req = Request(BG_URL, data=json.dumps(body).encode(), headers=bg_headers(), method='POST')
    with opener.open(req, timeout=180) as resp:
        for raw in resp:
            line = raw.decode('utf-8', 'replace').strip()
            if not line:
                continue
            line = re.sub(r'^data:\s*', '', line)
            try:
                j = json.loads(line)
            except Exception:
                continue
            d = j.get('data') or {}
            c = d.get('content') or ''
            if c:
                yield c
            webs = d.get('webs')
            if webs:
                out_web = [{'title': w.get('title', ''), 'uri': w.get('uri', '')} for w in webs]
                yield '\n[web_search_source]\n' + json.dumps(out_web, ensure_ascii=False)

# ---------------------------------------------------------------- goatchat IMAGE
GC_AUTH_URL = 'https://api.goatchat.ai/v1/auth'
GC_IMG_BOT = 'd31f578d-b9b3-40c9-aa17-740bbc20c272'  # Journey AI (IMAGE)
_gc_lock = threading.Lock()
_gc_token = None
_gc_time = 0

def gc_token() -> str:
    global _gc_token, _gc_time
    with _gc_lock:
        if _gc_token and time.time() - _gc_time < 30 * 24 * 3600:
            return _gc_token
        body = {
            'osName': 'android', 'osVersion': '14',
            'userDevice': {'buildNumber': 51, 'appVersionName': '1.4.1',
                           'deviceId': str(uuid.uuid4()) + '0', 'deviceLocale': 'en',
                           'deviceManufacturer': 'Google', 'deviceModel': 'Pixel 8',
                           'operatorName': 'T-Mobile', 'osName': 'android', 'osVersion': '1.4.1',
                           'deviceType': 'PHONE'},
            'userId': str(uuid.uuid4())
        }
        req = Request(GC_AUTH_URL, data=json.dumps(body).encode(),
                      headers={'Content-Type': 'application/json'}, method='POST')
        with opener.open(req, timeout=60) as resp:
            j = json.loads(resp.read())
        _gc_token = j['data']['token']
        _gc_time = time.time()
        return _gc_token

def gc_create_chat(bot_id) -> str:
    t = gc_token()
    req = Request(f'https://api.goatchat.ai/v1/bots/{bot_id}/chat',
                  headers={'authorization': 'Bearer ' + t}, method='GET')
    with opener.open(req, timeout=60) as resp:
        j = json.loads(resp.read())
    return j['data']['id']

def gc_image(prompt: str) -> dict:
    t = gc_token()
    chat_id = gc_create_chat(GC_IMG_BOT)
    req = Request(f'https://api.goatchat.ai/v1/chats/{chat_id}/message',
                  data=json.dumps({'message': prompt}).encode(),
                  headers={'authorization': 'Bearer ' + t, 'content-type': 'application/json'},
                  method='POST')
    with opener.open(req, timeout=180) as resp:
        j = json.loads(resp.read())
    msgs = j['data']['messages']
    bot = next((m for m in msgs if m['sender'] == 'BOT'), None)
    if bot and bot.get('messageImages'):
        img = bot['messageImages'][0]
        return {'url': img['imageUrl'], 'revised_prompt': bot.get('text', ''),
                'width': img.get('width'), 'height': img.get('height')}
    raise RuntimeError(f'goatchat no image: {json.dumps(j)[:200]}')

# ---------------------------------------------------------------- vulcan fallback
VULCAN_TOKEN_URL = 'https://api.vulcanlabs.co/smith-auth/api/v1/token'
VULCAN_CHAT_URL = 'https://api.vulcanlabs.co/smith-v2/api/v7/chat_android'
_v_lock = threading.Lock()
_v_token = None
_v_exp = 0

def vulcan_token() -> str:
    global _v_token, _v_exp
    with _v_lock:
        if _v_token and time.time() < _v_exp - 60:
            return _v_token
        body = {'device_id': str(uuid.uuid4()), 'order_id': '', 'product_id': '',
                'purchase_token': '', 'subscription_id': ''}
        req = Request(VULCAN_TOKEN_URL, data=json.dumps(body).encode(),
                      headers={'Content-Type': 'application/json'}, method='POST')
        with opener.open(req, timeout=60) as resp:
            j = json.loads(resp.read())
        _v_token = j['AccessToken']
        _v_exp = time.time() + 25 * 60
        return _v_token

def vulcan_chat(messages):
    t = vulcan_token()
    msgs = [{'role': m.get('role', 'user'),
             'content': m.get('content') if isinstance(m.get('content'), str)
             else ''.join(p.get('text', '') for p in m.get('content') or [] if isinstance(p, dict))}
            for m in messages]
    body = {'messages': msgs, 'model': 'gpt-4o-mini'}
    req = Request(VULCAN_CHAT_URL, data=json.dumps(body).encode(),
                  headers={'authorization': 'Bearer ' + t,
                           'content-type': 'application/json; charset=UTF-8',
                           'user-agent': 'Chat Smith Android, Version 3.8.1(615)'},
                  method='POST')
    with opener.open(req, timeout=180) as resp:
        raw = resp.read().decode('utf-8', 'replace')
    j = json.loads(raw)
    ch = j.get('choices') or []
    if ch:
        # upstream v7: "Message" is a dict {role, content}; some variants use lowercase str content
        msg = ch[0].get('Message')
        if isinstance(msg, dict):
            return msg.get('content', '') or ''
        if isinstance(msg, str):
            return msg
        m2 = ch[0].get('message')
        if isinstance(m2, dict):
            return m2.get('content', '') or ''
        if isinstance(m2, str):
            return m2
    return ''

# ---------------------------------------------------------------- stats
STATS = {
    'start': time.time(),
    'begamob_ok': 0, 'begamob_fail': 0,
    'vulcan_ok': 0, 'vulcan_fail': 0,
    'goatchat_ok': 0, 'goatchat_fail': 0,
    'total_req': 0,
}
_stats_lock = threading.Lock()

def bump(k, n=1):
    with _stats_lock:
        STATS[k] = STATS.get(k, 0) + n

# ---------------------------------------------------------------- handler
class Handler(BaseHTTPRequestHandler):
    protocol_version = 'HTTP/1.1'

    def log_message(self, fmt, *args):
        pass  # quiet under load

    def _json(self, code, obj):
        data = json.dumps(obj, ensure_ascii=False).encode()
        self.send_response(code)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Content-Length', str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _sse_headers(self):
        self.send_response(200)
        self.send_header('Content-Type', 'text/event-stream; charset=utf-8')
        self.send_header('Cache-Control', 'no-cache')
        self.send_header('Connection', 'close')
        self.end_headers()

    def _sse(self, obj):
        self.wfile.write(b'data: ' + json.dumps(obj, ensure_ascii=False).encode() + b'\n\n')
        self.wfile.flush()

    def do_GET(self):
        p = self.path.split('?')[0]
        if p == '/' or p == '/index.html':
            data = open(os.path.join(BASE, 'demo.html'), 'rb').read()
            self.send_response(200)
            self.send_header('Content-Type', 'text/html; charset=utf-8')
            self.send_header('Content-Length', str(len(data)))
            self.end_headers()
            self.wfile.write(data)
        elif p == '/health':
            self._json(200, {'status': 'ok', 'channels': ['begamob_v2', 'goatchat_image', 'vulcan_fallback']})
        elif p == '/stats':
            with _stats_lock:
                s = dict(STATS)
            s.pop('start', None)
            self._json(200, {'uptime_s': int(time.time() - STATS['start']), **s})
        elif p == '/v1/models':
            self._json(200, {'object': 'list', 'data': [
                {'id': 'gpt-4o-mini', 'object': 'model', 'owned_by': 'begamob'},
                {'id': 'gpt-4o-mini-search', 'object': 'model', 'owned_by': 'begamob'},
                {'id': 'goatchat-image', 'object': 'model', 'owned_by': 'goatchat'},
            ]})
        else:
            self._json(404, {'error': 'not found'})

    def do_POST(self):
        p = self.path.split('?')[0]
        if p == '/v1/chat/completions':
            self._chat()
        elif p == '/v1/images/generations':
            self._image()
        else:
            self._json(404, {'error': 'not found'})

    # -- OpenAI-compatible chat --
    def _chat(self):
        bump('total_req')
        n = int(self.headers.get('Content-Length', 0))
        try:
            body = json.loads(self.rfile.read(n))
        except Exception:
            return self._json(400, {'error': {'message': 'invalid json'}})
        messages = body.get('messages')
        if not messages:
            return self._json(400, {'error': {'message': 'messages required'}})
        model = body.get('model', 'gpt-4o-mini')
        stream = bool(body.get('stream'))
        web = bool(body.get('web_search')) or model == 'gpt-4o-mini-search'
        chat_id = f'chatcmpl-{uuid.uuid4().hex[:24]}'
        created = int(time.time())
        first_chunk_sent = [False]

        def as_text(c):
            if isinstance(c, str):
                return c
            if isinstance(c, list):
                return ''.join(p.get('text', '') for p in c if isinstance(p, dict))
            return json.dumps(c, ensure_ascii=False)

        prompt_txt = ''.join(as_text(m.get('content', '')) for m in messages)
        if not prompt_txt.strip():
            return self._json(400, {'error': {'message': 'empty prompt'}})

        try:
            if stream:
                self._sse_headers()
                first = True
                try:
                    for chunk in bg_chat_stream(messages, web_search=web):
                        first_chunk_sent[0] = True
                        if first:
                            self._sse({'id': chat_id, 'object': 'chat.completion.chunk', 'created': created,
                                       'model': model, 'choices': [{'index': 0, 'delta': {'role': 'assistant'}, 'finish_reason': None}]})
                            first = False
                        self._sse({'id': chat_id, 'object': 'chat.completion.chunk', 'created': created,
                                   'model': model, 'choices': [{'index': 0, 'delta': {'content': chunk}, 'finish_reason': None}]})
                    bump('begamob_ok')
                except (HTTPError, URLError, TimeoutError, OSError) as e:
                    bump('begamob_fail')
                    if first_chunk_sent[0]:
                        # partial stream already delivered; close gracefully
                        self._sse({'id': chat_id, 'object': 'chat.completion.chunk', 'created': created,
                                   'model': model, 'choices': [{'index': 0, 'delta': {}, 'finish_reason': 'stop'}]})
                        self._sse('[DONE]')
                        return
                    txt = vulcan_chat(messages)
                    bump('vulcan_ok')
                    self._sse({'id': chat_id, 'object': 'chat.completion.chunk', 'created': created,
                               'model': model, 'choices': [{'index': 0, 'delta': {'content': txt}, 'finish_reason': None}]})
                self._sse({'id': chat_id, 'object': 'chat.completion.chunk', 'created': created,
                           'model': model, 'choices': [{'index': 0, 'delta': {}, 'finish_reason': 'stop'}]})
                self._sse('[DONE]')
            else:
                try:
                    text = ''.join(bg_chat_stream(messages, web_search=web))
                    bump('begamob_ok')
                except (HTTPError, URLError, TimeoutError, OSError):
                    bump('begamob_fail')
                    text = vulcan_chat(messages)
                    bump('vulcan_ok')
                self._json(200, {
                    'id': chat_id, 'object': 'chat.completion', 'created': created,
                    'model': model,
                    'choices': [{'index': 0, 'message': {'role': 'assistant', 'content': text}, 'finish_reason': 'stop'}],
                    'usage': {'prompt_tokens': len(prompt_txt), 'completion_tokens': len(text),
                              'total_tokens': len(prompt_txt) + len(text)},
                })
        except Exception as e:
            # begamob failed -> vulcan fallback (non-stream semantics preserved)
            try:
                txt = vulcan_chat(messages)
                bump('vulcan_ok'); bump('begamob_fail')
                payload = {
                    'id': chat_id, 'object': 'chat.completion', 'created': created, 'model': model,
                    'choices': [{'index': 0, 'message': {'role': 'assistant', 'content': txt}, 'finish_reason': 'stop'}],
                    'usage': {'prompt_tokens': len(prompt_txt), 'completion_tokens': len(txt),
                              'total_tokens': len(prompt_txt) + len(txt)},
                }
                if stream and first_chunk_sent[0]:
                    pass  # stream already started; client sees error below
                else:
                    self._json(200, payload)
            except Exception as e2:
                bump('vulcan_fail'); bump('begamob_fail')
                try:
                    self._json(502, {'error': {'message': f'all channels failed: {e} / {e2}'}})
                except Exception:
                    pass

    # -- goatchat image --
    def _image(self):
        bump('total_req')
        n = int(self.headers.get('Content-Length', 0))
        try:
            body = json.loads(self.rfile.read(n))
        except Exception:
            return self._json(400, {'error': {'message': 'invalid json'}})
        prompt = body.get('prompt', '').strip()
        if not prompt:
            return self._json(400, {'error': {'message': 'prompt required'}})
        try:
            img = gc_image(prompt)
            bump('goatchat_ok')
            self._json(200, {
                'created': int(time.time()),
                'data': [{'url': img['url'], 'revised_prompt': img['revised_prompt']}],
                'meta': {'width': img['width'], 'height': img['height'], 'channel': 'goatchat-journey'},
            })
        except Exception as e:
            bump('goatchat_fail')
            self._json(502, {'error': {'message': f'goatchat image failed: {e}'}})

if __name__ == '__main__':
    srv = ThreadingHTTPServer(('127.0.0.1', PORT), Handler)
    log.info(f'Chat_AI v241 2API demo server on http://127.0.0.1:{PORT}')
    srv.serve_forever()
