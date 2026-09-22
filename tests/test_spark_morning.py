import unittest
from datetime import timedelta
from scripts import rolling, spark_morning
from scripts.config import load_config
from tests.test_alerts import NOW, article

class SparkMorningTests(unittest.TestCase):
    def setUp(self):
        self.a=article('석유관리원 품질검사 확대')
        self.state={}
        rolling.accumulate(self.state,[self.a],NOW,load_config())
        self.report={'date':NOW.strftime('%Y-%m-%d'),'pool_updated_at':NOW.isoformat(),'issues':[
            {'title':'품질검사 확대','summary':'품질검사 보도','change':'전일 비교 근거 부족',
             'impact':'석유 품질 관리 관련','article_ids':[self.a.id]}]}
    def test_spark_report_builds_linked_digest_without_api(self):
        d=spark_morning.build(self.state,self.report,NOW,load_config())
        self.assertEqual(d.analysis['model'],'gemini-spark')
        self.assertEqual(d.articles[0].id,self.a.id)
    def test_excluded_unknown_and_wrong_day_are_rejected(self):
        with self.assertRaises(ValueError):
            spark_morning.build(self.state,self.report,NOW,load_config(),['품질검사'])
        with self.assertRaises(ValueError):
            spark_morning.build(self.state,self.report,NOW+timedelta(days=1),load_config())
        self.report['issues'][0]['article_ids']=['unknown']
        with self.assertRaises(ValueError):
            spark_morning.build(self.state,self.report,NOW,load_config())
