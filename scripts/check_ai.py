"""운영 키를 노출하지 않고 API 요청 형식을 점검하는 수동 진단."""
import copy
import logging
from . import alerts, analysis, screening


def main():
    logging.basicConfig(level=logging.INFO, format='%(message)s')
    state=alerts.read_state()
    if state is None:
        raise RuntimeError('먼저 수집을 실행하세요')
    base={'contents':[{'role':'user','parts':[{'text':'Return only JSON: {"decisions":[]}'}]}],
          'generationConfig':{'responseMimeType':'application/json','maxOutputTokens':512}}
    thought=copy.deepcopy(base);thought['generationConfig']['thinkingConfig']={'thinkingLevel':'low'}
    def portable(value):
        if isinstance(value, dict):
            return {k: portable(v) for k, v in value.items() if k != 'additionalProperties'}
        if isinstance(value, list):
            return [portable(v) for v in value]
        return value
    schema=copy.deepcopy(thought);schema['generationConfig']['responseJsonSchema']=portable(screening.SCHEMA)
    legacy=copy.deepcopy(thought);legacy['generationConfig']['responseSchema']=portable(screening.SCHEMA)
    variants=[('portable_json_schema',schema), ('portable_response_schema',legacy)]
    for name,payload in variants:
        try:
            result,usage,attempts,model=analysis.complete(payload,lambda d:d,state,alerts.save_state)
            print(name,'OK',usage,flush=True)
        except Exception as exc:
            print(name,'FAILED',type(exc).__name__,flush=True)
    return 0

if __name__=='__main__':
    raise SystemExit(main())
