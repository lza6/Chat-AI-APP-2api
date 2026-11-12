# -*- coding: utf-8 -*-
"""
Chat_AI v241 2API stress test — 12 standard scenarios + optional extreme ladder.
Usage: python stress_test.py [--extreme]
"""
import json
import time
import sys
import threading
import statistics
from urllib.request import Request, build_opener

BASE = 'http://127.0.0.1:8918'
opener = build_opener()

results = []
_lock = threading.Lock()

def rec(name, ok, detail):
    with _lock:
        results.append((name, ok, detail))
        mark = 'PASS' if ok else 'FAIL'
        print(f'[{mark}] {name}: {detail}')

def post(path, body, timeout=180):
    t0 = time.time()
    req = Request(BASE + path, data=json.dumps(body).encode(),
                  headers={'Content-Type': 'application/json'}, method='POST')
    with opener.open(req, timeout=timeout) as r:
        data = json.loads(r.read())
    return data, (time.time() - t0) * 1000

def get(path, timeout=10):
    t0 = time.time()
    with opener.open(BASE + path, timeout=timeout) as r:
        return json.loads(r.read()), (time.time() - t0) * 1000

def stream_chat(prompt):
    body = {'model': 'gpt-4o-mini', 'stream': True,
            'messages': [{'role': 'user', 'content': prompt}]}
    t0 = time.time()
    req = Request(BASE + '/v1/chat/completions', data=json.dumps(body).encode(),
                  headers={'Content-Type': 'application/json'}, method='POST')
    with opener.open(req, timeout=180) as r:
        raw = r.read().decode('utf-8', 'replace')
    dt = (time.time() - t0) * 1000
    acc = ''
    for line in raw.split('\n'):
        line = line.strip()
        if not line.startswith('data:'):
            continue
        payload = line[5:].strip()
        if payload == '[DONE]':
            break
        try:
            j = json.loads(payload)
            acc += j['choices'][0]['delta'].get('content') or ''
        except Exception:
            pass
    return acc, dt

def nonstream_chat(prompt, model='gpt-4o-mini'):
    body = {'model': model, 'stream': False,
            'messages': [{'role': 'user', 'content': prompt}]}
    return post('/v1/chat/completions', body)

