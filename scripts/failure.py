"""AI 실행 실패를 소유자에게 알린다. 같은 단계는 6시간에 한 번."""
import argparse
import logging
from datetime import datetime, timedelta
from . import alerts
from .config import env
from .models import now_kst
from .notify import send_telegram


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument('--stage', choices=['screening', 'morning'], required=True)
    args = parser.parse_args(argv)
    now, state = now_kst(), None
    try:
        state = alerts.read_state()
        stamp = (state or {}).get('failure_notifications', {}).get(args.stage)
        if stamp and now-datetime.fromisoformat(stamp) < timedelta(hours=6):
            logging.warning('동일 단계 오류 알림은 6시간 동안 중복 발송하지 않습니다')
            return 0
    except Exception:
        pass  # DB 장애라도 오류 알림 자체는 시도한다.
    title = '새 기사 AI 선별' if args.stage == 'screening' else '조간 AI 분석·발송'
    message = f'⚠️ {title} 실패\n이번 작업이 완료되지 않았습니다. 결과와 발송 상태는 실행 로그를 확인해 주세요.'
    url = env('RUN_URL')
    if url.startswith('https://github.com/joongyu01/news/actions/runs/'):
        message += f'\n실행 로그: {url}'
    if send_telegram([message]) != 1:
        raise RuntimeError('오류 알림 발송 실패')
    if state is not None:
        state.setdefault('failure_notifications', {})[args.stage] = now.isoformat()
        alerts.save_state(state)
    return 0


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except Exception as exc:
        logging.error('오류 알림 처리 실패 (%s)', type(exc).__name__)
        raise SystemExit(1)
