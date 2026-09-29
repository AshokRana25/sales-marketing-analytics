import tempfile
import unittest
from pathlib import Path

from marketlens.analytics import export_csv, report
from marketlens.pipeline import connect, import_csv, initialize

SALES = "order_id,date,channel,campaign,gross_revenue,refund_amount,currency\n"
ADS = "date,channel,campaign,spend,impressions,clicks,conversions,currency\n"
SALE = "SYN-1,2026-08-01,paid search,Launch,60.00,10.00,USD\n"
AD = "2026-08-01,paid search,Launch,20.00,100,10,2,USD\n"


class PipelineTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.db = Path(self.temp.name) / "test.db"
        initialize(self.db)

    def tearDown(self):
        self.temp.cleanup()

    def test_join_does_not_multiply_spend(self):
        import_csv(self.db, SALES + SALE + SALE.replace("SYN-1", "SYN-2"), ADS + AD)
        summary = report(self.db)["summary"]
        self.assertEqual(summary["spend"], 20)
        self.assertEqual(summary["net_revenue"], 100)
        self.assertEqual(summary["orders"], 2)
        self.assertEqual(summary["roas"], 5)

    def test_roas_and_mer_are_different(self):
        organic = "SYN-2,2026-08-01,organic,Discovery,100,0,USD\n"
        import_csv(self.db, SALES + SALE + organic, ADS + AD)
        summary = report(self.db)["summary"]
        self.assertEqual(summary["roas"], 2.5)
        self.assertEqual(summary["mer"], 7.5)
        self.assertEqual(summary["aov"], 75)
        self.assertEqual(summary["cpa"], 10)

    def test_weighted_ctr_uses_ratio_of_sums(self):
        second = "2026-08-02,paid search,Launch,10,900,9,1,USD\n"
        import_csv(self.db, ads_csv=ADS + AD + second)
        self.assertEqual(report(self.db)["summary"]["ctr"], 1.9)

    def test_reimport_is_idempotent(self):
        import_csv(self.db, SALES + SALE, ADS + AD)
        result = import_csv(self.db, SALES + SALE, ADS + AD)
        self.assertEqual((result["accepted"], result["duplicates"]), (0, 2))
        self.assertEqual(report(self.db)["summary"]["orders"], 1)

    def test_in_batch_duplicates_are_skipped(self):
        result = import_csv(self.db, SALES + SALE + SALE)
        self.assertEqual((result["accepted"], result["duplicates"]), (1, 1))

    def test_conflicting_key_never_overwrites(self):
        import_csv(self.db, SALES + SALE)
        result = import_csv(self.db, SALES + SALE.replace("60.00", "90.00"))
        self.assertEqual(result["rejected"], 1)
        self.assertEqual(report(self.db)["summary"]["net_revenue"], 50)

    def test_bad_second_file_does_not_half_import(self):
        with self.assertRaises(ValueError):
            import_csv(self.db, SALES + SALE, "wrong,headers\n1,2\n")
        with connect(self.db) as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM sales").fetchone()[0], 0)
            self.assertEqual(db.execute("SELECT COUNT(*) FROM imports").fetchone()[0], 0)

    def test_channel_currency_and_whitespace_normalization(self):
        row = " SYN-1 ,2026-08-01, Search , Launch ,60,10,usd\n"
        result = import_csv(self.db, "\ufeff" + SALES + row)
        self.assertEqual(result["normalized"], 1)
        campaign = report(self.db)["campaigns"][0]
        self.assertEqual((campaign["channel"], campaign["campaign"]), ("paid search", "Launch"))

    def test_invalid_rows_are_quarantined_and_good_rows_commit(self):
        bad = [SALE.replace("SYN-1", "BAD1").replace("2026-08-01", "2026-02-30"),
               SALE.replace("SYN-1", "BAD2").replace("60.00", "-5"),
               SALE.replace("SYN-1", "BAD3").replace("10.00", "100.00"),
               SALE.replace("SYN-1", "BAD4").replace("USD", "EUR")]
        result = import_csv(self.db, SALES + SALE + "".join(bad))
        self.assertEqual((result["accepted"], result["rejected"]), (1, 4))

    def test_nonfinite_and_fractional_cents_rejected(self):
        for value in ["NaN", "Infinity", "0.001", "1e1000"]:
            with self.subTest(value=value):
                result = import_csv(self.db, SALES + SALE.replace("60.00", value))
                self.assertEqual(result["rejected"], 1)

    def test_invalid_ad_funnel_rejected(self):
        result = import_csv(self.db, ads_csv=ADS + AD.replace(",100,10,2,", ",100,110,2,"))
        self.assertEqual(result["rejected"], 1)

    def test_zero_denominators_and_empty_selection(self):
        summary = report(self.db)["summary"]
        for key in ["roas", "mer", "ctr", "cpc", "cpa", "aov"]:
            self.assertIsNone(summary[key])
        self.assertEqual(summary["net_revenue"], 0)

    def test_filters_are_inclusive_and_validated(self):
        import_csv(self.db, SALES + SALE, ADS + AD)
        self.assertEqual(report(self.db, "2026-08-01", "2026-08-01")["summary"]["orders"], 1)
        self.assertEqual(report(self.db, channel="organic")["summary"]["orders"], 0)
        with self.assertRaises(ValueError):
            report(self.db, "2026-08-02", "2026-08-01")
        with self.assertRaises(ValueError):
            report(self.db, channel="';DROP TABLE sales;--")

    def test_one_sided_source_days_remain_visible(self):
        import_csv(self.db, SALES + SALE, ADS + AD.replace("Launch", "Awareness"))
        summary = report(self.db)["summary"]
        self.assertEqual(summary["missing_ad_days"], 1)
        self.assertEqual(summary["ad_only_days"], 1)
        self.assertEqual(summary["spend"], 20)
        self.assertEqual(summary["net_revenue"], 50)

    def test_cents_remain_exact(self):
        rows = "".join(f"SYN-{i},2026-08-01,email,Small,0.10,0,USD\n" for i in range(3))
        import_csv(self.db, SALES + rows)
        self.assertEqual(report(self.db)["summary"]["revenue_cents"], 30)

    def test_persists_after_reopening(self):
        import_csv(self.db, SALES + SALE)
        initialize(self.db)
        self.assertEqual(report(self.db)["summary"]["orders"], 1)

    def test_export_neutralizes_spreadsheet_formula_names(self):
        import_csv(self.db, SALES + SALE.replace("Launch", "=1+1"))
        exported = export_csv(report(self.db)).decode("utf-8-sig")
        self.assertIn("'=1+1", exported)
        self.assertIn("net_revenue", exported)


if __name__ == "__main__":
    unittest.main()
