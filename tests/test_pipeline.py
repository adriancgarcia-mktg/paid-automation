"""End-to-end tests: each guardrail is exercised by breaking the thing it protects.

Run with: python3 -m unittest discover -s tests -v
"""
import csv
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parent.parent
SCRIPTS = REPO / "scripts"
PUSH_STUB = """
import json, runpy, sys
from unittest import mock
sent = []
def post(url, data=None, **kwargs):
    sent.append({"url": url, "data": data})
    response = mock.Mock(status_code=200)
    response.json.return_value = {"id": str(len(sent))}
    return response
sys.path.insert(0, sys.argv[1])
sys.argv = ["03_build_meta.py", "--push"]
with mock.patch("requests.post", post):
    runpy.run_path(sys.path[0] + "/03_build_meta.py", run_name="__main__")
print("SENT=" + json.dumps(sent))
"""


class PipelineCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        shutil.copytree(REPO / "config", self.root / "config")
        shutil.copytree(REPO / "data", self.root / "data")
        (self.root / "output").mkdir()
        self.env = {**os.environ, "PAID_AUTOMATION_ROOT": str(self.root)}

    def tearDown(self):
        self.tmp.cleanup()

    def run_script(self, name, *args):
        return subprocess.run([sys.executable, str(SCRIPTS / name), *args], env=self.env,
                              capture_output=True, text=True)

    def build(self):
        for name in ("01_audit.py", "03_build_meta.py", "04_build_google.py"):
            result = self.run_script(name)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def edit_plan(self, change):
        path = self.root / "config/plan.yaml"
        plan = yaml.safe_load(path.read_text())
        change(plan)
        path.write_text(yaml.safe_dump(plan, sort_keys=False))

    def campaign(self, plan, platform, name):
        return next(c for c in plan[platform]["campaigns"] if c["name"] == name)

    def assert_qa_fails(self, check_text):
        result = self.run_script("05_qa.py")
        self.assertEqual(result.returncode, 1, result.stdout)
        failed = [line for line in result.stdout.splitlines() if line.startswith("FAIL")]
        self.assertTrue(any(check_text in line for line in failed), result.stdout)

    def replace_in(self, relative, old, new):
        path = self.root / relative
        text = path.read_text()
        self.assertIn(old, text)
        path.write_text(text.replace(old, new))


class HappyPath(PipelineCase):
    def test_pipeline_passes_and_everything_is_paused(self):
        self.build()
        result = self.run_script("05_qa.py")
        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertEqual(json.loads((self.root / "output/qa_status.json").read_text())["overall"], "PASS")
        for name in ("meta_bulk_upload.csv", "google_ads_editor.csv", "meta_api_payloads.json"):
            self.assertNotIn("ACTIVE", (self.root / "output" / name).read_text())

    def test_expected_audit_verdicts(self):
        self.run_script("01_audit.py")
        report = (self.root / "output/audit_report.md").read_text()
        audit = json.loads(report.split("```json\n")[1].split("\n```")[0])
        verdicts = {v["object"]: v["verdict"] for v in audit["verdicts"]}
        self.assertEqual(verdicts["Search_NonBrand_UK"], "CUT")
        self.assertEqual(verdicts["UGC_Founder_v2"], "RESHOOT_ANGLE")
        self.assertEqual(verdicts["Carousel_Old"], "FATIGUE")
        self.assertEqual(verdicts["Cold_Interest"], "CUT_CANDIDATE")
        self.assertEqual(verdicts["Search_NonBrand_US"], "KEEP")
        self.assertEqual(audit["tracking"]["status"], "OK")
        flagged = {(i["object"], i["change"]) for i in audit["change_impacts"]}
        self.assertIn(("Cold_Interest", "Broadened interest stack"), flagged)


class BudgetGuardrail(PipelineCase):
    def test_original_spec_totals_abort(self):
        self.run_script("01_audit.py")
        self.edit_plan(lambda plan: plan["google"].update(monthly_budget=55000))
        result = self.run_script("03_build_meta.py")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("ABORT", result.stderr)

    def test_tenfold_daily_budget_aborts(self):
        self.run_script("01_audit.py")
        self.edit_plan(lambda plan: self.campaign(plan, "meta", "Cold_Consolidated").update(daily_budget_cents=1667000))
        result = self.run_script("03_build_meta.py")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("ABORT", result.stderr)
        self.assertFalse((self.root / "output/meta_bulk_upload.csv").exists())

    def test_tampered_csv_budget_fails_qa(self):
        self.build()
        self.replace_in("output/google_ads_editor.csv", "1066.67", "2066.67")
        self.assert_qa_fails("Budget sum")


