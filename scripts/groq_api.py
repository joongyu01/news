"""Free-tier-only Groq adapter. No paid fallback and no unbounded retries."""
import json
import logging
import requests
from .config import env
from .models import now_kst

MODEL = 'qwen/qwen3.8-27b'
MAX_INPUT_BYTES = 6000
MAX_OUTPUT = 1800
FREE_TOKENS = 200_000
MORNING_RESERVE = MAX_INPUT_BYTES + MAX_OUTPUT


def enabled():
    return env('AI_PROVIDER') == 'groq'


def complete(payload, validator, state, persist, *, morning=False):
    if env('GROQ_FREE_TIER_CONFIRMED') != 'true' or not env('GROQ_API_KEY'):
        raise RuntimeError('Groq 무료 등급 확인과 API 키가 필요합니다')
    messages = []
    system = '\n'.join(p.get('text', '') for p in payload.get('systemInstruction', {}).get('parts', []))
    if system:
        messages.append({'role': 'system', 'content': system})
    for c in payload.get('contents', []):
        messages.append({'role': 'user', 'content': '\n'.join(p.get('text', '') for p in c.get('parts', []))})
    size = sum(len(m['content'].encode('utf-8')) for m in messages) + 100
    if size > MAX_INPUT_BYTES:
        logging.getLogger(__name__).warning('Groq input size %d exceeds %d bytes', size, MAX_INPUT_BYTES)
        raise RuntimeError('Groq 무료 요청 입력 상한 초과')
    state = state if state is not None else {}
    ledger = state.setdefault('groq_ai', {})
    now = now_kst()
    day = now.date().isoformat()
    # Keep a rolling window across midnight, so evening screening cannot
    # consume the following morning's allowance. This is a local estimate;
    # the provider remains authoritative about quota and its reset time.
    if 'recent' not in ledger:
        ledger['recent'] = ([{'at': now.timestamp(), 'tokens': ledger['reserved_tokens']}]
                            if ledger.get('reserved_tokens', 0) else [])
    ledger['recent'] = [r for r in ledger['recent'] if r['at'] > now.timestamp() - 86400]
    if ledger.get('date') != day:
        ledger.update(date=day, requests=0, reserved_tokens=0, usage={})
    reserve = size + MAX_OUTPUT
    ceiling = FREE_TOKENS if morning else FREE_TOKENS - MORNING_RESERVE
    if ledger['requests'] >= (40 if morning else 39) or sum(r['tokens'] for r in ledger['recent']) + reserve > ceiling:
        raise RuntimeError('Groq 일일 무료 보호 상한 도달')
    ledger['requests'] += 1
    ledger['reserved_tokens'] += reserve
    reservation = {'at': now.timestamp(), 'tokens': reserve}
    ledger['recent'].append(reservation)
    if persist:
        persist(state)  # Reserve before sending; unknown failures keep the reservation.
    stage = 'request'
    try:
        response = requests.post('https://api.groq.com/openai/v1/chat/completions',
            headers={'Authorization': 'Bearer '+env('GROQ_API_KEY'), 'Content-Type': 'application/json'},
            json={'model': MODEL, 'messages': messages, 'response_format': {'type': 'json_object'},
                  'reasoning_effort': 'none', 'max_completion_tokens': MAX_OUTPUT}, timeout=(10, 90))
        if not response.ok:
            logging.getLogger(__name__).warning('Groq HTTP %d (자동 재시도 없음)', response.status_code)
            raise RuntimeError('Groq API 응답 실패')
        stage = 'response_json'
        body = response.json()
        usage = {k:v for k,v in body.get('usage', {}).items()
                 if k in ('prompt_tokens', 'completion_tokens', 'total_tokens') and type(v) is int and v >= 0}
        if 'total_tokens' in usage:
            ledger['reserved_tokens'] += usage['total_tokens'] - reserve
            reservation['tokens'] = usage['total_tokens']
        for k,v in usage.items():
            ledger['usage'][k] = ledger['usage'].get(k,0)+v
        if persist:
            persist(state)
        logging.getLogger(__name__).info('Groq response usage: %s', json.dumps(usage))
        stage = 'finish_reason'
        choice = body['choices'][0]
        if choice.get('finish_reason') != 'stop':
            raise ValueError('Incomplete response')
        stage = 'content_json'
        data = json.loads(choice['message']['content'])
        stage = 'validation'
        result = validator(data)
        logging.getLogger(__name__).info('Groq API OK · %s · %s', MODEL, json.dumps(usage))
        return result, usage, 1, 'groq/'+MODEL
    except (requests.RequestException, ValueError, KeyError, TypeError, IndexError, RuntimeError):
        logging.getLogger(__name__).warning('Groq analysis failed at %s', stage)
        raise RuntimeError('Groq 분석 실패; 유료 모델 대체 없음') from None
