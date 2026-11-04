#!/usr/bin/env python3
"""Phase 1: score campaigns and ads, reconcile tracking, write output/audit_report.md."""
import json
import sys

import pandas as pd

from common import AUDIT_PATH, DATA, OUTPUT

TARGET_CPA = 265            # midpoint of the 250-280 band
TARGET_TOLERANCE = 0.10     # +/-10% around target
ZERO_CONV_MIN_SPEND = 1000
ZERO_CONV_MIN_DAYS = 14
FATIGUE_FREQ = 2.0
META_MIN_CTR = 0.015
TRACKING_DRIFT = 0.15
CHANGE_WINDOW_DAYS = 7
CHANGE_SHIFT = 0.20         # a 20% move in the post-change window counts as a shift
NEGATIVE_MIN_SPEND = 100    # optional Search_Terms.csv: zero-conversion terms above this


def conversion_column(df):
    """Find the conversion count, skipping derived columns such as 'Conversion rate'."""
    for column in df.columns:
        lowered = column.lower().strip()
        if lowered in ("trials", "trial", "conversions", "conversion", "trial starts"):
            return column
    raise SystemExit(f"ABORT: no conversion count column in {list(df.columns)}")


def score(spend, conversions, days):
    cpa = spend / conversions if conversions else None
    if conversions == 0 and spend >= ZERO_CONV_MIN_SPEND and days >= ZERO_CONV_MIN_DAYS:
        verdict = "CUT"
    elif cpa is None:
        verdict = "INSUFFICIENT_DATA"
    elif cpa > TARGET_CPA * (1 + TARGET_TOLERANCE):
        verdict = "CUT_CANDIDATE"
    elif cpa < TARGET_CPA * (1 - TARGET_TOLERANCE):
        verdict = "SCALE_CANDIDATE"
    else:
        verdict = "KEEP"
    return verdict, cpa


def evidence_line(spend, conversions, cpa, days):
    if conversions == 0:
        return f"${spend:,.0f} spend, 0 conversions in {days} days"
    return f"${spend:,.0f} spend, {conversions:.0f} conversions, ${cpa:,.0f} CPA over {days} days"


def audit_campaigns(df, platform):
    column = conversion_column(df)
    df = df.assign(Date=pd.to_datetime(df["Date"]))
    out = []
    for campaign, group in df.groupby("Campaign"):
        spend, conversions = float(group["Spend ($)"].sum()), float(group[column].sum())
        days = (group["Date"].max() - group["Date"].min()).days + 1
        verdict, cpa = score(spend, conversions, days)
        ctr = group["Clicks"].sum() / group["Impressions"].sum() if group["Impressions"].sum() else 0
        flags = ["LOW_CTR"] if platform == "meta" and ctr < META_MIN_CTR else []
        out.append({"object": campaign, "level": "campaign", "platform": platform, "verdict": verdict,
                    "evidence": evidence_line(spend, conversions, cpa, days), "spend": round(spend, 2),
                    "conversions": conversions, "cpa": round(cpa, 2) if cpa else None, "days": days,
                    "ctr": round(float(ctr), 4), "flags": flags,
                    "current_monthly": round(spend / days * 30, 2)})
    return out


