"""수동 진단: 같은 3.8 모델/키에서 API 경로만 비교. 뉴스 전송 없음."""
import json
import time
import requests
from . import alerts
from .config import env
from .models import now_kst


def main():
    if env('GEMINI_FREE_TIER_CONFIRMED') != 'true':
        raise RuntimeError('무료 등급 확인 필요')
    keys = list(dict.fromkeys(k for k in [env('GEMINI_API_KEY'), env('GEMINI_API_KEY_BACKUP')] if k))
    state = alerts.read_state()
    if not keys or state is None:
        raise RuntimeError('운영 키/상태 없음')
    ledger = state.setdefault('ai', {})
    start = int(ledger.get('next_key', 0)) % len(keys)
    model = 'gemini-3.8-flash'
    results = []
    format_check = env('COMPARE_FORMAT') == 'true'
    routes = ('json_mode', 'plain_json') if format_check else ('generateContent', 'interactions')
    for route in routes:
        for offset in range(len(keys)):
            index = (start + offset) % len(keys)
            today = now_kst().date().isoformat()
            if ledger.get('date') != today:
                ledger.update(date=today, requests=0, usage={})
            if ledger.get('requests', 0) >= 40:
                raise RuntimeError('하루 40회 상한 도달')
            ledger['requests'] = ledger.get('requests', 0) + 1
            ledger['next_key'] = (index + 1) % len(keys)
            alerts.save_state(state)
            if route != 'interactions':
                url = f'https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent'
                payload = {'contents': [{'parts': [{'text': 'Say OK.'}]}], 'generationConfig': {'maxOutputTokens': 512}}
                if format_check:
                    payload['contents'][0]['parts'][0]['text'] = 'Return only JSON: {"decisions":[]}'
                    payload['generationConfig']['thinkingConfig'] = {'thinkingLevel': 'low'}
                    if route == 'json_mode':
                        payload['generationConfig']['responseMimeType'] = 'application/json'
            else:
                url = 'https://generativelanguage.googleapis.com/v1beta/interactions'
                payload = {'model': model, 'input': 'Say OK.', 'store': False,
                           'generation_config': {'max_output_tokens': 512, 'thinking_level': 'low'}}
            started = time.monotonic()
            try:
                r = requests.post(url, headers={'x-goog-api-key': keys[index]}, json=payload, timeout=(10, 60))
                data = r.json()
                status = data.get('error', {}).get('status', data.get('error', {}).get('code', ''))
                # Do not print raw response, headers, keys, or exception URLs.
                status = str(status)[:60] if str(status).replace('_', '').isalnum() else ''
                print(json.dumps({'route': route, 'key_slot': index+1, 'http': r.status_code,
                                  'error_code': status, 'seconds': round(time.monotonic()-started, 2),
                                  'completed': data.get('status') == 'completed' if route == 'interactions' else bool(data.get('candidates'))}), flush=True)
                usage = data.get('usage', {}) if route == 'interactions' else data.get('usageMetadata', {})
                mapping = {'total_input_tokens': 'promptTokenCount', 'total_output_tokens': 'candidatesTokenCount',
                           'total_thought_tokens': 'thoughtsTokenCount', 'total_tokens': 'totalTokenCount'}
                for k, v in usage.items():
                    target = mapping.get(k, k)
                    if target in mapping.values() and type(v) is int and v >= 0:
                        ledger.setdefault('usage', {})[target] = ledger.get('usage', {}).get(target, 0)+v
                alerts.save_state(state)
                results.append(r.ok)
            except (requests.RequestException, ValueError) as exc:
                print(route, 'key_slot', index+1, type(exc).__name__, flush=True)
                results.append(False)
            time.sleep(15)
    return 0 if all(results) else 1


if __name__ == '__main__':
    raise SystemExit(main())
