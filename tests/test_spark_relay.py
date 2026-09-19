import copy
import unittest
from datetime import timedelta
from unittest.mock import patch, MagicMock
from scripts import spark_relay, preferences
from scripts.models import now_kst


class SparkRelayTest(unittest.TestCase):
    def setUp(self):
        self.now=now_kst()
        self.state={'payload':{'owner':'123','chats':{'123':preferences.defaults()},'spark_queue':[
            {'id':'a','text':'테스트 공개 뉴스 검토 보고','created_at':self.now.isoformat()}]},'revision':0}
        self.conflict=False
        def request(method,table,**kwargs):
            if table=='news_alert_state':return MagicMock(json=lambda:[])
            if method=='GET':return MagicMock(json=lambda:[copy.deepcopy(self.state)])
            if self.conflict:
                self.conflict=False
                self.state['revision']+=1
                self.state['payload']['chats']['123']['daily']=False
                return MagicMock(json=lambda:[])
            self.assertEqual(kwargs['params']['revision'],f"eq.{self.state['revision']}")
            self.state=copy.deepcopy(kwargs['json'])
            return MagicMock(json=lambda:[{'id':'main'}])
        self.patches=[patch.object(spark_relay.storage,'request',side_effect=request),
            patch.object(spark_relay,'env',return_value='123'),patch.object(spark_relay,'now_kst',return_value=self.now)]
        for p in self.patches:p.start();self.addCleanup(p.stop)

    def test_success_removes_body_and_preserves_concurrent_change(self):
        self.conflict=True
        with patch.object(spark_relay,'send_telegram',return_value=1) as send:
            self.assertEqual(spark_relay.deliver(),1)
            self.assertEqual(send.call_args.kwargs['chat_id'],'123')
        self.assertFalse(self.state['payload']['chats']['123']['daily'])
        self.assertEqual(self.state['payload']['spark_queue'],[])
        self.assertEqual(set(self.state['payload']['spark_recent'][0]),{'id','sent_at'})

    def test_failure_keeps_pending_body(self):
        with patch.object(spark_relay,'send_telegram',side_effect=RuntimeError('temporary')):
            with self.assertRaises(RuntimeError):spark_relay.deliver()
        self.assertEqual(len(self.state['payload']['spark_queue']),1)

    def test_paused_and_expired_reports_are_not_sent(self):
        self.state['payload']['chats']['123']['urgent']=False
        with patch.object(spark_relay,'send_telegram') as send:
            self.assertEqual(spark_relay.deliver(),0)
            send.assert_not_called()
        self.state['payload']['spark_queue'][0]['created_at']=(self.now-timedelta(hours=25)).isoformat()
        with patch.object(spark_relay,'send_telegram') as send:
            spark_relay.deliver();send.assert_not_called()
        self.assertEqual(self.state['payload']['spark_queue'],[])

    def test_daily_limit_counts_gemini_reports(self):
        self.state['payload']['chats']['123']['limit']=1
        self.state['payload']['spark_recent']=[{'id':'old','sent_at':self.now.isoformat()}]
        with patch.object(spark_relay,'send_telegram') as send:
            self.assertEqual(spark_relay.deliver(),0);send.assert_not_called()
