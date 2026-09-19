"""Deliver small Gemini web reports using existing GitHub-held Telegram secrets."""
from datetime import datetime, timedelta
from . import storage, preferences
from .config import env
from .models import now_kst
from .notify import send_telegram
from .sources import KST


def row():
    rows = storage.request('GET','news_bot_settings',params={'id':'eq.main','select':'payload,revision'}).json()
    if not rows:
        raise RuntimeError('Bot settings missing')
    return rows[0]


def update(transform):
    for _ in range(5):
        current = row()
        payload = current['payload']
        transform(payload)
        saved = storage.request('PATCH','news_bot_settings',
            params={'id':'eq.main','revision':f"eq.{current['revision']}"},
            prefer='return=representation',
            json={'payload':payload,'revision':current['revision']+1,'updated_at':now_kst().isoformat()}).json()
        if saved:
            return
    raise RuntimeError('Settings update conflict')


def deliver():
    now = now_kst()
    initial = row()['payload']
    if not initial.get('spark_queue') and not initial.get('spark_recent'):
        return 0
    def trim(p):
        p['spark_queue']=[x for x in p.get('spark_queue',[]) if datetime.fromisoformat(x['created_at'])>now-timedelta(hours=24)]
        p['spark_recent']=[x for x in p.get('spark_recent',[]) if datetime.fromisoformat(x['sent_at'])>now-timedelta(days=7)][-100:]
    update(trim)
    sent = 0
    for _ in range(3):
        p = row()['payload']
        owner = p['owner']
        if owner != env('TELEGRAM_CHAT_ID'):
            raise RuntimeError('Relay owner mismatch')
        options = p['chats'].get(owner)
        if not options or not options.get('urgent',True) or preferences.quiet_now(options,now):
            break
        queue = p.get('spark_queue',[])
        if not queue:
            break
        if options.get('limit',0):
            histories=storage.request('GET','news_alert_state',params={'id':'eq.urgent','select':'payload'}).json()
            history=histories[0]['payload'].get('sent',[]) if histories else []
            today=sum(datetime.fromisoformat(x['sent_at']).astimezone(KST).date()==now.date()
                      for x in history if x.get('chat',owner)==owner)
            today+=sum(datetime.fromisoformat(x['sent_at']).astimezone(KST).date()==now.date() for x in p.get('spark_recent',[]))
            if today>=options['limit']:
                break
        item=queue[0]
        text='🧠 Gemini 검토 보고\n\n'+item['text']+'\n\nGemini가 작성한 검토 의견입니다. 보고 전 원문을 확인해주세요.'
        if send_telegram([text],chat_id=owner)!=1:
            raise RuntimeError('Gemini report delivery failed')
        def finish(latest):
            latest['spark_queue']=[x for x in latest.get('spark_queue',[]) if x['id']!=item['id']]
            recent=[x for x in latest.get('spark_recent',[]) if x['id']!=item['id']]
            latest['spark_recent']=(recent+[{'id':item['id'],'sent_at':now.isoformat()}])[-100:]
        update(finish)
        sent+=1
    print(f'Gemini 검토 보고 {sent}건 전달')
    return sent


if __name__=='__main__':
    try:
        deliver()
    except Exception as error:
        print(f'Gemini 보고 전달 실패 ({type(error).__name__})')
        raise SystemExit(1)
