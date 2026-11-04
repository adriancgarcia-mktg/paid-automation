#!/usr/bin/env python3
"""Phase 3a: build the Meta bulk sheet, API payloads and pending creatives from the approved plan.

Default run writes files only. `--push` sends the payloads to the Marketing API, and only after
05_qa.py has passed on these exact files. No code path sets a status other than PAUSED.
"""
import argparse
import csv
import json
import os

from common import (META_CSV, META_HEADERS, META_PAYLOADS, OUTPUT, PENDING_CSV, PLAN_PATH, QA_STATUS, load_approved_plan,
                    load_audit, require, require_tracking_clear, sha256, utm_url, write_sections)

PAUSED = "PAUSED"
# Meta's API enum for a trial start is START_TRIAL. The plan and bulk sheet keep the spec's name.
API_EVENT_NAMES = {"TRIAL_START": "START_TRIAL"}
SECRET_PLACEHOLDERS = {"META_PIXEL_ID", "META_PAGE_ID", "META_EXCLUSION_AUDIENCE_ID"}


def ad_sets_for(campaign):
    """One main ad set, or one ad set per ad when the plan asks for that structure."""
    ads = campaign.get("ads", [])
    if campaign.get("structure") == "one_ad_per_adset":
        if not ads:
            raise SystemExit(f"ABORT: {campaign['name']} needs at least one ad.")
        if not campaign.get("exclusion"):
            raise SystemExit(f"ABORT: {campaign['name']} is missing its exclusion audience.")
        each = campaign["daily_budget_cents"] // len(ads)
        return [{"name": f"{campaign['name']} - {ad['name']}", "cents": each, "ads": [ad]} for ad in ads]
    return [{"name": f"{campaign['name']} - Main", "cents": campaign["daily_budget_cents"], "ads": ads}]


def is_ready(ad):
    return ad.get("creative_status") == "READY" and bool(ad.get("asset_id"))


def creative_payload(campaign, ad, url):
    require(ad, "format", "landing_url", "primary_text", "headline", "cta")
    cta = {"type": ad["cta"], "value": {"link": url}}
    if ad["format"] == "video":
        story = {"page_id": "${META_PAGE_ID}", "video_data": {
            "video_id": ad["asset_id"], "message": ad["primary_text"], "title": ad["headline"],
            "call_to_action": cta}}
    else:
        story = {"page_id": "${META_PAGE_ID}", "link_data": {
            "image_hash": ad["asset_id"], "link": url, "message": ad["primary_text"], "name": ad["headline"],
            "call_to_action": cta}}
    return {"name": f"{ad['name']} creative", "object_story_spec": story}


def build(plan):
    rows, payloads, pending = [], [], []
    headers = META_HEADERS
    for campaign in plan["meta"]["campaigns"]:
        require(campaign, "objective", "optimization_goal", "custom_event_type", "bid_strategy", "cost_cap",
                "daily_budget_cents")
        rows.append((headers["campaign"], [
            campaign["name"], PAUSED, campaign["objective"], f"{campaign['daily_budget_cents'] / 100:.2f}",
            campaign["bid_strategy"], f"{campaign['cost_cap'] / 100:.2f}"]))
        campaign_payload = {"params": {"name": campaign["name"], "objective": campaign["objective"],
                                       "status": PAUSED, "special_ad_categories": [],
                                       "is_adset_budget_sharing_enabled": False}, "adsets": []}
        for ad_set in ad_sets_for(campaign):
            rows.append((headers["adset"], [
                ad_set["name"], PAUSED, f"{ad_set['cents'] / 100:.2f}", campaign["optimization_goal"],
                campaign["custom_event_type"], ad_set["name"]]))
            targeting = {"geo_locations": {"countries": ["US"]}}
            if campaign.get("exclusion"):
                targeting["excluded_custom_audiences"] = [{"id": "${META_EXCLUSION_AUDIENCE_ID}"}]
            event = campaign["custom_event_type"]
            set_payload = {"params": {
                "name": ad_set["name"], "daily_budget": ad_set["cents"], "billing_event": "IMPRESSIONS",
                "optimization_goal": campaign["optimization_goal"], "bid_strategy": campaign["bid_strategy"],
                "bid_amount": campaign["cost_cap"], "targeting": targeting, "status": PAUSED,
                "promoted_object": {"pixel_id": "${META_PIXEL_ID}",
                                    "custom_event_type": API_EVENT_NAMES.get(event, event)}}, "ads": []}
            for ad in ad_set["ads"]:
                if not is_ready(ad):
                    pending.append([campaign["name"], ad_set["name"], ad["name"], ad.get("format", ""),
                                    ad.get("angle", ""), ad.get("replaces", ""), ad.get("creative_status", ""),
                                    ad.get("owner", ""), ad.get("due_date", "")])
                    continue
                url = utm_url(ad["landing_url"], "facebook", campaign["name"], ad["name"])
                creative = creative_payload(campaign, ad, url)
                rows.append((headers["ad"], [ad["name"], PAUSED, ad["format"], url, ad["primary_text"],
                                             ad["headline"], ad["cta"]]))
                set_payload["ads"].append({"creative": creative, "params": {"name": ad["name"], "status": PAUSED}})
            campaign_payload["adsets"].append(set_payload)
        payloads.append(campaign_payload)
    return rows, payloads, pending


