"""발송 진입점 검증.

특히 "아무 데도 보내지 않았는데 성공으로 끝나는" 경우를 막는 데 집중합니다.
Secret 이 비어 있으면 send_telegram/send_email 은 예외 대신 0을 돌려주므로,
그 상태로 아카이브까지 남기면 아무에게도 가지 않은 동향이 기록으로 남고
Actions 는 초록불이 뜹니다. 조용히 잘못되는 쪽이라 더 위험합니다.
"""

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from scripts import archive, dispatch
from tests.fixtures import sample_digest

DATE = "2026-09-16"


class DispatchHarness(unittest.TestCase):
    """초안·아카이브 경로를 임시 디렉터리로 돌려 실제 저장소를 건드리지 않습니다."""

    def setUp(self):
        self._tmp = TemporaryDirectory()
        root = Path(self._tmp.name)
        self.draft_dir = root / "drafts"
        self.exclusion_dir = root / "exclusions"
        self.archive_dir = root / "archive"
        self.draft_dir.mkdir()
        self.exclusion_dir.mkdir()

        patches = {
            "scripts.dispatch.DRAFT_DIR": self.draft_dir,
            "scripts.dispatch.EXCLUSION_DIR": self.exclusion_dir,
            # archive 모듈은 임포트 시점에 ARCHIVE_DIR 을 참조하므로 그쪽을 바꿉니다.
            "scripts.archive.ARCHIVE_DIR": self.archive_dir,
        }
        for target, value in patches.items():
            p = patch(target, value)
            p.start()
            self.addCleanup(p.stop)
        self.addCleanup(self._tmp.cleanup)

    def save_draft(self):
        sample_digest().save(self.draft_dir / f"{DATE}.json")

    def run_dispatch(self, telegram_sent, email_sent):
        with patch.object(dispatch, "send_telegram", return_value=telegram_sent), \
             patch.object(dispatch, "send_email", return_value=email_sent):
            return dispatch.main(["--date", DATE])

    @property
    def archive_file(self):
        return archive.archive_path(DATE)


class TestDispatch(DispatchHarness):
    def test_nothing_sent_does_not_archive(self):
        """설정이 비어 발송이 0건이면 실패로 끊고 아카이브를 남기지 않습니다."""
        self.save_draft()
        self.assertEqual(self.run_dispatch(telegram_sent=0, email_sent=0), 1)
        self.assertFalse(self.archive_file.exists())

    def test_telegram_only_still_archives(self):
        """이메일만 실패해도 담당자는 텔레그램으로 받았으므로 기록은 남깁니다."""
        self.save_draft()
        self.assertEqual(self.run_dispatch(telegram_sent=1, email_sent=0), 0)
        self.assertTrue(self.archive_file.exists())
        self.assertIn("일일언론동향", self.archive_file.read_text(encoding="utf-8"))

    def test_email_only_still_archives(self):
        self.save_draft()
        self.assertEqual(self.run_dispatch(telegram_sent=0, email_sent=2), 0)
        self.assertTrue(self.archive_file.exists())

    def test_email_exception_does_not_block_archive(self):
        """이메일이 예외로 죽어도 텔레그램이 나갔으면 계속 진행합니다."""
        self.save_draft()
        with patch.object(dispatch, "send_telegram", return_value=1), \
             patch.object(dispatch, "send_email", side_effect=RuntimeError("SMTP 거부")):
            self.assertEqual(dispatch.main(["--date", DATE]), 0)
        self.assertTrue(self.archive_file.exists())

    def test_email_exception_with_no_telegram_fails(self):
        """양쪽 다 실패하면 아카이브 없이 실패해야 합니다."""
        self.save_draft()
        with patch.object(dispatch, "send_telegram", return_value=0), \
             patch.object(dispatch, "send_email", side_effect=RuntimeError("SMTP 거부")):
            self.assertEqual(dispatch.main(["--date", DATE]), 1)
        self.assertFalse(self.archive_file.exists())

    def test_missing_draft_stops_quietly(self):
        """수집이 실패한 날 빈 동향을 보내지 않고 멈춥니다."""
        self.assertEqual(self.run_dispatch(telegram_sent=1, email_sent=1), 1)
        self.assertFalse(self.archive_file.exists())

    def test_dry_run_sends_nothing_and_archives_nothing(self):
        self.save_draft()
        with patch.object(dispatch, "send_telegram") as telegram, \
             patch.object(dispatch, "send_email") as email:
            self.assertEqual(dispatch.main(["--date", DATE, "--dry-run"]), 0)
        telegram.assert_not_called()
        email.assert_not_called()
        self.assertFalse(self.archive_file.exists())

    def test_exclusions_applied_to_archive(self):
        import json

        digest = sample_digest()
        digest.save(self.draft_dir / f"{DATE}.json")
        dropped = digest.articles[2]
        (self.exclusion_dir / f"{DATE}.json").write_text(
            json.dumps({"date": DATE, "excluded": [dropped.id]}, ensure_ascii=False),
            encoding="utf-8",
        )
        self.assertEqual(self.run_dispatch(telegram_sent=1, email_sent=1), 0)
        self.assertNotIn(dropped.title, self.archive_file.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