def main():
    extreme = '--extreme' in sys.argv

    # 1. health
    try:
        j, dt = get('/health')
        rec('health', j.get('status') == 'ok', f'status={j.get("status")} {dt:.1f}ms')
    except Exception as e:
        rec('health', False, str(e))
        return

    # 2. baseline RTT x5 (non-stream short prompts)
    rts = []
    okc = 0
    for i in range(5):
        try:
            data, dt = nonstream_chat(f'Reply with the single word: OK{i}')
            txt = data['choices'][0]['message']['content']
            if txt.strip():
                okc += 1
            rts.append(dt)
        except Exception as e:
            rts.append(None)
    ok_rts = [r for r in rts if r is not None]
    rec('baseline_5x', okc == 5,
        f'{okc}/5 ok, p50={statistics.median(ok_rts):.0f}ms' if ok_rts else 'all failed')

    # 3. stream test
    try:
        acc, dt = stream_chat('Count from 1 to 5, digits separated by spaces.')
        has = all(str(n) in acc for n in range(1, 6))
        rec('stream_basic', has and len(acc) > 5, f'"{acc[:50]}" {dt:.0f}ms')
    except Exception as e:
        rec('stream_basic', False, str(e))

    # 4. concurrency 5 x10
    def worker5(idx, out):
        try:
            data, dt = nonstream_chat(f'What is {idx}+{idx}? Only the number.')
            out[idx] = (data['choices'][0]['message']['content'].strip(), dt)
        except Exception as e:
            out[idx] = ('ERR:' + str(e)[:60], None)
    out5 = {}
    ts = [threading.Thread(target=worker5, args=(i, out5)) for i in range(10)]
    t0 = time.time()
    for t in ts: t.start()
    for t in ts: t.join()
    wall5 = time.time() - t0
    ok5 = sum(1 for v in out5.values() if not str(v[0]).startswith('ERR') and v[0])
    rt5 = [v[1] for v in out5.values() if v[1]]
    rec('concurrency_5x10', ok5 >= 8,
        f'{ok5}/10 ok, wall={wall5:.1f}s, p50={statistics.median(rt5):.0f}ms' if rt5 else 'all failed')

    # 5. concurrency 10 x20
    def worker10(idx, out):
        try:
            data, dt = nonstream_chat(f'Name the capital of country #{idx}: France, Japan, Brazil, Egypt, Canada, Spain, Kenya, Norway, Peru, Korea, Italy, India, Iran, Chile, Ghana, Nepal, Oman, Qatar, Yemen, Laos'.split(', ')[idx % 20])
            out[idx] = (data['choices'][0]['message']['content'].strip(), dt)
        except Exception as e:
            out[idx] = ('ERR:' + str(e)[:60], None)
    out10 = {}
    ts = [threading.Thread(target=worker10, args=(i, out10)) for i in range(20)]
    t0 = time.time()
    for t in ts: t.start()
    for t in ts: t.join()
    wall10 = time.time() - t0
    ok10 = sum(1 for v in out10.values() if not str(v[0]).startswith('ERR') and v[0])
    rt10 = [v[1] for v in out10.values() if v[1]]
    rec('concurrency_10x20', ok10 >= 16,
        f'{ok10}/20 ok, wall={wall10:.1f}s, p50={statistics.median(rt10):.0f}ms' if rt10 else 'all failed')

    # 6. continuous 15 x2 zero-rate-limit check
    fails = 0
    rate_limited = 0
    rts6 = []
    for rnd in range(2):
        for i in range(15):
            try:
                data, dt = nonstream_chat(f'Say the number {i} in English. One word.')
                txt = data['choices'][0]['message']['content']
                low = txt.lower()
                if '429' in str(data) or 'rate' in low or 'limit' in low:
                    rate_limited += 1
                rts6.append(dt)
            except Exception:
                fails += 1
    rec('continuous_15x2', fails == 0 and rate_limited == 0,
        f'{fails} failures, {rate_limited} rate-limited, p50={statistics.median(rts6):.0f}ms' if rts6 else 'no data')

    # 7. boundary: long prompt 20K chars
    try:
        long_prompt = 'Summarize in one sentence: ' + ('The quick brown fox jumps over the lazy dog. ' * 420)
        data, dt = nonstream_chat(long_prompt)
        txt = data['choices'][0]['message']['content']
        rec('boundary_20k', bool(txt.strip()), f'reply len={len(txt)} {dt:.0f}ms')
    except Exception as e:
        rec('boundary_20k', False, str(e)[:100])

    # 8. boundary: empty message -> 400
    try:
        req = Request(BASE + '/v1/chat/completions',
                      data=json.dumps({'model': 'gpt-4o-mini', 'messages': [{'role': 'user', 'content': ''}]}).encode(),
                      headers={'Content-Type': 'application/json'}, method='POST')
        try:
            opener.open(req, timeout=30)
            rec('boundary_empty', False, 'empty accepted (should 400)')
        except Exception as e:
            code = getattr(e, 'code', None)
            rec('boundary_empty', code == 400, f'HTTP {code}')
    except Exception as e:
        rec('boundary_empty', False, str(e))

    # 9. boundary: bad json -> 400
    try:
        req = Request(BASE + '/v1/chat/completions', data=b'{bad json',
                      headers={'Content-Type': 'application/json'}, method='POST')
        try:
            opener.open(req, timeout=30)
            rec('boundary_badjson', False, 'bad json accepted')
        except Exception as e:
            code = getattr(e, 'code', None)
            rec('boundary_badjson', code == 400, f'HTTP {code}')
    except Exception as e:
        rec('boundary_badjson', False, str(e))

    # 10. boundary: missing messages -> 400
    try:
        req = Request(BASE + '/v1/chat/completions',
                      data=json.dumps({'model': 'gpt-4o-mini'}).encode(),
                      headers={'Content-Type': 'application/json'}, method='POST')
        try:
            opener.open(req, timeout=30)
            rec('boundary_nomsg', False, 'missing messages accepted')
        except Exception as e:
            code = getattr(e, 'code', None)
            rec('boundary_nomsg', code == 400, f'HTTP {code}')
    except Exception as e:
        rec('boundary_nomsg', False, str(e))

    # 11. boundary: unknown model -> routes to begamob fixed model (documented behavior)
    try:
        data, dt = nonstream_chat('Say PING', model='nonexistent-model-xyz')
        txt = data['choices'][0]['message']['content']
        rec('boundary_model', bool(txt.strip()),
            f'unknown model routed ok, reply="{txt[:30]}" (upstream pins gpt-4o-mini)')
    except Exception as e:
        rec('boundary_model', False, str(e)[:100])

    # 12. image generation
    try:
        data, dt = post('/v1/images/generations', {'prompt': 'a small lighthouse on a cliff at dawn'}, timeout=240)
        url = data['data'][0]['url']
        rec('image_gen', url.startswith('http'), f'{url[:60]}... {dt:.0f}ms')
    except Exception as e:
        rec('image_gen', False, str(e)[:100])

    # summary
    npass = sum(1 for _, ok, _ in results if ok)
    print(f'\n===== {npass}/{len(results)} PASS =====')
    if extreme:
        print('--- extreme ladder ---')
        for level in (20, 30, 50):
            outl = {}
            def wl(idx, out):
                try:
                    data, dt = nonstream_chat(f'Reply one word: level{idx}')
                    out[idx] = (True, dt)
                except Exception:
                    out[idx] = (False, None)
            ts = [threading.Thread(target=wl, args=(i, outl)) for i in range(level)]
            t0 = time.time()
            for t in ts: t.start()
            for t in ts: t.join()
            wall = time.time() - t0
            okl = sum(1 for v in outl.values() if v[0])
            rtl = [v[1] for v in outl.values() if v[1]]
            rec(f'extreme_c{level}', okl >= int(level * 0.85),
                f'{okl}/{level} ok, wall={wall:.1f}s, p50={statistics.median(rtl):.0f}ms' if rtl else 'all failed')
        npass2 = sum(1 for _, ok, _ in results if ok)
        print(f'\n===== EXTREME TOTAL {npass2}/{len(results)} PASS =====')

if __name__ == '__main__':
    main()
