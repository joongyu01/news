import copy
import json
import os
import unittest
from datetime import timedelta
from unittest.mock import Mock, patch
from scripts import analysis, alerts, screening, rolling
from scripts.config import load_config
from tests.test_alerts import NOW, article


def decision(a, **kw):
    return dict(id=a.id, relevant=True, urgent=True, freshness='new', event_key='울산 정유공장 폭발', reason='새 폭발 발생', **kw)


class ScreeningTests(unittest.TestCase):
    def setUp(self):
        self.a = article()
        self.state = {'version': 1, 'started_at': (NOW-timedelta(days=1)).isoformat(), 'sent': []}
        rolling.accumulate(self.state, [self.a], NOW, load_config())
        self.save = Mock()

    def complete(self, decisions):
        def call(payload, validator, state, persist):
            return validator({'decisions': decisions}), {}, 1, 'test-model'
        return patch.object(analysis, 'complete', side_effect=call)

    def test_old_followup_and_uncertain_never_become_urgent(self):
        for freshness in ['recap', 'uncertain']:
            self.state.pop('screening', None)
            d=decision(self.a); d['freshness']=freshness
            with self.complete([d]):
                screening.run(self.state, NOW, self.save)
            self.assertEqual(screening.approved(self.state, [self.a], urgent=True), [])
            self.assertEqual(len(screening.approved(self.state,[self.a])), 1)

    def test_checked_article_is_not_resubmitted_and_second_batch_waits(self):
        with self.complete([decision(self.a)]) as api:
            screening.run(self.state, NOW, self.save)
            screening.run(self.state, NOW+timedelta(minutes=30), self.save)
            self.assertEqual(api.call_count, 1)
            b=article('정부 유류세 인하 확정', 'https://news.test/new')
            rolling.accumulate(self.state, [b], NOW+timedelta(minutes=31), load_config())
            screening.run(self.state, NOW+timedelta(minutes=31), self.save)
            self.assertEqual(api.call_count, 1)

    def test_foreign_is_never_urgent_even_if_model_claims_it(self):
        self.a.language='en'
        self.state['pool']['articles']=[self.a.to_dict()]
        with self.complete([decision(self.a)]):
            screening.run(self.state,NOW,self.save)
        self.assertFalse(self.state['screening']['checked'][0]['urgent'])

    def test_partial_or_unknown_decisions_fail_without_approval(self):
        for items in [[], [dict(decision(self.a),id='invented')]]:
            self.state.pop('screening',None)
            with self.complete(items), self.assertRaises(ValueError):
                screening.run(self.state,NOW,self.save)
            self.assertEqual(screening.approved(self.state,[self.a],urgent=True),[])

    def test_same_event_different_titles_is_sent_only_once(self):
        b=article('석유 저장시설 대형 폭발 사고 발생', 'https://news.test/b')
        self.state['screening']={'checked':[decision(self.a),decision(b)]}
        picked=alerts.select_alerts([self.a,b],self.state,alerts.load_rules(),NOW,load_config())
        self.assertEqual(len(picked),1)
        self.state['sent']=[{'id':self.a.id,'title':self.a.title,'rule':picked[0][1]['id'],
                             'ai_event':'울산 정유공장 폭발','sent_at':NOW.isoformat()}]
        self.assertEqual(alerts.select_alerts([b],self.state,alerts.load_rules(),NOW,load_config()),[])

    def test_night_guard_stops_before_collection(self):
        with patch.object(alerts,'now_kst',return_value=NOW.replace(hour=2)), patch.object(alerts,'read_state') as read:
            self.assertEqual(alerts.run(alerts.load_rules(),dry_run=True),0)
        read.assert_not_called()


