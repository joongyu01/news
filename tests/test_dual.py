import copy
import unittest
from unittest.mock import patch, Mock
from scripts import analysis, morning
from scripts.config import load_config
from scripts.render import render_plain, telegram_chunks
from tests.fixtures import sample_digest
from tests.test_morning import issue
from tests.test_parity import js_plain

class DualTests(unittest.TestCase):
    def test_identical_payload_and_provider_isolation(self):
        articles=sample_digest().articles
        payloads=[]
        def call(payload, validator, state, persist, **kwargs):
            payloads.append((copy.deepcopy(payload),kwargs['provider']))
            if kwargs['provider']=='gemini': raise RuntimeError('unavailable')
            return [],{},1,'groq/test'
        with patch.object(analysis,'complete',side_effect=call):
            result=analysis.analyze_dual(articles,state={})
        self.assertEqual(payloads[0][0],payloads[1][0])
        self.assertEqual([r['status'] for r in result['reports']],['failed','ok'])
        self.assertEqual(result['mode'],'dual')

    def test_preview_parity_partial_failure_and_exclusions(self):
        d=sample_digest(); a,b=d.articles[:2]
        reports=[{'provider':'gemini','status':'ok','model':'gemini/test','issues':[issue(a)]},
                 {'provider':'groq','status':'ok','model':'groq/test','issues':[issue(a),issue(b)]}]
        for failed in (False,True):
            if failed: reports[0].update(status='failed',issues=[])
            d.analysis={'version':1,'mode':'dual','input_count':2,'reports':reports,'issues':[i for r in reports for i in r['issues']]}
            for excluded in (set(),{a.id}):
                self.assertEqual(js_plain(d,excluded),render_plain(d,load_config(),excluded))
                chunks=telegram_chunks(d,load_config(),excluded)
                self.assertTrue(all(len(c)<6000 for c in chunks))
                self.assertIn('[Gemini 분석]', ''.join(chunks))
                if excluded: self.assertNotIn(a.url,''.join(chunks))

    def test_owner_test_only_positive_matching_owner(self):
        d=sample_digest()
        with patch.dict('os.environ',{'TELEGRAM_CHAT_ID':'123'}),patch('scripts.notify.send_telegram',return_value=1) as send:
            for owner in ('-123','456',''):
                with self.assertRaises(RuntimeError): morning.send_owner_test(d,load_config(),{'owner':owner})
            send.assert_not_called()
            morning.send_owner_test(d,load_config(),{'owner':'123','chats':{'-99':{}}})
            self.assertEqual(send.call_args.kwargs,{'chat_id':'123','parse_mode':'HTML'})

    def test_both_fail_still_preserves_reports(self):
        with patch.object(analysis,'analyze',side_effect=RuntimeError()):
            r=analysis.analyze_dual(sample_digest().articles)
        self.assertEqual([x['status'] for x in r['reports']],['failed','failed'])