def resolve(value):
    """Swap ${PLACEHOLDER} tokens for environment values at push time."""
    if isinstance(value, dict):
        return {k: resolve(v) for k, v in value.items()}
    if isinstance(value, list):
        return [resolve(v) for v in value]
    if isinstance(value, str) and value.startswith("${") and value.endswith("}"):
        return os.environ[value[2:-1]]
    return value


def encode(params):
    return {k: json.dumps(v) if isinstance(v, (dict, list, bool)) else v for k, v in params.items()}


def push():
    import requests

    if not QA_STATUS.exists():
        raise SystemExit("ABORT: no QA result. Run 05_qa.py first.")
    status = json.loads(QA_STATUS.read_text())
    passed_files = status.get("files", {})
    if (status.get("overall") != "PASS" or passed_files.get(META_PAYLOADS.name) != sha256(META_PAYLOADS)
            or passed_files.get(PLAN_PATH.name) != sha256(PLAN_PATH)):
        raise SystemExit("ABORT: QA did not pass on this exact plan and these payloads. Re-run 05_qa.py.")
    require_tracking_clear(load_audit())
    needed = {"META_ACCESS_TOKEN", "META_AD_ACCOUNT"} | SECRET_PLACEHOLDERS
    missing = sorted(name for name in needed if not os.environ.get(name))
    if missing:
        raise SystemExit(f"ABORT: missing environment variables: {', '.join(missing)}")

    base = (f"https://graph.facebook.com/{os.environ.get('META_API_VERSION', 'v21.0')}/"
            f"{os.environ['META_AD_ACCOUNT']}")
    token = os.environ["META_ACCESS_TOKEN"]
    created = []

    def create(edge, params):
        if "status" in params and params["status"] != PAUSED:
            raise SystemExit(f"ABORT: refusing to send status {params['status']}.")
        response = requests.post(f"{base}/{edge}", data={**encode(resolve(params)), "access_token": token},
                                 timeout=60)
        if response.status_code >= 400:
            (OUTPUT / "meta_created_ids.json").write_text(json.dumps(created, indent=2))
            raise SystemExit(f"ABORT: {edge} failed for {params.get('name')}: {response.text}. "
                             "Objects created so far are in output/meta_created_ids.json.")
        object_id = response.json()["id"]
        created.append({"edge": edge, "name": params.get("name"), "id": object_id})
        return object_id

    for campaign in json.loads(META_PAYLOADS.read_text()):
        campaign_id = create("campaigns", campaign["params"])
        for ad_set in campaign["adsets"]:
            ad_set_id = create("adsets", {**ad_set["params"], "campaign_id": campaign_id})
            for ad in ad_set["ads"]:
                creative_id = create("adcreatives", ad["creative"])
                create("ads", {**ad["params"], "adset_id": ad_set_id, "creative": {"creative_id": creative_id}})
    (OUTPUT / "meta_created_ids.json").write_text(json.dumps(created, indent=2))
    print(f"Created {len(created)} objects, all PAUSED. Activation stays a manual step in Ads Manager.")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--push", action="store_true", help="send QA-passed payloads to the Marketing API")
    args = parser.parse_args()
    if args.push:
        push()
        return
    require_tracking_clear(load_audit())
    rows, payloads, pending = build(load_approved_plan())
    write_sections(META_CSV, rows)
    META_PAYLOADS.write_text(json.dumps(payloads, indent=2))
    with open(PENDING_CSV, "w", newline="") as handle:
        writer = csv.writer(handle, lineterminator="\n")
        writer.writerow(["Campaign", "Ad Set", "Ad", "Format", "Angle", "Replaces", "Creative Status", "Owner", "Due Date"])
        writer.writerows(pending)
    print(f"Wrote {META_CSV}, {META_PAYLOADS} and {PENDING_CSV} ({len(pending)} pending creatives).")


if __name__ == "__main__":
    main()
