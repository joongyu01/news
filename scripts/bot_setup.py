"""One-time registration. Secrets never appear in logs or command arguments."""
import hashlib
import hmac
from urllib.parse import urlsplit
import requests
from . import storage, preferences
from .config import env

COMMANDS = {
    "usage": "GitHub 사용량·API 잔여 한도 (개인 대화)",
    "logs": "수집·발송 시각, 건수와 상세 로그",
    "help": "사용법", "status": "현재 방 설정", "subscribe": "이 방 구독",
    "unsubscribe": "이 방 구독 해제", "urgent": "긴급 알림 on/off", "daily": "아침 동향 on/off",
    "mode": "강도 strict/standard", "limit": "하루 상한 0~20", "quiet": "휴식 시간 22-07/off",
    "watch": "관심 키워드 add/remove/list", "exclude": "제외 키워드 add/remove/list",
}


def main():
    token, url, key = env("TELEGRAM_BOT_TOKEN"), env("REVIEW_URL").rstrip('/'), env("SUPABASE_SERVICE_ROLE_KEY")
    if not token or not key or urlsplit(url).scheme != 'https':
        raise RuntimeError('Missing bot settings')
    rows = storage.request('GET','news_bot_settings',params={'id':'eq.main','select':'id'}).json()
    if not rows:
        storage.request('POST','news_bot_settings',json={'id':'main','payload':preferences.initial()})
    secret = hmac.new(key.encode(),b'news-bot-webhook-v1',hashlib.sha256).hexdigest()
    # Verify production API and DB before asking Telegram to deliver messages.
    check = requests.post(url+'/api/telegram',headers={'X-Telegram-Bot-Api-Secret-Token':secret},
                          json={'update_id':0,'message':{'text':'/status','chat':{'id':0,'type':'private'},'from':{'id':0}}},timeout=20)
    if check.status_code != 200 or check.json().get('method') != 'sendMessage':
        raise RuntimeError('Webhook endpoint not ready')

    def api(method, data):
        r=requests.post(f'https://api.telegram.org/bot{token}/{method}',json=data,timeout=20)
        body=r.json()
        if not r.ok or not body.get('ok'):
            raise RuntimeError(f'Telegram {method} failed')
        return body.get('result')

    me=api('getMe',{})
    api('setMyCommands',{'commands':[{'command':cmd,'description':desc} for cmd,desc in COMMANDS.items()]})
    api('setWebhook',{'url':url+'/api/telegram','secret_token':secret,'max_connections':1,
                      'allowed_updates':['message']})
    info=api('getWebhookInfo',{})
    if info.get('url') != url+'/api/telegram':
        raise RuntimeError('Webhook URL mismatch')
    print(f"명령 연결 완료 · 단톡방 초대 가능: {bool(me.get('can_join_groups'))} · 전체 대화 읽기: {bool(me.get('can_read_all_group_messages'))}")


if __name__=='__main__':
    try:
        main()
    except Exception as exc:
        print(f'봇 명령 연결 실패 ({type(exc).__name__})')
        raise SystemExit(1)