class StatusGuardrail(PipelineCase):
    def test_active_in_plan_aborts(self):
        self.run_script("01_audit.py")
        self.edit_plan(lambda plan: self.campaign(plan, "meta", "Retargeting_30d").update(status="ACTIVE"))
        self.assertNotEqual(self.run_script("03_build_meta.py").returncode, 0)

    def test_active_in_csv_fails_qa(self):
        self.build()
        self.replace_in("output/meta_bulk_upload.csv", "Retargeting_30d,PAUSED", "Retargeting_30d,ACTIVE")
        self.assert_qa_fails("PAUSED")

    def test_draft_plan_cannot_build(self):
        self.run_script("01_audit.py")
        self.edit_plan(lambda plan: plan.update(plan_status="DRAFT"))
        result = self.run_script("03_build_meta.py")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("APPROVED", result.stderr)


class TrackingGuardrail(PipelineCase):
    def test_drift_halts_build(self):
        path = self.root / "data/Trials_PostHog.csv"
        rows = list(csv.DictReader(path.read_text().splitlines()))
        with path.open("w", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=rows[0].keys())
            writer.writeheader()
            for row in rows:
                if row["utm_source"] == "google":
                    row["Trials"] = int(int(row["Trials"]) * 0.5)
                writer.writerow(row)
        self.assertEqual(self.run_script("01_audit.py").returncode, 2)
        self.assertIn("TRACKING_RISK", (self.root / "output/audit_report.md").read_text())
        self.assertNotEqual(self.run_script("03_build_meta.py").returncode, 0)
        self.assertNotEqual(self.run_script("04_build_google.py").returncode, 0)


class QaChecks(PipelineCase):
    def test_cut_object_in_plan_fails(self):
        def rename(plan):
            self.campaign(plan, "google", "PMax_US")["name"] = "Search_NonBrand_UK"
        self.run_script("01_audit.py")
        self.edit_plan(rename)
        self.run_script("03_build_meta.py")
        self.run_script("04_build_google.py")
        self.assert_qa_fails("No CUT object")

    def test_cost_cap_out_of_band_fails(self):
        self.run_script("01_audit.py")
        self.edit_plan(lambda plan: self.campaign(plan, "meta", "Retargeting_30d").update(cost_cap=40000))
        self.run_script("03_build_meta.py")
        self.run_script("04_build_google.py")
        self.assert_qa_fails("Cost caps")

    def test_missing_replacement_fails(self):
        def remove(plan):
            for ad in self.campaign(plan, "meta", "Cold_Consolidated")["ads"]:
                ad.pop("replaces", None)
        self.run_script("01_audit.py")
        self.edit_plan(remove)
        self.run_script("03_build_meta.py")
        self.run_script("04_build_google.py")
        self.assert_qa_fails("replacements")

    def test_extra_ad_in_testing_ad_set_fails(self):
        self.build()
        path = self.root / "output/meta_bulk_upload.csv"
        lines = path.read_text().splitlines()
        index = next(i for i, line in enumerate(lines) if line.startswith("Test_Hook_A,PAUSED"))
        lines.insert(index + 1, lines[index].replace("Test_Hook_A,PAUSED", "Test_Hook_Z,PAUSED"))
        path.write_text("\n".join(lines) + "\n")
        self.assert_qa_fails("Creative_Testing")

    def test_missing_pmax_negatives_fails(self):
        self.build()
        self.replace_in("output/google_ads_editor.csv", "Account negative list", "Standard")
        self.assert_qa_fails("PMax")

    def test_bad_utm_fails(self):
        self.build()
        self.replace_in("output/google_ads_editor.csv", "utm_source=google", "utm_source=adwords")
        self.assert_qa_fails("UTMs")

    def test_campaign_not_in_plan_fails(self):
        self.build()
        self.replace_in("output/meta_bulk_upload.csv", "Retargeting_30d,PAUSED", "Rogue_Campaign,PAUSED")
        self.assert_qa_fails("match the approved plan")

    def test_missing_files_fail_closed(self):
        self.run_script("01_audit.py")
        result = self.run_script("05_qa.py")
        self.assertEqual(result.returncode, 1)
        self.assertEqual(json.loads((self.root / "output/qa_status.json").read_text())["overall"], "FAIL")


