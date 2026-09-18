import os
import unittest
from unittest.mock import Mock, patch

from scripts import dispatch, storage
from tests.fixtures import sample_digest


class TestSupabase(unittest.TestCase):
    def setUp(self):
        p = patch.dict(os.environ, {"SUPABASE_URL": "https://example.supabase.co",
                                  "SUPABASE_SERVICE_ROLE_KEY": "test-only"})
        p.start()
        self.addCleanup(p.stop)

    def test_partial_configuration_rejected(self):
        with patch.dict(os.environ, {"SUPABASE_SERVICE_ROLE_KEY": ""}):
            with self.assertRaises(RuntimeError):
                storage.enabled()

    def test_draft_upsert_uses_date_and_full_payload(self):
        digest = sample_digest()
        with patch.object(storage.requests, "request", return_value=Mock(ok=True)) as request:
            storage.save_draft(digest)
        self.assertEqual(request.call_args.kwargs["json"]["payload"], digest.to_dict())
        self.assertEqual(request.call_args.kwargs["params"], {"on_conflict": "date"})

    def test_database_failure_never_sends_unreviewed_news(self):
        with patch.object(storage, "read", side_effect=RuntimeError("HTTP 503")), \
             patch.object(dispatch, "send_telegram") as telegram, \
             patch.object(dispatch, "send_email") as email:
            self.assertEqual(dispatch.main(["--date", "2026-09-16"]), 1)
        telegram.assert_not_called()
        email.assert_not_called()

    def test_remote_exclusions_applied_without_local_draft(self):
        digest = sample_digest()
        excluded = digest.articles[2]
        with patch.object(storage, "read", side_effect=[digest.to_dict(), {"excluded": [excluded.id]}]), \
             patch.object(dispatch, "send_telegram", return_value=0), \
             patch.object(dispatch, "send_email", return_value=1) as email, \
             patch.object(dispatch.archive, "write"), \
             patch.object(dispatch.archive, "rebuild_index"):
            self.assertEqual(dispatch.main(["--date", digest.date]), 0)
        self.assertNotIn(excluded.title, email.call_args.args[2])