def audit_ads(ads):
    ads = ads.copy()
    ads["CPA ($)"] = pd.to_numeric(ads["CPA ($)"], errors="coerce")
    ads["Week starting"] = pd.to_datetime(ads["Week starting"])
    column = conversion_column(ads)
    out = []
    for ad, group in ads.groupby("Ad name"):
        group = group.sort_values("Week starting")
        spend, conversions = float(group["Spend ($)"].sum()), float(group[column].sum())
        days = len(group) * 7
        verdict, cpa = score(spend, conversions, days)
        ctr = group["Clicks"].sum() / group["Impressions"].sum() if group["Impressions"].sum() else 0
        flags = ["LOW_CTR"] if ctr < META_MIN_CTR else []
        evidence = evidence_line(spend, conversions, cpa, days)
        weekly_cpa = group["CPA ($)"].dropna().values
        frequency = group["Frequency"].values
        fatigued = (frequency[-1] > FATIGUE_FREQ and len(weekly_cpa) >= 2
                    and weekly_cpa[-1] > weekly_cpa[-2])
        if fatigued and verdict != "CUT":
            flags.append("FATIGUE")
            evidence = (f"${cpa:,.0f} CPA lifetime, freq {frequency[0]}->{frequency[-1]}, "
                        f"weekly CPA ${weekly_cpa[-2]:,.0f}->${weekly_cpa[-1]:,.0f}")
            # The angle earned its keep but the creative wore out: reshoot it. Otherwise replace it.
            verdict = "FATIGUE" if verdict == "CUT_CANDIDATE" else "RESHOOT_ANGLE"
        out.append({"object": ad, "level": "ad", "platform": "meta", "verdict": verdict,
                    "evidence": evidence, "spend": round(spend, 2), "conversions": conversions,
                    "cpa": round(cpa, 2) if cpa else None, "days": days, "ctr": round(float(ctr), 4),
                    "flags": flags, "campaign": group["Campaign"].iloc[-1]})
    return out


def monthly_slices(df, platform):
    column = conversion_column(df)
    months = pd.to_datetime(df["Date"]).dt.strftime("%Y-%m")
    grouped = df.groupby(months).agg(spend=("Spend ($)", "sum"), impressions=("Impressions", "sum"),
                                     clicks=("Clicks", "sum"), conversions=(column, "sum"))
    return [{"platform": platform, "month": month, **{k: float(v) for k, v in row.items()}}
            for month, row in grouped.iterrows()]


def reconcile_tracking(meta, google, posthog):
    trials = conversion_column(posthog)
    by_source = {}
    risky = False
    for source, frame in (("facebook", meta), ("google", google)):
        platform_total = float(frame[conversion_column(frame)].sum())
        posthog_total = float(posthog.loc[posthog["utm_source"] == source, trials].sum())
        drift = abs(platform_total - posthog_total) / posthog_total if posthog_total else None
        ok = drift is not None and drift <= TRACKING_DRIFT
        risky = risky or not ok
        by_source[source] = {"platform": platform_total, "posthog": posthog_total,
                             "drift": round(drift, 4) if drift is not None else None,
                             "status": "OK" if ok else "TRACKING_RISK"}
    return {"status": "TRACKING_RISK" if risky else "OK", "by_source": by_source}


def window_metrics(frame, column):
    spend, conversions = frame["Spend ($)"].sum(), frame[column].sum()
    impressions, clicks = frame["Impressions"].sum(), frame["Clicks"].sum()
    return {"conversions": conversions, "CTR": clicks / impressions if impressions else None,
            "CVR": conversions / clicks if clicks else None,
            "CPA": spend / conversions if conversions else None}


def change_impacts(changes, frames):
    """Compare the 7 days before each logged change with the 7 days after it."""
    out = []
    window = pd.Timedelta(days=CHANGE_WINDOW_DAYS)
    for _, change in changes.iterrows():
        frame = frames.get(str(change["Platform"]).lower())
        if frame is None:
            continue
        column = conversion_column(frame)
        frame = frame.assign(Date=pd.to_datetime(frame["Date"]))
        if str(change["Campaign"]).lower() != "all":
            frame = frame[frame["Campaign"] == change["Campaign"]]
        day = pd.to_datetime(change["Date"])
        before = window_metrics(frame[(frame["Date"] < day) & (frame["Date"] >= day - window)], column)
        after = window_metrics(frame[(frame["Date"] >= day) & (frame["Date"] < day + window)], column)
        for metric in before:
            old, new = before[metric], after[metric]
            if not old or new is None:
                continue
            shift = (new - old) / old
            worse = shift >= CHANGE_SHIFT if metric == "CPA" else shift <= -CHANGE_SHIFT
            if worse:
                out.append({"flag": "CAUSED_BY_CHANGE", "change": change["Change"],
                            "date": str(change["Date"]), "object": change["Campaign"],
                            "metric": metric, "before": round(float(old), 4),
                            "after": round(float(new), 4), "shift": round(float(shift), 3)})
    return out


