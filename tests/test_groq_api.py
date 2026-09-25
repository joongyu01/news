import json
import unittest
from unittest.mock import Mock, patch
from scripts import groq_api, analysis
from scripts.models import now_kst


class GroqTests(unittest.TestCase):
    def setUp(self):
        self.env = patch.dict('os.environ', {'AI_PROVIDER':'groq', 'GROQ_FREE_TIER_CONFIRMED':'true', 'GROQ_API_KEY':'test-secret'})
        self.env.start()
        self.addCleanup(self.env.stop)
        self.payload = {'contents':[{'parts':[{'text':'Return JSON'}]}]}

    def test_fail_closed_free_guard_and_reservation(self):
        with patch.dict('os.environ', {'GROQ_FREE_TIER_CONFIRMED':'false'}), patch.object(groq_api.requests,'post') as post:
            with self.assertRaises(RuntimeError):
                analysis.complete(self.payload, lambda x:x, {}, Mock())
            post.assert_not_called()
        with patch.object(groq_api.requests,'post') as post:
            with self.assertRaises(RuntimeError):
                groq_api.complete(self.payload, lambda x:x, {}, Mock(side_effect=RuntimeError()))
            post.assert_not_called()

    def test_no_retry_paid_fallback_or_secret_error(self):
        state={}
        with patch.object(groq_api.requests,'post',return_value=Mock(ok=False,status_code=429)) as post, patch.object(analysis,'request_json') as gemini:
            with self.assertRaisesRegex(RuntimeError, 'Groq 분석 실패'):
                analysis.complete(self.payload,lambda x:x,state,Mock())
        self.assertEqual(post.call_count,1)
        gemini.assert_not_called()
        self.assertGreater(state['groq_ai']['reserved_tokens'],0)

    def test_validation_and_usage(self):
        state={}
        response=Mock(ok=True,json=lambda:{'choices':[{'finish_reason':'stop','message':{'content':'{"ok":true}'}}], 'usage':{'total_tokens':17}})
        with patch.object(groq_api.requests,'post',return_value=response):
            result=analysis.complete(self.payload,lambda x:x,state,Mock())
        self.assertEqual(result[0],{'ok':True})
        self.assertEqual(state['groq_ai']['reserved_tokens'],17)
        self.assertEqual(result[-1],'groq/qwen/qwen3.8-27b')

    def test_daily_and_input_caps(self):
        for state,payload in [({'groq_ai':{'date':now_kst().date().isoformat(),'requests':40,'reserved_tokens':0}},self.payload),
                              ({}, {'contents':[{'parts':[{'text':'가'*3000}]}]}),
                              ({'groq_ai':{'date':now_kst().date().isoformat(),'requests':1,'reserved_tokens':200000}},self.payload)]:
            with patch.object(groq_api.requests,'post') as post, self.assertRaises(RuntimeError):
                analysis.complete(payload,lambda x:x,state,Mock())
            post.assert_not_called()

    def test_morning_reserve_and_removal_of_old_cap(self):
        response=Mock(ok=True,json=lambda:{'choices':[{'finish_reason':'stop','message':{'content':'{}'}}], 'usage':{'total_tokens':17}})
        def state(tokens):
            return {'groq_ai':{'date':now_kst().date().isoformat(),'requests':1,'reserved_tokens':tokens,'usage':{}}}
        with patch.object(groq_api.requests,'post',return_value=response) as post:
            analysis.complete(self.payload,lambda x:x,state(180000),Mock())
            post.assert_called_once()
        shared=state(192200)
        with patch.object(groq_api.requests,'post',return_value=response) as post:
            with self.assertRaises(RuntimeError):
                analysis.complete(self.payload,lambda x:x,shared,Mock())
            post.assert_not_called()
            analysis.complete(self.payload,lambda x:x,shared,Mock(),morning=True)
            post.assert_called_once()

    def test_reserve_survives_midnight_and_old_usage_expires(self):
        now=now_kst()
        state={'groq_ai':{'date':'2000-01-01','requests':39,'reserved_tokens':0,'usage':{},
                         'recent':[{'at':now.timestamp()-3600,'tokens':192200},
                                   {'at':now.timestamp()-90000,'tokens':200000}]}}
        with patch.object(groq_api.requests,'post') as post:
            with self.assertRaises(RuntimeError):
                analysis.complete(self.payload,lambda x:x,state,Mock())
            post.assert_not_called()
        self.assertEqual(len(state['groq_ai']['recent']),1)
        self.assertEqual(state['groq_ai']['requests'],0)
