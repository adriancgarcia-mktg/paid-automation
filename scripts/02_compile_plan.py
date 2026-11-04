#!/usr/bin/env python3
"""Phase 2: map audit verdicts onto a DRAFT plan at output/plan.yaml.

The draft is never written to config/plan.yaml. A human reviews it, allocates anything left
unallocated, sets plan_status: APPROVED, and copies it to config/plan.yaml.
"""
import argparse

import yaml

from common import CONFIG, DAYS_PER_MONTH, OUTPUT, load_audit

SCALE_CAP = 0.30


def meta_campaign(name, monthly):
    return {"name": name, "objective": "OUTCOME_SALES", "buying_type": "auction",
            "optimization_goal": "OFFSITE_CONVERSIONS", "custom_event_type": "TRIAL_START",
            "bid_strategy": "COST_CAP", "cost_cap": 28000,
            "daily_budget_cents": round(monthly / DAYS_PER_MONTH * 100), "status": "PAUSED", "ads": []}


def google_campaign(name, monthly):
    brand = "brand" in name.lower() and "nonbrand" not in name.lower()
    return {"name": name, "daily_budget_micros": round(monthly / DAYS_PER_MONTH * 1_000_000),
            "bidding": "TARGET_CPA", "target_cpa_micros": 200000000 if brand else 280000000,
            "status": "PAUSED", "ad_groups": []}


def planned_monthly(verdict, overrides, notes):
    """Return the proposed monthly budget, or None when the object leaves the plan."""
    name, action = verdict["object"], verdict["verdict"]
    current = verdict["current_monthly"]
    if action == "CUT":
        return None
    if action == "CUT_CANDIDATE":
        reason = str(overrides.get(name) or "").strip()
        if not reason:
            notes.append(f"Excluded {name}: CUT_CANDIDATE with no written override.")
            return None
        notes.append(f"Kept {name} despite CUT_CANDIDATE: {reason}")
        return current
    if action == "SCALE_CANDIDATE":
        return current * (1 + SCALE_CAP)
    if action == "KEEP":
        return current
    notes.append(f"Excluded {name}: {action} needs a human budget decision.")
    return None


def allocate(verdicts, envelope, overrides, notes):
    """Fit proposed budgets inside the envelope. Spare dollars stay unallocated, never invented."""
    proposed = {}
    for verdict in verdicts:
        monthly = planned_monthly(verdict, overrides, notes)
        if monthly is not None:
            proposed[verdict["object"]] = monthly
    total = sum(proposed.values())
    if total > envelope:
        factor = envelope / total
        notes.append(f"Scaled proposals down by {1 - factor:.1%} to fit the ${envelope:,} envelope.")
        proposed = {name: monthly * factor for name, monthly in proposed.items()}
    return proposed, envelope - sum(proposed.values())


def attach_ads(campaigns, ad_verdicts, notes):
    by_name = {c["name"]: c for c in campaigns}
    replacements_required = []
    for verdict in ad_verdicts:
        name, action = verdict["object"], verdict["verdict"]
        campaign = by_name.get(verdict.get("campaign"))
        if action in ("KEEP", "SCALE_CANDIDATE") and campaign:
            campaign["ads"].append({"name": name, "creative_status": "NEEDS_ASSET"})
        elif action == "RESHOOT_ANGLE":
            if campaign:
                campaign["ads"].append({"name": f"{name}_Reshoot", "replaces": name, "fresh_creative": True,
                                        "angle": verdict.get("angle", "same_as_replaced_ad"),
                                        "creative_status": "NEEDS_ASSET"})
            else:
                replacements_required.append(name)
        elif action == "FATIGUE":
            replacements_required.append(name)
            notes.append(f"{name} is FATIGUE: add an ad with `replaces: {name}` or QA fails.")
    return replacements_required


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--envelope", default=CONFIG / "envelope.yaml")
    parser.add_argument("--overrides", default=CONFIG / "overrides.yaml")
    parser.add_argument("--out", default=OUTPUT / "plan.yaml")
    args = parser.parse_args()

    audit = load_audit()
    envelope = yaml.safe_load(open(args.envelope))
    overrides = (yaml.safe_load(open(args.overrides)) or {}).get("cut_candidate_overrides") or {}
    total = envelope["meta"] + envelope["google"] + envelope.get("reserve", 0)
    if abs(total - envelope["monthly_cap"]) > 1:
        raise SystemExit(f"ABORT: envelope allocates ${total:,} vs ${envelope['monthly_cap']:,} cap.")

    notes = []
    if audit["tracking"]["status"] != "OK":
        notes.append("TRACKING_RISK is open. This draft cannot be built until it clears.")
    verdicts = audit["verdicts"]
    plan = {"plan_status": "DRAFT", "monthly_cap": envelope["monthly_cap"],
            "brand_terms": ["[brand term 1]", "[brand term 2]"]}
    for platform, factory in (("meta", meta_campaign), ("google", google_campaign)):
        rows = [v for v in verdicts if v["platform"] == platform and v["level"] == "campaign"]
        budgets, spare = allocate(rows, envelope[platform], overrides, notes)
        plan[platform] = {"monthly_budget": envelope[platform],
                          "unallocated_monthly": round(spare, 2),
                          "campaigns": [factory(name, monthly) for name, monthly in budgets.items()]}
    plan["meta"]["replacements_required"] = attach_ads(
        plan["meta"]["campaigns"], [v for v in verdicts if v["level"] == "ad"], notes)
    plan["reserve"] = {"monthly_budget": envelope.get("reserve", 0),
                       "release_condition": "US NonBrand holds CPA <= 280 for 14 consecutive days"}
    plan["compiler_notes"] = notes

    with open(args.out, "w") as handle:
        yaml.safe_dump(plan, handle, sort_keys=False)
    print(f"Wrote DRAFT plan to {args.out}. Review it, allocate any unallocated budget, set "
          "plan_status: APPROVED, then copy it to config/plan.yaml.")
    for note in notes:
        print(f"  - {note}")


if __name__ == "__main__":
    main()
