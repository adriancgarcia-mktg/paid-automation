#!/usr/bin/env python3
"""Phase 4: the automated QA gate. Fails closed: any FAIL, or any error in a check, blocks upload."""
import csv
import json
import re
import sys
from urllib.parse import parse_qs, urlparse


from common import (ACCOUNT_NEGATIVE_LIST, BRAND_EXCEPTION_CPA, CPA_BAND, DAYS_PER_MONTH, GOOGLE_CSV,
                    GOOGLE_HEADERS, META_CSV, META_HEADERS, META_PAYLOADS, PENDING_CSV, PLAN_PATH, QA_REPORT,
                    QA_STATUS, load_audit, load_plan, read_sections, sha256)

HUMAN_CHECKLIST = [
    "Open each new campaign in the platform UI and confirm: status PAUSED, budget matches plan, bid strategy and cap match plan.",
    "Confirm tracking: pixel/dataset fires trial-start on a test signup; Google conversion action fires on a test conversion; PostHog receives the event with correct utm_source.",
    "Confirm no legacy campaign is still spending that was marked CUT (pause confirmed in UI, not just absent from the new upload).",
    "Confirm retargeting audience windows and exclusions match plan (cold excludes all warm audiences).",
    "Confirm pending_creatives.csv items have owners and due dates assigned.",
    "Screenshot each campaign's settings page into output/qa_screenshots/ for the change record.",
    "Log every change made in the account's Change_Log with date and owner, same format as the existing tab.",
]


class Context:
    def __init__(self):
        self.plan = load_plan(PLAN_PATH)
        self.audit = load_audit()
        self.meta = read_sections(META_CSV, META_HEADERS)
        self.google = read_sections(GOOGLE_CSV, GOOGLE_HEADERS)
        self.payloads = json.loads(META_PAYLOADS.read_text())
        with open(PENDING_CSV, newline="") as handle:
            self.pending = list(csv.DictReader(handle))

    def plan_campaign(self, platform, name):
        return next((c for c in self.plan[platform]["campaigns"] if c["name"] == name), {})

    def walk_google(self):
        """Yield (campaign_name, section, row) with each row tied to its campaign."""
        current = None
        for section, row in self.google:
            if section == "campaign":
                current = row["Campaign"]
            yield current, section, row

    def walk_meta(self):
        """Yield (campaign_name, ad_set_name, section, row) in file order."""
        campaign = ad_set = None
        for section, row in self.meta:
            if section == "campaign":
                campaign, ad_set = row["Campaign Name"], None
            elif section == "adset":
                ad_set = row["Ad Set Name"]
            yield campaign, ad_set, section, row


def check_budget(ctx):
    meta = sum(float(r["Campaign Daily Budget"]) for s, r in ctx.meta if s == "campaign") * DAYS_PER_MONTH
    google = sum(float(r["Daily Budget"]) for s, r in ctx.google if s == "campaign") * DAYS_PER_MONTH
    reserve = ctx.plan.get("reserve", {}).get("monthly_budget", 0)
    total, cap = meta + google + reserve, ctx.plan.get("monthly_cap", 120000)
    detail = f"Meta ${meta:,.2f} + Google ${google:,.2f} + reserve ${reserve:,} = ${total:,.2f} vs ${cap:,} cap"
    return abs(total - cap) <= 1, detail


def check_paused(ctx):
    bad = []
    for section, row in ctx.meta:
        key = {"campaign": "Campaign Status", "adset": "Ad Set Status", "ad": "Ad Status"}[section]
        if row[key] != "PAUSED":
            bad.append(f"{list(row.values())[0]}={row[key]!r}")
    for section, row in ctx.google:
        key = {"campaign": "Campaign Status", "adgroup": "Ad group status"}.get(section)
        if key and row[key] != "Paused":
            bad.append(f"{list(row.values())[0]}={row[key]!r}")
    for path in (META_CSV, GOOGLE_CSV):
        if re.search(r"\b(ACTIVE|ENABLED)\b", path.read_text()):
            bad.append(f"{path.name} contains an active status value")
    for campaign in ctx.payloads:
        objects = [campaign["params"]]
        for ad_set in campaign["adsets"]:
            objects.append(ad_set["params"])
            objects += [ad["params"] for ad in ad_set["ads"]]
        bad += [f"payload {o['name']}={o.get('status')!r}" for o in objects if o.get("status") != "PAUSED"]
    return not bad, "; ".join(bad) or "All generated objects are paused"


