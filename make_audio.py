#!/usr/bin/env python3
"""
Generates one German MP3 for every word / example sentence / conjugation line
in index.html, into ./audio/ (file names match what index.html looks for).

    pip install edge-tts          # recommended (Microsoft neural voice, free)
    python make_audio.py          # run next to index.html

Alternative engine (Google, slower):  pip install gTTS ; python make_audio.py --engine gtts
Already-existing files are skipped, so you can stop and re-run any time.
"""
import argparse, asyncio, json, re, sys
from pathlib import Path

# ---- must stay identical to cleanSpeakText() / cyrb53() in index.html ----
def clean(t):
    t = str(t or '')
    t = re.sub(r'\([^)]*\)', ' ', t)
    t = re.sub(r'/e\b', '', t)
    t = re.sub(r'-?/', ' ', t)
    return re.sub(r'\s+', ' ', t).strip()

def _imul(a, b):
    return (a * b) & 0xFFFFFFFF

def cyrb53(s, seed=0):
    h1 = (0xDEADBEEF ^ seed) & 0xFFFFFFFF
    h2 = (0x41C6CE57 ^ seed) & 0xFFFFFFFF
    data = s.encode('utf-16-le')                       # JS charCodeAt = UTF-16 units
    for i in range(0, len(data), 2):
        ch = data[i] | (data[i + 1] << 8)
        h1 = _imul(h1 ^ ch, 2654435761)
        h2 = _imul(h2 ^ ch, 1597334677)
    h1 = _imul(h1 ^ (h1 >> 16), 2246822507) ^ _imul(h2 ^ (h2 >> 13), 3266489909)
    h2 = _imul(h2 ^ (h2 >> 16), 2246822507) ^ _imul(h1 ^ (h1 >> 13), 3266489909)
    h1 &= 0xFFFFFFFF; h2 &= 0xFFFFFFFF
    return 4294967296 * (2097151 & h2) + h1

def b36(n):
    d = '0123456789abcdefghijklmnopqrstuvwxyz'
    if n == 0: return '0'
    out = ''
    while n:
        n, r = divmod(n, 36); out = d[r] + out
    return out

def filename(text):
    return b36(cyrb53(text)) + '.mp3'

def collect_texts(html_path):
    src = Path(html_path).read_text(encoding='utf-8')
    data = json.loads(re.search(r'const DATA = (\{.*\});\n', src).group(1))
    texts = set()
    for items in data.values():
        for it in items:
            texts.add(((it['artikel'] + ' ') if it.get('artikel') else '') + it['de'])
            ex = it.get('example') or {}
            if ex.get('de'): texts.add(ex['de'])
            for pron, key in [('ich','ich'),('du','du'),('er','er'),('wir','wir'),('ihr','ihr'),('sie','sie')]:
                d = (it.get('conj') or {}).get(key)
                if d:
                    texts.add(pron + ' ' + d['form'])
                    if d.get('de'): texts.add(d['de'])
    return sorted({clean(t) for t in texts if clean(t)})

MIN_BYTES = 1500   # a real mp3 is bigger than this; smaller = broken/empty leftover

def is_ok(path):
    return path.exists() and path.stat().st_size >= MIN_BYTES

async def run_edge(todo, out, voice, rate, workers):
    import edge_tts
    sem = asyncio.Semaphore(workers); done = 0; failed = 0
    async def one(text, path):
        nonlocal done, failed
        async with sem:
            tmp = path.with_suffix('.part')
            ok = False
            for attempt in range(5):
                try:
                    await edge_tts.Communicate(text, voice, rate=rate).save(str(tmp))
                    if tmp.exists() and tmp.stat().st_size >= MIN_BYTES:
                        tmp.replace(path); ok = True; break
                except Exception as e:
                    last = e
                await asyncio.sleep(2 * (attempt + 1))
            if not ok:
                failed += 1
                if tmp.exists(): tmp.unlink()
            done += 1
            if done % 100 == 0: print(f'{done}/{len(todo)}  (failed so far: {failed})')
    await asyncio.gather(*(one(t, p) for t, p in todo))
    print(f'finished. failed: {failed}  -> run the script again to retry them')

def run_gtts(todo):
    from gtts import gTTS
    import time
    for i, (text, path) in enumerate(todo, 1):
        for attempt in range(4):
            try:
                gTTS(text, lang='de').save(str(path))
                if path.stat().st_size >= MIN_BYTES: break
            except Exception as e:
                if attempt == 3: print('FAILED:', text, e)
                else: time.sleep(2 * (attempt + 1))
        if i % 50 == 0: print(f'{i}/{len(todo)}')
        time.sleep(0.3)

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--html', default='index.html')
    ap.add_argument('--out', default='audio')
    ap.add_argument('--engine', choices=['edge', 'gtts'], default='edge')
    ap.add_argument('--voice', default='de-DE-KatjaNeural')   # or de-DE-ConradNeural
    ap.add_argument('--rate', default='-8%')                  # a bit slower = clearer for learners
    ap.add_argument('--workers', type=int, default=3)
    a = ap.parse_args()
    out = Path(a.out); out.mkdir(exist_ok=True)
    texts = collect_texts(a.html)
    for f in list(out.glob('*.mp3')) + list(out.glob('*.part')):
        if f.stat().st_size < MIN_BYTES: f.unlink()      # remove broken leftovers from failed runs
    todo = [(t, out / filename(t)) for t in texts if not is_ok(out / filename(t))]
    print(f'{len(texts)} texts, {len(todo)} to generate')
    if not todo: return
    if a.engine == 'edge': asyncio.run(run_edge(todo, out, a.voice, a.rate, a.workers))
    else: run_gtts(todo)
    print('done ->', out.resolve())

if __name__ == '__main__':
    main()