class RotationTests(unittest.TestCase):
    def setUp(self):
        delay=patch.object(analysis.time, "sleep")
        delay.start(); self.addCleanup(delay.stop)
        p=patch.dict(os.environ,{'GEMINI_API_KEY':'key-a','GEMINI_API_KEY_BACKUP':'key-b',
                                'GEMINI_FREE_TIER_CONFIRMED':'true'})
        p.start(); self.addCleanup(p.stop)

    def test_persisted_keys_alternate_across_jobs_and_failed_attempts(self):
        state={}; snapshots=[]
        def save(s): snapshots.append(copy.deepcopy(s))
        with patch.object(analysis,'request_json',return_value=({'ok':True},{'totalTokenCount':123})) as req:
            for _ in range(3):
                analysis.complete({},lambda d:d,state,save)
        self.assertEqual([c.args[0] for c in req.call_args_list],['key-a','key-b','key-a'])
        self.assertEqual(state['ai']['requests'],3)
        self.assertEqual(snapshots[0]['ai']['requests'],1)
        self.assertEqual(state['ai']['usage']['totalTokenCount'],369)
        with patch.object(analysis,'request_json',side_effect=[RuntimeError(),({'ok':True},{})]) as req:
            analysis.complete({},lambda d:d,state,save)
        self.assertEqual([c.args[0] for c in req.call_args_list],['key-b','key-a'])
        self.assertEqual(state['ai']['next_key'],1)

    def test_daily_cap_and_persist_failure_make_zero_requests(self):
        from scripts.models import now_kst
        state={'ai':{'date':now_kst().date().isoformat(),'requests':40}}
        with patch.object(analysis,'request_json') as req, self.assertRaises(RuntimeError):
            analysis.complete({},lambda d:d,state,Mock())
        req.assert_not_called()

    def test_fallback_cannot_exceed_daily_cap(self):
        from scripts.models import now_kst
        state={'ai':{'date':now_kst().date().isoformat(),'requests':39,'usage':{}}}
        with patch.object(analysis,'request_json',side_effect=RuntimeError()) as req, self.assertRaises(RuntimeError):
            analysis.complete({},lambda d:d,state,Mock())
        self.assertEqual(req.call_count,1)
        self.assertEqual(state['ai']['requests'],40)

    def test_lite_fallback_keeps_validation_rotation_and_budget(self):
        state={}
        with patch.object(analysis,'request_json',side_effect=[RuntimeError(),RuntimeError(),({'ok':True},{'totalTokenCount':7})]) as req:
            result=analysis.complete({},lambda d:d,state,Mock())
        self.assertEqual(result[2:],(3,'gemini-3.1-flash-lite'))
        self.assertEqual([c.args[0] for c in req.call_args_list],['key-a','key-b','key-a'])
        self.assertEqual(state['ai']['requests'],3)
        self.assertEqual(state['ai']['usage']['totalTokenCount'],7)
        self.assertEqual([c.args[0] for c in analysis.time.sleep.call_args_list],[5,10])

    def test_fallback_records_actual_model_and_next_job_returns_to_primary(self):
        state={}
        with patch.object(analysis,'request_json',side_effect=[RuntimeError(),({'ok':True},{}),({'ok':True},{})]) as req:
            result=analysis.complete({},lambda d:d,state,Mock())
            self.assertEqual(result[2:],(2,'gemini-3.7-flash'))
            analysis.complete({},lambda d:d,state,Mock())
        self.assertEqual([c.args[1] for c in req.call_args_list],['gemini-3.8-flash','gemini-3.7-flash','gemini-3.8-flash'])
        with patch.object(analysis,'request_json') as req, self.assertRaises(RuntimeError):
            analysis.complete({},lambda d:d,{},Mock(side_effect=RuntimeError()))
        req.assert_not_called()

class DeliveryTests(unittest.TestCase):
    def test_multiple_urgent_articles_use_one_message_and_record_each(self):
        a=article(); b=article('정부 비축유 방출 결정', 'https://news.test/two')
        state={'version':1,'started_at':(NOW-timedelta(days=1)).isoformat(),'sent':[]}
        prefs={'owner':'owner','chats':{'owner':alerts.preferences.defaults()}}
        with patch.dict(os.environ,{'TELEGRAM_BOT_TOKEN':'test','TELEGRAM_CHAT_ID':'owner'}), \
             patch.object(alerts,'now_kst',return_value=NOW), patch.object(alerts,'read_state',return_value=state), \
             patch.object(alerts,'save_state'), patch.object(alerts.preferences,'load',return_value=prefs), \
             patch.object(alerts,'gather',return_value=[a,b]), patch.object(alerts,'send_telegram',return_value=1) as send:
            self.assertEqual(alerts.run({**alerts.load_rules(),'ai_screening':False}),2)
        self.assertEqual(send.call_count,1)
        self.assertEqual(len(send.call_args.args[0]),1)
        self.assertIn('긴급 뉴스 2건',send.call_args.args[0][0])
        self.assertIn('<a href=',send.call_args.args[0][0])
        self.assertEqual(len(state['sent']),2)

    def test_collector_still_runs_at_night_without_ai_or_delivery(self):
        state={'version':1,'started_at':NOW.isoformat(),'sent':[]}
        prefs={'owner':'owner','chats':{'owner':alerts.preferences.defaults()}}
        with patch.object(alerts,'now_kst',return_value=NOW.replace(hour=2)), \
             patch.object(alerts,'read_state',return_value=state), patch.object(alerts,'save_state'), \
             patch.object(alerts.preferences,'load',return_value=prefs), patch.object(alerts,'gather',return_value=[] ) as gather, \
             patch.object(screening,'run') as ai, patch.object(alerts,'send_telegram') as send:
            self.assertEqual(alerts.run(alerts.load_rules(),collect_only=True),0)
        gather.assert_called_once(); ai.assert_not_called(); send.assert_not_called()

    def test_error_notification_has_log_link_and_suppresses_repeats(self):
        from scripts import failure
        state={'version':1,'started_at':NOW.isoformat(),'sent':[]}
        with patch.object(failure,'now_kst',return_value=NOW), patch.object(alerts,'read_state',return_value=state), \
             patch.object(alerts,'save_state'), patch.object(failure,'send_telegram',return_value=1) as send, \
             patch.dict(os.environ,{'RUN_URL':'https://github.com/joongyu01/news/actions/runs/123'}):
            self.assertEqual(failure.main(['--stage','morning']),0)
            self.assertEqual(failure.main(['--stage','morning']),0)
        send.assert_called_once()
        self.assertIn('/actions/runs/123',send.call_args.args[0][0])
        self.assertIn('조간 AI 분석',send.call_args.args[0][0])
