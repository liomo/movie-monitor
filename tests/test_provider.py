import unittest
from datetime import datetime
from zoneinfo import ZoneInfo
from unittest.mock import Mock

from provider import Jisu, SourceError, discover_candidates, parse_shows, show_key


class ProviderTests(unittest.TestCase):
    def setUp(self):
        self.cinema = {"name": "测试影院", "url": "https://www.maoyan.com/cinema/1",
                       "lookup_tokens": ["寰映", "大融城"]}
        self.now = datetime(2026, 11, 7, 16, 0, tzinfo=ZoneInfo("Asia/Shanghai"))
        self.row = {"starttime": "19:30", "screentype": "英语IMAX2D", "hallname": "1号厅",
                    "issale": "1", "ticketurl": "https://example.com/ticket"}
        self.result = {"theaterid": "123", "date": "2026-12-31", "list": [
            {"movieid": "456", "moviename": "沙丘3", "showlist": [self.row]}]}

    def parse(self, result=None):
        return parse_shows(result or self.result, self.cinema, ["沙丘3"], self.now)

    def test_imax_sale_in_same_show(self):
        s = self.parse()[0]
        self.assertTrue(all(s[k] for k in ("imax", "sale", "target", "future")))

    def test_dune2_cannot_match(self):
        self.result["list"][0]["moviename"] = "沙丘2"
        self.assertFalse(self.parse()[0]["target"])

    def test_cinema_imax_name_does_not_make_normal_show_imax(self):
        self.cinema["name"] = "IMAX影城"
        self.row["screentype"] = "2D"
        self.assertFalse(self.parse()[0]["imax"])

    def test_unknown_sale_is_not_open(self):
        self.row["issale"] = ""
        self.assertFalse(self.parse()[0]["sale"])

    def test_sale_transition_keeps_identity(self):
        a = self.parse()[0]
        self.row["issale"] = "0"
        self.row["ticketurl"] = "https://example.com/changed"
        self.assertEqual(show_key(a), show_key(self.parse()[0]))

    def test_past_show(self):
        self.result["date"] = "2026-11-06"
        self.assertFalse(self.parse()[0]["future"])

    def test_invalid_time_fails_instead_of_empty(self):
        self.row["starttime"] = "bad"
        with self.assertRaises(SourceError):
            self.parse()

    def test_missing_showlist_fails(self):
        del self.result["list"][0]["showlist"]
        with self.assertRaises(SourceError):
            self.parse()

    def test_discovery_returns_all_ambiguous_candidates(self):
        rows = [{"theaterid": "1", "theatername": "寰映大融城"},
                {"theaterid": "2", "theatername": "寰映影城大融城店"}]
        self.assertEqual(len(discover_candidates(self.cinema, rows)), 2)

    def test_missing_key(self):
        with self.assertRaises(SourceError):
            Jisu("")

    def test_identity_mismatch_fails(self):
        api = Jisu("test")
        api.call = Mock(return_value={"theaterid": "999", "date": "2026-12-31", "list": []})
        with self.assertRaises(SourceError):
            api.schedule("123", "2026-12-31")

    def test_credentials_are_not_in_error(self):
        api = Jisu("PRIVATE-TEST-KEY")
        api.session.get = Mock(side_effect=ValueError("PRIVATE-TEST-KEY"))
        with self.assertRaises(SourceError) as error:
            api.call("theater", city="上海")
        self.assertNotIn("PRIVATE-TEST-KEY", str(error.exception))


if __name__ == "__main__":
    unittest.main()