def new_negatives():
    """Zero-conversion search terms from the optional Search_Terms.csv export."""
    path = DATA / "Search_Terms.csv"
    if not path.exists():
        return []
    terms = pd.read_csv(path)
    wasted = terms[(terms["Conversions"] == 0) & (terms["Spend ($)"] >= NEGATIVE_MIN_SPEND)]
    return sorted(wasted["Search term"].astype(str).unique().tolist())


def verdict_table(rows):
    lines = ["| Object | Verdict | Spend | Conversions | CPA | Flags | Evidence |",
             "|---|---|---|---|---|---|---|"]
    for row in rows:
        cpa = f"${row['cpa']:,.0f}" if row["cpa"] else "n/a"
        lines.append(f"| {row['object']} | **{row['verdict']}** | ${row['spend']:,.0f} | "
                     f"{row['conversions']:.0f} | {cpa} | {', '.join(row['flags']) or '-'} | "
                     f"{row['evidence']} |")
    return lines


def render(meta_campaigns, google_campaigns, ads, tracking, impacts, slices, negatives):
    verdicts = meta_campaigns + ads + google_campaigns
    lines = ["# Audit report", "", "## Tracking reconciliation", "",
             f"Status: **{tracking['status']}** (tolerance {TRACKING_DRIFT:.0%})", "",
             "| utm_source | Platform | PostHog | Drift | Status |", "|---|---|---|---|---|"]
    for source, row in tracking["by_source"].items():
        drift = f"{row['drift']:.1%}" if row["drift"] is not None else "n/a"
        lines.append(f"| {source} | {row['platform']:.0f} | {row['posthog']:.0f} | {drift} | {row['status']} |")
    lines += ["", "## Meta", "", "### Campaigns", ""] + verdict_table(meta_campaigns)
    lines += ["", "### Ads", ""] + verdict_table(ads)
    lines += ["", "## Google", "", "### Campaigns", ""] + verdict_table(google_campaigns)
    lines += ["", "## Monthly slices", "", "| Platform | Month | Spend | Impressions | Clicks | Conversions |",
              "|---|---|---|---|---|---|"]
    for row in slices:
        lines.append(f"| {row['platform']} | {row['month']} | ${row['spend']:,.0f} | "
                     f"{row['impressions']:,.0f} | {row['clicks']:,.0f} | {row['conversions']:.0f} |")
    lines += ["", "## Change impact (7 days after vs 7 days before)", ""]
    lines += [f"- **CAUSED_BY_CHANGE**: {i['object']} {i['metric']} moved {i['shift']:+.0%} after "
              f"\"{i['change']}\" ({i['date']})" for i in impacts] or ["None flagged."]
    payload = {"verdicts": verdicts, "tracking": tracking, "change_impacts": impacts,
               "new_negatives": negatives}
    lines += ["", "## Verdict JSON", "", "```json", json.dumps(payload, indent=2), "```", ""]
    return "\n".join(lines)


def main():
    meta = pd.read_csv(DATA / "Meta_Daily.csv")
    google = pd.read_csv(DATA / "Google_Daily.csv")
    ads = pd.read_csv(DATA / "Meta_Ads_Weekly.csv")
    posthog = pd.read_csv(DATA / "Trials_PostHog.csv")
    changes = pd.read_csv(DATA / "Change_Log.csv")

    meta_campaigns = audit_campaigns(meta, "meta")
    google_campaigns = audit_campaigns(google, "google")
    ad_verdicts = audit_ads(ads)
    tracking = reconcile_tracking(meta, google, posthog)
    impacts = change_impacts(changes, {"meta": meta, "google": google})
    slices = monthly_slices(meta, "meta") + monthly_slices(google, "google")

    OUTPUT.mkdir(exist_ok=True)
    AUDIT_PATH.write_text(render(meta_campaigns, google_campaigns, ad_verdicts, tracking, impacts,
                                 slices, new_negatives()))
    print(f"Wrote {AUDIT_PATH}")
    if tracking["status"] != "OK":
        print("TRACKING_RISK: platform totals drift more than 15% from PostHog. Build phase halted.")
        sys.exit(2)


if __name__ == "__main__":
    main()
