"""운영 키를 노출하지 않고 API 요청 형식을 점검하는 수동 진단."""
import logging
from . import alerts, analysis


def main():
    logging.basicConfig(level=logging.INFO, format='%(message)s')
    state=alerts.read_state()
    if state is None:
        raise RuntimeError('먼저 수집을 실행하세요')
    payload = {'contents': [{'role': 'user', 'parts': [{'text': 'Return only JSON: {"decisions":[]}'}]}],
               'generationConfig': {'responseMimeType': 'application/json', 'maxOutputTokens': 512,
                                    'thinkingConfig': {'thinkingLevel': 'low'}}}
    def validate(data):
        if data != {'decisions': []}:
            raise ValueError('진단 응답 형식 오류')
        return data
    try:
        _, usage, attempts, _ = analysis.complete(payload, validate, state, alerts.save_state)
        print('API OK', usage, 'attempts', attempts, flush=True)
    except Exception as exc:
        print('API FAILED', type(exc).__name__, flush=True)
        return 1
    return 0

if __name__=='__main__':
    raise SystemExit(main())
