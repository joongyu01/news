"""One-time registration. Secrets never appear in logs or command arguments."""
import hashlib
import hmac
from urllib.parse import urlsplit
import requests
from . import storage, preferences
from .config import env

COMMANDS = {
    "subscribers": "구독 목록 (소유자 개인톡)", "daily_report": "최근 일일 운영 요약 (소유자 개인톡)",
    "settings": "봇 전체 현재 설정", "status": "전체 설정 확인", "help": "명령어 사용법",
    "articles": "수집 기사와 판정 (개인톡)", "excluded": "기사 제외 이유 (개인톡)",
    "urgent_on": "전체 긴급 알림 켜기", "urgent_off": "전체 긴급 알림 끄기",
    "daily_on": "전체 조간 알림 켜기", "daily_off": "전체 조간 알림 끄기",
    "mode_strict": "엄격한 중복 억제", "mode_standard": "기본 중복 억제",
    "limit": "상한 지정: /limit_5", "quiet": "휴식 지정: /quiet_22_07", "quiet_off": "추가 휴식 해제",
    "watch_add": "관심 추가: /watch_add_키워드", "watch_remove": "관심 제거: /watch_remove_키워드",
    "watch_list": "관심 키워드 목록", "exclude_add": "제외 추가: /exclude_add_키워드",
    "exclude_remove": "제외 제거: /exclude_remove_키워드", "exclude_list": "제외 키워드 목록",
    "subscribe": "이 방 구독", "unsubscribe": "이 방 구독 해제",
    "usage": "Groq·Gemini 잔여 봇 예산 (개인톡)", "logs": "운영 기록 (개인톡)",
    "api_status": "AI API 최근 성공·실패와 모델", "api_help": "AI API 명령 안내",
    "logs_collect": "조간 기록", "logs_alerts": "수집 기록", "logs_dispatch": "발송 기록",
}


def main():
    token, url, key = env("TELEGRAM_BOT_TOKEN"), env("REVIEW_URL").rstrip('/'), env("SUPABASE_SERVICE_ROLE_KEY")
    if not token or not key or urlsplit(url).scheme != 'https':
        raise RuntimeError('Missing bot settings')
    rows = storage.request('GET','news_bot_settings',params={'id':'eq.main','select':'id'}).json()
    if not rows:
        storage.request('POST','news_bot_settings',json={'id':'main','payload':preferences.initial()})
    owner = preferences.load()['owner']
    if owner != env('TELEGRAM_CHAT_ID') or not str(owner).isdigit():
        raise RuntimeError('Private owner mismatch')
    secret = hmac.new(key.encode(),b'news-bot-webhook-v1',hashlib.sha256).hexdigest()
    # Verify production API and DB before asking Telegram to deliver messages.
    check = requests.post(url+'/api/telegram',headers={'X-Telegram-Bot-Api-Secret-Token':secret},
                          json={'update_id':0,'message':{'text':'/status','chat':{'id':int(owner),'type':'private'},'from':{'id':int(owner)}}},timeout=20)
    if check.status_code != 200 or check.json().get('method') != 'sendMessage':
        raise RuntimeError('Webhook endpoint not ready')
    for command in ('/settings', '/articles', '/excluded'):
        check = requests.post(url+'/api/telegram', headers={'X-Telegram-Bot-Api-Secret-Token':secret},
                              json={'update_id':0,'message':{'text':command,'chat':{'id':int(owner),'type':'private'},'from':{'id':int(owner)}}}, timeout=20)
        body = check.json()
        if check.status_code != 200 or body.get('method') != 'sendMessage' or not body.get('text'):
            raise RuntimeError('Bot query verification failed')
        if command != '/settings' and body.get('parse_mode') != 'HTML':
            raise RuntimeError('Article query not deployed')
        if body['text'].startswith('기사 판정 조회에 실패'):
            raise RuntimeError('Article database query failed')
        print(f'{command} 응답 검증 완료 (실제 메시지 발송 없음)')

    def api(method, data):
        r=requests.post(f'https://api.telegram.org/bot{token}/{method}',json=data,timeout=20)
        body=r.json()
        if not r.ok or not body.get('ok'):
            raise RuntimeError(f'Telegram {method} failed')
        return body.get('result')

    for chat, sender in [(-1, int(owner)), (0, 0)]:
        check = requests.post(url+'/api/telegram', headers={'X-Telegram-Bot-Api-Secret-Token':secret},
            json={'update_id':0,'message':{'text':'/subscribers','chat':{'id':chat,'type':'group' if chat < 0 else 'private'},'from':{'id':sender}}}, timeout=20)
        if check.status_code != 200 or '소유자' not in check.json().get('text',''):
            raise RuntimeError('Master access guard not deployed')
    for command in ('/subscribers', '/daily_report'):
        check = requests.post(url+'/api/telegram', headers={'X-Telegram-Bot-Api-Secret-Token':secret},
            json={'update_id':0,'message':{'text':command,'chat':{'id':int(owner),'type':'private'},'from':{'id':int(owner)}}}, timeout=20)
        if check.status_code != 200 or check.json().get('method') != 'sendMessage' or '명령 형식' in check.json().get('text',''):
            raise RuntimeError('Master query not deployed')
    print('마스터 전용 조회·그룹/타 계정 접근 차단 검증 완료 (실제 메시지 발송 없음)')
    from .daily_report import chat_info
    from .spark_relay import update
    names = chat_info(preferences.load())
    def save_names(p):
        p['ai_provider'] = 'groq' if env('AI_PROVIDER') == 'groq' else 'gemini'
        old = p.get('chat_info', {})
        p['chat_info'] = {c:names.get(c, old.get(c, {'name':'이름 미확인'})) for c in p['chats']}
    update(save_names)

    me=api('getMe',{})
    api('setMyCommands',{'commands':[]})
    scope = {'type':'chat', 'chat_id':int(owner)}
    api('setMyCommands',{'scope':scope,'commands':[{'command':cmd,'description':desc} for cmd,desc in COMMANDS.items()]})
    if {c['command'] for c in api('getMyCommands',{'scope':scope})} != set(COMMANDS):
        raise RuntimeError('Telegram command registration mismatch')
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
