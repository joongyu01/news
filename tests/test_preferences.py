import unittest
from unittest.mock import patch
from datetime import timedelta
from scripts import alerts, preferences, notify
from scripts.config import load_config
from tests.test_alerts import NOW, article


class PreferencesTests(unittest.TestCase):
    def test_shared_settings_override_all_rooms_and_owner_migrates(self):
        payload={'owner':'1','chats':{'1':{**preferences.defaults(),'watch':['석유']},'-2':preferences.defaults()}}
        result=preferences.normalize(payload)
        self.assertEqual(result['chats']['-2']['watch'],['석유'])
        result['global']['urgent']=False
        self.assertFalse(preferences.normalize(result)['chats']['1']['urgent'])
    def test_defaults_match_user_choice(self):
        self.assertEqual(preferences.defaults()['mode'],'standard')
        self.assertEqual(preferences.defaults()['limit'],0)

    def test_overnight_quiet(self):
        self.assertTrue(preferences.quiet_now({'quiet':'22-07'},NOW.replace(hour=23)))
        self.assertTrue(preferences.quiet_now({'quiet':'22-07'},NOW.replace(hour=6)))
        self.assertFalse(preferences.quiet_now({'quiet':'22-07'},NOW.replace(hour=7)))

    def test_custom_keywords_literal_and_excluded(self):
        rules={**alerts.load_rules(),'topics_delivery':'instant'}; a=article('관심 (a+)+$ 소식')
        opts={**preferences.defaults(),'watch':['(a+)+$']}
        self.assertEqual(alerts.urgent_reason(a,rules,opts)['id'],'watch')
        self.assertIsNone(alerts.urgent_reason(article('aaaaaaaaaa 소식'),rules,opts))
        opts['exclude']=['관심']
        self.assertIsNone(alerts.urgent_reason(a,rules,opts))

    def test_strict_topic_cooldown(self):
        a=article('사우디 송유관 피격에 정유사 비상')
        b=article('중동에서 다시 공격…사우디 송유관 피격',url='https://x.test/2')
        rules=alerts.load_rules(); reason=alerts.urgent_reason(a,rules)
        state={'started_at':(NOW-timedelta(days=1)).isoformat(),'sent':[
            {'id':a.id,'title':a.title,'rule':reason['id'],'sent_at':NOW.isoformat(),'topic':alerts.topic_key(a,reason)}]}
        self.assertEqual(alerts.select_alerts([b],state,rules,NOW,load_config(),{'mode':'strict'}),[])

    def test_group_and_owner_get_separate_history_and_limits(self):
        prefs={'owner':'1','chats':{'1':preferences.defaults(),'-2':{**preferences.defaults(),'limit':1}}}
        state={'version':1,'started_at':(NOW-timedelta(days=1)).isoformat(),'sent':[
            {'chat':'-2','id':'old','title':'old','rule':'agency','sent_at':NOW.isoformat()}]}
        with patch.dict('os.environ',{'TELEGRAM_BOT_TOKEN':'test','TELEGRAM_CHAT_ID':'1'}), \
             patch.object(alerts.preferences,'load',return_value=prefs), \
             patch.object(alerts,'read_state',return_value=state), \
             patch.object(alerts,'save_state'), patch.object(alerts,'now_kst',return_value=NOW), \
             patch.object(alerts,'gather',return_value=[article()]), \
             patch.object(alerts,'send_telegram',return_value=1) as send:
            self.assertEqual(alerts.run({**alerts.load_rules(), 'ai_screening': False}),1)
        self.assertEqual(send.call_args.kwargs['chat_id'],'1')

    def test_digest_only_subscribed_rooms(self):
        prefs={'chats':{'1':{'daily':True},'-2':{'daily':False},'-3':{'daily':True}}}
        with patch.dict('os.environ',{'TELEGRAM_BOT_TOKEN':'test'}), \
             patch.object(preferences,'load',return_value=prefs), \
             patch.object(notify,'send_telegram',return_value=1) as send:
            self.assertEqual(notify.send_digest(['news']),2)
        self.assertEqual([x.kwargs['chat_id'] for x in send.call_args_list],['1','-3'])
