"""Shared paths, thresholds, guardrails and file parsing for the pipeline."""
import csv
import hashlib
import json
import os
import re
from pathlib import Path

import yaml

ROOT = Path(os.environ.get("PAID_AUTOMATION_ROOT", Path(__file__).resolve().parent.parent))
DATA, CONFIG, OUTPUT = ROOT / "data", ROOT / "config", ROOT / "output"
PLAN_PATH = CONFIG / "plan.yaml"
AUDIT_PATH = OUTPUT / "audit_report.md"
META_CSV = OUTPUT / "meta_bulk_upload.csv"
GOOGLE_CSV = OUTPUT / "google_ads_editor.csv"
META_PAYLOADS = OUTPUT / "meta_api_payloads.json"
PENDING_CSV = OUTPUT / "pending_creatives.csv"
QA_REPORT = OUTPUT / "qa_report.md"
QA_STATUS = OUTPUT / "qa_status.json"

MONTHLY_CAP = 120000
DAYS_PER_MONTH = 30
CPA_BAND = (250, 280)
BRAND_EXCEPTION_CPA = 200

META_HEADERS = {
    "campaign": ["Campaign Name", "Campaign Status", "Campaign Objective", "Campaign Daily Budget",
                 "Campaign Bid Strategy", "Campaign Cost Cap"],
    # The spec's header repeats "Ad Set Name" in the last column. Kept exactly as specified.
    "adset": ["Ad Set Name", "Ad Set Status", "Ad Set Daily Budget", "Optimization Goal",
              "Custom Event Type", "Ad Set Name"],
    "ad": ["Ad Name", "Ad Status", "Format", "Link URL", "Primary Text", "Headline", "CTA"],
}
GOOGLE_HEADERS = {
    "campaign": ["Campaign", "Daily Budget", "Bid Strategy", "Target CPA", "Campaign Status",
                 "Networks", "Location", "Language"],
    "adgroup": ["Ad group", "Ad group type", "Max CPC", "Ad group status", "Keywords",
                "Keyword match type", "Negatives"],
    "ad": ["Ad type", "Ad name", "Headline 1", "Headline 2", "Headline 3", "Description 1",
           "Description 2", "Final URL", "Path 1", "Path 2"],
}
ACCOUNT_NEGATIVE_LIST = "Account negative list"


def campaign_monthly(platform, campaign):
    if platform == "meta":
        return campaign["daily_budget_cents"] / 100 * DAYS_PER_MONTH
    return campaign["daily_budget_micros"] / 1_000_000 * DAYS_PER_MONTH


def reconcile(plan, monthly_cap=MONTHLY_CAP):
    """Abort unless the plan's stated and per-campaign budgets all reconcile to the cap."""
    total = (plan["meta"]["monthly_budget"] + plan["google"]["monthly_budget"]
             + plan.get("reserve", {}).get("monthly_budget", 0))
    if abs(total - monthly_cap) > 1:
        raise SystemExit(f"ABORT: plan allocates ${total} vs ${monthly_cap} cap. "
                         "Fix plan.yaml before building.")
    for platform in ("meta", "google"):
        stated = plan[platform]["monthly_budget"]
        allocated = sum(campaign_monthly(platform, c) for c in plan[platform]["campaigns"])
        if abs(allocated - stated) > 1:
            raise SystemExit(f"ABORT: {platform} campaigns allocate ${allocated:,.2f}/mo vs "
                             f"${stated:,} stated. Fix plan.yaml before building.")


def load_plan(path=PLAN_PATH):
    with open(path) as handle:
        return yaml.safe_load(handle)


def load_approved_plan(path=PLAN_PATH):
    """Load a plan for building: approved, reconciled, and PAUSED on every object."""
    plan = load_plan(path)
    if plan.get("plan_status") != "APPROVED":
        raise SystemExit(f"ABORT: {path} has plan_status={plan.get('plan_status')!r}. "
                         "Only an APPROVED plan can be built.")
    for platform in ("meta", "google"):
        for campaign in plan[platform]["campaigns"]:
            if campaign.get("status") != "PAUSED":
                raise SystemExit(f"ABORT: {campaign['name']} is not PAUSED in the plan.")
    reconcile(plan, plan.get("monthly_cap", MONTHLY_CAP))
    return plan


def load_audit(path=AUDIT_PATH):
    if not Path(path).exists():
        raise SystemExit(f"ABORT: {path} not found. Run 01_audit.py first.")
    match = re.search(r"```json\n(.*?)\n```", Path(path).read_text(), re.S)
    if not match:
        raise SystemExit(f"ABORT: no verdict JSON block in {path}.")
    return json.loads(match.group(1))


def require_tracking_clear(audit):
    if audit.get("tracking", {}).get("status") != "OK":
        raise SystemExit("ABORT: open TRACKING_RISK flag from Phase 1. Resolve it and re-run "
                         "01_audit.py before building.")


def utm_url(base, source, campaign, ad):
    separator = "&" if "?" in base else "?"
    return f"{base}{separator}utm_source={source}&utm_campaign={campaign}&utm_content={ad}"


def require(spec, *fields):
    missing = [f for f in fields if spec.get(f) in (None, "")]
    if missing:
        raise SystemExit(f"ABORT: {spec.get('name', spec)} is missing {', '.join(missing)} in the "
                         "plan. Generators do not fall back to platform defaults.")


def read_sections(path, headers):
    """Parse a stacked CSV into (section, columns_as_dict) rows, in file order."""
    rows = []
    current = None
    with open(path, newline="") as handle:
        for cells in csv.reader(handle):
            section = next((name for name, header in headers.items() if cells == header), None)
            if section:
                current = section
            elif cells:
                if current is None:
                    raise ValueError(f"{path}: data row before any header: {cells}")
                rows.append((current, dict(zip(headers[current], cells))))
    return rows


def write_sections(path, rows):
    """Write (header, values) pairs, repeating a header only when the section changes."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="") as handle:
        writer = csv.writer(handle, lineterminator="\n")
        previous = None
        for header, values in rows:
            if header is not previous:
                writer.writerow(header)
            writer.writerow(values)
            previous = header


def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()
