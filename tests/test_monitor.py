import json
import os
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import Mock, patch
from zoneinfo import ZoneInfo

import monitor


class MonitorTests(unittest.TestCase):
    def test_probe_does_not_send_or_mutate_state(self):
        self.exercise(probe=True, delivered=True)

    def test_failed_send_retries_next_run(self):
        self.exercise(probe=False, delivered=False)

    def test_successful_send_deduplicates(self):
        self.exercise(probe=False, delivered=True)

    def exercise(self, probe, delivered):
        day = (datetime.now(ZoneInfo("Asia/Shanghai")) + timedelta(days=1)).date().isoformat()
        cinema = {"name": "影院", "url": "https://example.com", "lookup_tokens": ["影院"],
                  "jisu_theater_id": "123", "jisu_verified_name": "影院"}
        cfg = {"target_titles": ["沙丘3"], "monitor_dates": [day], "cinemas": [cinema]}
        result = {"date": day, "theaterid": "123", "theatername": "影院", "list": [
            {"moviename": "沙丘3", "movieid": "456", "showlist": [
                {"starttime": "20:00", "screentype": "IMAX2D", "hallname": "1", "issale": "1"}]}]}
        fake = Mock()
        fake.calls = 1
        fake.discover.return_value = []
        fake.schedule.side_effect = lambda _, date: dict(result, date=date)
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            config = root / "cinemas.json"
            state = root / "state.json"
            config.write_text(json.dumps(cfg))
            state.write_text('{"notified_shows": {}}')
            initial = state.read_text()
            with patch.multiple(monitor, ROOT=root, CONFIG=config, STATE=state), \
                 patch.dict(os.environ, {"LIVE_MONITOR_ENABLED": "true", "JISU_API_KEY": "test"}), \
                 patch("provider.Jisu", return_value=fake), \
                 patch.object(monitor, "send_wechat", return_value=delivered) as sender:
                monitor.run(probe)
                if probe:
                    sender.assert_not_called()
                    self.assertEqual(state.read_text(), initial)
                    return
                self.assertEqual(sender.call_count, 1)
                monitor.run(False)
                self.assertEqual(sender.call_count, 1 if delivered else 2)
                # Empty source responses never clear notification history.
                before_empty = state.read_text()
                fake.schedule.side_effect = lambda _, date: dict(result, date=date, list=[])
                self.assertEqual(monitor.run(False), 2)
                self.assertEqual(state.read_text(), before_empty)


if __name__ == "__main__":
    unittest.main()
