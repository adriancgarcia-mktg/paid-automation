#!/usr/bin/env python3
"""Phase 3b: build the Google Ads Editor CSV from the approved plan."""
import argparse

import pandas as pd
import yaml

from common import (ACCOUNT_NEGATIVE_LIST, DATA, GOOGLE_CSV, GOOGLE_HEADERS, PLAN_PATH, load_approved_plan,
                    load_audit, require, require_tracking_clear, utm_url, write_sections)

PAUSED = "Paused"
BID_LABELS = {"TARGET_CPA": "Target CPA", "MAXIMIZE_CONVERSIONS": "Maximize conversions"}
MIN_NEGATIVES = 40
FLIP_MIN_MONTHLY = 30
FLIP_TARGET_MICROS = 280000000


def change_log_negatives():
    log = pd.read_csv(DATA / "Change_Log.csv")
    terms = []
    if "Negatives" in log:
        for cell in log["Negatives"].dropna():
            terms += [term.strip() for term in str(cell).split(";") if term.strip()]
    return terms


def resolve_negatives(audit):
    merged = list(dict.fromkeys(change_log_negatives() + audit.get("new_negatives", [])))
    if len(merged) < MIN_NEGATIVES:
        raise SystemExit(f"ABORT: found {len(merged)} negatives, need at least {MIN_NEGATIVES}. "
                         "Add the list to the Negatives column in data/Change_Log.csv.")
    return merged


def campaign_rows(campaign, plan, audit):
    headers = GOOGLE_HEADERS
    require(campaign, "daily_budget_micros", "bidding")
    if campaign["bidding"] not in BID_LABELS:
        raise SystemExit(f"ABORT: {campaign['name']} has unknown bidding {campaign['bidding']}.")
    target = campaign.get("target_cpa_micros")
    if not target and not campaign.get("tcpa_deferred_until"):
        raise SystemExit(f"ABORT: {campaign['name']} has no tCPA and no documented tcpa_deferred_until.")
    pmax = campaign.get("type") == "pmax"
    rows = [(headers["campaign"], [
        campaign["name"], f"{campaign['daily_budget_micros'] / 1_000_000:.2f}", BID_LABELS[campaign["bidding"]],
        f"{target / 1_000_000:.2f}" if target else "", PAUSED,
        "All Google networks" if pmax else "Search; Search partners", "United States", "English"])]
    if campaign.get("brand_negation"):
        if not plan.get("brand_terms"):
            raise SystemExit(f"ABORT: {campaign['name']} needs brand_terms in the plan.")
        # Written first so the negative list precedes the campaign's asset groups.
        rows.append((headers["adgroup"], ["Brand_Negatives", ACCOUNT_NEGATIVE_LIST, "", PAUSED, "", "",
                                          "; ".join(plan["brand_terms"])]))
    negatives = resolve_negatives(audit) if campaign.get("negatives") else []
    for group in campaign.get("ad_groups", []):
        keywords = "; ".join(group.get("keywords", []))
        for match_type in (campaign.get("match_types") or [""]):
            rows.append((headers["adgroup"], [group["name"], group["type"], "", PAUSED, keywords,
                                              match_type.capitalize(), "; ".join(negatives)]))
        for ad in group.get("ads", []):
            require(ad, "name", "type", "headlines", "descriptions", "landing_url")
            url = utm_url(ad["landing_url"], "google", campaign["name"], ad["name"])
            rows.append((headers["ad"], [ad["type"], ad["name"], *ad["headlines"][:3], *ad["descriptions"][:2],
                                         url, ad.get("path1", ""), ad.get("path2", "")]))
    return rows


def flip_candidates(plan):
    """Deferred-tCPA campaigns with 30+ conversions in each of the last two full months."""
    daily = pd.read_csv(DATA / "Google_Daily.csv")
    daily["Month"] = pd.to_datetime(daily["Date"]).dt.to_period("M")
    ready = []
    for campaign in plan["google"]["campaigns"]:
        if not campaign.get("tcpa_deferred_until"):
            continue
        months = daily[daily["Campaign"] == campaign["name"]].groupby("Month")["Conversions"].sum().sort_index()
        if len(months) >= 2 and (months.iloc[-2:] >= FLIP_MIN_MONTHLY).all():
            ready.append(campaign)
    return ready


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply-flip", action="store_true",
                        help="edit config/plan.yaml to tCPA 280 for campaigns that sustained 30 conversions/month")
    args = parser.parse_args()
    audit = load_audit()
    require_tracking_clear(audit)
    plan = load_approved_plan()
    ready = flip_candidates(plan)
    if ready and args.apply_flip:
        for campaign in ready:
            campaign.update(bidding="TARGET_CPA", target_cpa_micros=FLIP_TARGET_MICROS)
            del campaign["tcpa_deferred_until"]
            print(f"Plan edit: {campaign['name']} flipped to tCPA $280.")
        with open(PLAN_PATH, "w") as handle:
            yaml.safe_dump(plan, handle, sort_keys=False)
    elif ready:
        names = ", ".join(c["name"] for c in ready)
        print(f"Eligible for the tCPA 280 flip: {names}. Re-run with --apply-flip to make the plan edit.")
    rows = []
    for campaign in plan["google"]["campaigns"]:
        rows += campaign_rows(campaign, plan, audit)
    write_sections(GOOGLE_CSV, rows)
    print(f"Wrote {GOOGLE_CSV}")


if __name__ == "__main__":
    main()