def check_cost_caps(ctx):
    low, high = CPA_BAND
    bad = []
    for section, row in ctx.meta:
        if section == "campaign":
            value = float(row["Campaign Cost Cap"] or 0)
            if not low <= value <= high:
                bad.append(f"{row['Campaign Name']} cost cap ${value:.2f}")
    for section, row in ctx.google:
        if section != "campaign":
            continue
        name, raw = row["Campaign"], row["Target CPA"]
        if not raw:
            if not ctx.plan_campaign("google", name).get("tcpa_deferred_until"):
                bad.append(f"{name} has no tCPA and no documented deferral")
            continue
        value = float(raw)
        is_brand = "brand" in name.lower() and "nonbrand" not in name.lower()
        if not low <= value <= high and not (is_brand and value == BRAND_EXCEPTION_CPA):
            bad.append(f"{name} tCPA ${value:.2f}")
    return not bad, "; ".join(bad) or f"All caps are within ${low}-${high} or the Brand ${BRAND_EXCEPTION_CPA} exception"


def check_no_cut_objects(ctx):
    cut = {v["object"] for v in ctx.audit["verdicts"] if v["verdict"] == "CUT"}
    found = set()
    for rows in (ctx.meta, ctx.google):
        for _, row in rows:
            for value in row.values():
                found |= {name for name in cut if value == name or value.startswith(f"{name} - ")}
    return not found, f"CUT objects present: {sorted(found)}" if found else f"None of {len(cut)} CUT objects appear"


def check_replacements(ctx):
    needed = {v["object"] for v in ctx.audit["verdicts"] if v["verdict"] in ("RESHOOT_ANGLE", "FATIGUE")}
    replaced = {ad.get("replaces") for c in ctx.plan["meta"]["campaigns"] for ad in c.get("ads", [])}
    missing = sorted(needed - replaced)
    return not missing, f"No replacement in plan for: {missing}" if missing else f"All {len(needed)} have replacements"


def check_creative_testing(ctx):
    name = "Creative_Testing"
    spec = ctx.plan_campaign("meta", name)
    if not spec:
        return False, f"{name} is not in the plan"
    counts = {}
    for campaign, ad_set, section, row in ctx.walk_meta():
        if campaign == name and section == "adset":
            counts[ad_set] = 0
        elif campaign == name and section == "ad":
            counts[ad_set] += 1
    for item in ctx.pending:
        if item["Campaign"] == name:
            counts[item["Ad Set"]] = counts.get(item["Ad Set"], 0) + 1
    wrong = {k: v for k, v in counts.items() if v != 1}
    payload = next((c for c in ctx.payloads if c["params"]["name"] == name), {"adsets": []})
    excluded = bool(payload["adsets"]) and all(
        s["params"]["targeting"].get("excluded_custom_audiences") for s in payload["adsets"])
    if not counts or wrong:
        return False, f"Ads per ad set (live + pending) must be 1: {wrong or 'no ad sets'}"
    if not spec.get("exclusion") or not excluded:
        return False, "Exclusion audience missing from the plan or the ad set payloads"
    return True, f"{len(counts)} ad sets with one ad each; exclusion audience present"


def check_pmax_negatives(ctx):
    terms = set(ctx.plan.get("brand_terms") or [])
    pmax = [c["name"] for c in ctx.plan["google"]["campaigns"] if c.get("type") == "pmax"]
    if not pmax or not terms:
        return False, "No PMax campaign or no brand terms in the plan"
    for name in pmax:
        rows = [(s, r) for c, s, r in ctx.walk_google() if c == name and s != "campaign"]
        first = rows[0] if rows else None
        if not first or first[0] != "adgroup" or first[1]["Ad group type"] != ACCOUNT_NEGATIVE_LIST:
            return False, f"{name}: brand negative list must come before its asset groups"
        attached = {t.strip() for t in first[1]["Negatives"].split(";")}
        if not terms <= attached:
            return False, f"{name}: missing brand negatives {sorted(terms - attached)}"
    return True, f"{', '.join(pmax)} has {len(terms)} brand negatives attached first"