class Compiler(PipelineCase):
    def compile(self):
        self.run_script("01_audit.py")
        result = self.run_script("02_compile_plan.py")
        self.assertEqual(result.returncode, 0, result.stderr)
        return yaml.safe_load((self.root / "output/plan.yaml").read_text())

    def test_verdict_rules(self):
        draft = self.compile()
        self.assertEqual(draft["plan_status"], "DRAFT")
        google = [c["name"] for c in draft["google"]["campaigns"]]
        meta = {c["name"]: c for c in draft["meta"]["campaigns"]}
        self.assertNotIn("Search_NonBrand_UK", google)
        self.assertNotIn("Cold_Interest", meta)
        ads = {ad["name"]: ad for ad in meta["Cold_Broad"]["ads"]}
        self.assertEqual(ads["UGC_Founder_v2_Reshoot"]["replaces"], "UGC_Founder_v2")
        self.assertNotIn("UGC_Founder_v2", ads)
        self.assertEqual(draft["meta"]["replacements_required"], ["Carousel_Old"])

    def test_scale_capped_at_30_percent_and_inside_envelope(self):
        draft = self.compile()
        report = (self.root / "output/audit_report.md").read_text()
        audit = json.loads(report.split("```json\n")[1].split("\n```")[0])
        current = {v["object"]: v["current_monthly"] for v in audit["verdicts"] if v["level"] == "campaign"}
        total = 0
        for campaign in draft["meta"]["campaigns"]:
            monthly = campaign["daily_budget_cents"] / 100 * 30
            total += monthly
            self.assertLessEqual(monthly, current[campaign["name"]] * 1.30 + 1)
        self.assertLessEqual(total, 65001)

    def test_written_override_keeps_cut_candidate(self):
        (self.root / "config/overrides.yaml").write_text(
            "cut_candidate_overrides:\n  Cold_Interest: Needed for geo coverage\n")
        draft = self.compile()
        self.assertIn("Cold_Interest", [c["name"] for c in draft["meta"]["campaigns"]])

    def test_compiler_does_not_touch_approved_plan(self):
        before = (self.root / "config/plan.yaml").read_text()
        self.compile()
        self.assertEqual((self.root / "config/plan.yaml").read_text(), before)


class GoogleRules(PipelineCase):
    def test_too_few_negatives_aborts(self):
        self.run_script("01_audit.py")
        path = self.root / "data/Change_Log.csv"
        rows = list(csv.DictReader(path.read_text().splitlines()))
        with path.open("w", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=rows[0].keys())
            writer.writeheader()
            for row in rows:
                row["Negatives"] = ""
                writer.writerow(row)
        result = self.run_script("04_build_google.py")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("negatives", result.stderr)

    def test_flip_is_a_plan_edit_only_when_asked(self):
        self.run_script("01_audit.py")
        self.assertEqual(self.run_script("04_build_google.py").returncode, 0)
        plan = yaml.safe_load((self.root / "config/plan.yaml").read_text())
        self.assertEqual(self.campaign(plan, "google", "Search_NonBrand_US")["bidding"], "MAXIMIZE_CONVERSIONS")
        self.assertEqual(self.run_script("04_build_google.py", "--apply-flip").returncode, 0)
        plan = yaml.safe_load((self.root / "config/plan.yaml").read_text())
        flipped = self.campaign(plan, "google", "Search_NonBrand_US")
        self.assertEqual((flipped["bidding"], flipped["target_cpa_micros"]), ("TARGET_CPA", 280000000))


class MetaPush(PipelineCase):
    """The HTTP layer is mocked. This proves request content, not acceptance by Meta."""

    def push_env(self):
        return {**self.env, "META_ACCESS_TOKEN": "test", "META_AD_ACCOUNT": "act_1", "META_PIXEL_ID": "1",
                "META_PAGE_ID": "2", "META_EXCLUSION_AUDIENCE_ID": "3"}

    def push(self):
        return subprocess.run([sys.executable, "-c", PUSH_STUB, str(SCRIPTS)], env=self.push_env(),
                              capture_output=True, text=True)

    def test_push_blocked_without_qa_pass(self):
        self.build()
        result = self.push()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("ABORT", result.stderr)
        self.assertNotIn("SENT=", result.stdout)

    def test_push_blocked_if_plan_changes_after_qa(self):
        self.build()
        self.assertEqual(self.run_script("05_qa.py").returncode, 0)
        path = self.root / "config/plan.yaml"
        path.write_text(path.read_text() + "\n# edited after QA\n")
        result = self.push()
        self.assertNotEqual(result.returncode, 0)
        self.assertNotIn("SENT=", result.stdout)

    def test_push_sends_only_paused_ready_objects(self):
        self.build()
        self.assertEqual(self.run_script("05_qa.py").returncode, 0)
        result = self.push()
        self.assertEqual(result.returncode, 0, result.stderr)
        sent = json.loads(result.stdout.split("SENT=")[1])
        statuses = [call["data"]["status"] for call in sent if "status" in call["data"]]
        self.assertTrue(statuses)
        self.assertEqual(set(statuses), {"PAUSED"})
        names = {call["data"].get("name") for call in sent}
        self.assertIn("Test_Hook_A", names)
        self.assertNotIn("Test_Hook_B", names)
        self.assertNotIn("UGC_Founder_v3_Reshot", names)
        self.assertNotIn("${", json.dumps(sent))
        self.assertTrue(all("access_token" not in call["url"] for call in sent))


if __name__ == "__main__":
    unittest.main()
