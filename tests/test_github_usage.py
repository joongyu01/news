import copy
import json
import unittest
from unittest.mock import MagicMock, patch

from scripts import github_usage


class GitHubUsageTest(unittest.TestCase):
    def setUp(self):
        self.values = {'GITHUB_TOKEN':'never-persist-this', 'GITHUB_REPOSITORY':'owner/news', 'GITHUB_RUN_ID':'7'}
        p = patch.object(github_usage, 'env', side_effect=lambda name:self.values.get(name,''))
        p.start(); self.addCleanup(p.stop)

    def response(self, url, **kwargs):
        self.assertEqual(kwargs['headers']['Authorization'], 'Bearer never-persist-this')
        if url.endswith('/owner/news'): data={'visibility':'public','private':False}
        elif url.endswith('/cache/usage'): data={'active_caches_size_in_bytes':1234}
        elif url.endswith('/rate_limit'): data={'resources':{'core':{'limit':1000,'remaining':994,'used':6,'reset':1800000000}}}
        else: data={'workflow_runs':[{'id':i,'status':'completed','conclusion':'success','secret':'do-not-store'} for i in range(7,3,-1)]}
        return MagicMock(ok=True,json=lambda:copy.deepcopy(data))

    def test_small_snapshot_rate_and_recent_runs_only(self):
        with patch.object(github_usage.requests,'get',side_effect=self.response) as get:
            data=github_usage.collect()
        self.assertEqual(get.call_count,6)
        self.assertTrue(get.call_args.args[0].endswith('/rate_limit'))
        self.assertEqual(data['rate']['remaining'],994)
        self.assertEqual(data['cache_bytes'],1234)
        self.assertEqual([r['id'] for r in data['runs']['collect']],[6,5,4])
        self.assertTrue(data['standard_runners'])
        self.assertNotIn('never-persist-this',json.dumps(data))
        self.assertNotIn('do-not-store',json.dumps(data))
        self.assertLess(len(json.dumps(data)),5000)

    def test_unavailable_is_not_zero_or_free(self):
        with patch.object(github_usage.requests,'get',return_value=MagicMock(ok=False,status_code=403)):
            data=github_usage.collect()
        self.assertIsNone(data['visibility'])
        self.assertIsNone(data['rate'])
        self.assertIsNone(data['cache_bytes'])
        self.assertEqual(data['runs'],{})
        self.assertEqual(len(data['errors']),6)

    def test_new_snapshot_replaces_history_and_preserves_settings(self):
        payload={'github_usage':{'old':'snapshot'},'spark_queue':[{'id':'pending'}],'chats':{'123':{'daily':False}}}
        with patch.object(github_usage,'collect',return_value={'errors':{},'checked_at':'new'}), \
             patch.object(github_usage,'update',side_effect=lambda transform:transform(payload)):
            github_usage.main()
        self.assertNotIn('old',payload['github_usage'])
        self.assertEqual(payload['spark_queue'],[{'id':'pending'}])
        self.assertFalse(payload['chats']['123']['daily'])

    def test_credentials_required_and_bad_counts_rejected(self):
        self.values['GITHUB_TOKEN']=''
        with patch.object(github_usage.requests,'get') as get:
            with self.assertRaises(RuntimeError): github_usage.collect()
            get.assert_not_called()
        self.values['GITHUB_TOKEN']='never-persist-this'
        with patch.object(github_usage.requests,'get',return_value=MagicMock(ok=True,json=lambda:{
                'resources':{'core':{'limit':1000,'remaining':1001,'reset':1800000000}}})):
            self.assertIsNone(github_usage.collect()['rate'])