def check_tracking(ctx):
    status = ctx.audit.get("tracking", {}).get("status")
    return status == "OK", f"Phase 1 tracking status: {status}"


def utm_problem(url, source, campaign, ad):
    query = parse_qs(urlparse(url).query)
    expected = {"utm_source": source, "utm_campaign": campaign, "utm_content": ad}
    if any(query.get(key) != [value] for key, value in expected.items()):
        return f"{ad}: {url}"
    return None


def check_utms(ctx):
    bad, count = [], 0
    for campaign, _, section, row in ctx.walk_meta():
        if section == "ad":
            count += 1
            bad.append(utm_problem(row["Link URL"], "facebook", campaign, row["Ad Name"]))
    for campaign, section, row in ctx.walk_google():
        if section == "ad":
            count += 1
            bad.append(utm_problem(row["Final URL"], "google", campaign, row["Ad name"]))
    bad = [item for item in bad if item]
    return not bad and count > 0, "; ".join(bad) or f"{count} ad URLs match the naming convention"


def check_plan_is_source_of_truth(ctx):
    """Guardrail: nothing is generated that is not in the plan, and nothing in the plan is dropped."""
    generated = {r["Campaign Name"] for s, r in ctx.meta if s == "campaign"} | {
        r["Campaign"] for s, r in ctx.google if s == "campaign"}
    planned = {c["name"] for p in ("meta", "google") for c in ctx.plan[p]["campaigns"]}
    extra, dropped = sorted(generated - planned), sorted(planned - generated)
    if extra or dropped:
        return False, f"Not in plan: {extra}; missing from files: {dropped}"
    return True, f"Generated campaigns match the {len(planned)} in the plan"


CHECKS = [
    ("Budget sum equals the monthly cap within $1", check_budget),
    ("Every generated object is PAUSED", check_paused),
    ("Cost caps and tCPAs are in band or the Brand exception", check_cost_caps),
    ("No CUT object appears in any generated file", check_no_cut_objects),
    ("RESHOOT_ANGLE and FATIGUE ads have replacements in the plan", check_replacements),
    ("Creative_Testing has one ad per ad set and its exclusion", check_creative_testing),
    ("PMax has brand negatives attached", check_pmax_negatives),
    ("PostHog reconciliation passed (no open TRACKING_RISK)", check_tracking),
    ("UTMs match the naming convention", check_utms),
    ("Generated campaigns exactly match the approved plan", check_plan_is_source_of_truth),
]


def main():
    results = []
    try:
        ctx = Context()
    except (Exception, SystemExit) as error:
        ctx = None
        results.append(("Load plan, audit and generated files", False, str(error)))
    if ctx:
        for name, check in CHECKS:
            try:
                passed, detail = check(ctx)
            except Exception as error:  # A check that cannot run has not passed.
                passed, detail = False, f"Check error: {error!r}"
            results.append((name, passed, detail))

    overall = "PASS" if all(passed for _, passed, _ in results) else "FAIL"
    lines = ["# QA report", "", f"Automated gate: **{overall}**", "", "| # | Check | Result | Detail |", "|---|---|---|---|"]
    for number, (name, passed, detail) in enumerate(results, 1):
        lines.append(f"| {number} | {name} | {'PASS' if passed else '**FAIL**'} | {detail} |")
    lines += ["", "## Human checklist (operator, after upload and before activation)", ""]
    lines += [f"- [ ] {item}" for item in HUMAN_CHECKLIST]
    lines += ["", "Only after every box is checked: activate ads first, then ad sets, then campaigns, one "
              "platform at a time, re-reading each object's status as ACTIVE before moving on.", ""]
    QA_REPORT.parent.mkdir(exist_ok=True)
    QA_REPORT.write_text("\n".join(lines))

    files = {}
    if overall == "PASS":
        files = {p.name: sha256(p) for p in (PLAN_PATH, META_CSV, GOOGLE_CSV, META_PAYLOADS)}
    QA_STATUS.write_text(json.dumps({"overall": overall, "files": files}, indent=2))
    for name, passed, detail in results:
        print(f"{'PASS' if passed else 'FAIL'}  {name}: {detail}")
    print(f"Automated gate: {overall}. Report: {QA_REPORT}")
    sys.exit(0 if overall == "PASS" else 1)


if __name__ == "__main__":
    main()
