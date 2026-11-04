#!/usr/bin/env python3
"""Write deterministic, entirely synthetic exports to data/ so the pipeline can be run as a demo."""
import csv
import math
from datetime import date, timedelta

from common import DATA

START, END = date(2026, 8, 1), date(2026, 10, 31)
CHANGE_DAY = date(2026, 9, 15)
NEGATIVES = ["free", "jobs", "careers", "salary", "login", "support", "reddit", "wiki", "template",
             "tutorial", "course", "certification", "internship", "definition", "meaning", "pdf",
             "download", "crack", "torrent", "cheap", "diy", "open source", "alternative to excel",
             "review scam", "cancel", "refund", "phone number", "address", "stock", "layoffs",
             "news", "history", "examples", "homework", "university", "student discount", "ppt",
             "resume", "interview questions", "glassdoor", "indeed", "linkedin"]

# name, platform, daily spend, target CPA, first day, last day, CTR
CAMPAIGNS = [
    ("Cold_Broad", "meta", 1100, 225, START, END, 0.019),
    ("Cold_Interest", "meta", 500, 300, START, END, 0.013),
    ("Retargeting_30d", "meta", 170, 190, START, END, 0.024),
    ("Search_Brand_US", "google", 260, 110, START, END, 0.11),
    ("Search_NonBrand_US", "google", 1000, 270, START, END, 0.035),
    ("Search_NonBrand_UK", "google", 558.9, None, date(2026, 8, 1), date(2026, 8, 27), 0.028),
    ("PMax_US", "google", 330, 275, START, END, 0.012),
]
# name, campaign, weekly spend, weekly CPAs, frequency start, frequency end, CTR
ADS = [
    ("UGC_Founder_v2", "Cold_Broad", 3500, [150, 165, 180, 205, 240, 300], 1.4, 3.85, 0.021),
    ("Static_BenefitStack_A", "Cold_Broad", 2500, [255, 250, 262, 258, 265, 260], 1.2, 1.6, 0.018),
    ("Carousel_Old", "Cold_Interest", 1800, [340, 370, 390, 430, 470, 520], 1.6, 3.1, 0.012),
    ("Video_Hook_Test3", "Cold_Interest", 500, [None, None, None], 1.1, 1.3, 0.016),
]


def days():
    current = START
    while current <= END:
        yield current
        current += timedelta(days=1)


def write(name, header, rows):
    with open(DATA / name, "w", newline="") as handle:
        writer = csv.writer(handle, lineterminator="\n")
        writer.writerow(header)
        writer.writerows(rows)


def main():
    DATA.mkdir(exist_ok=True)
    daily = {"meta": [], "google": []}
    totals = {("meta", d): 0 for d in days()}
    totals.update({("google", d): 0 for d in days()})
    for name, platform, spend, cpa, first, last, ctr in CAMPAIGNS:
        banked = 0.0
        for index, day in enumerate(days()):
            if not first <= day <= last:
                continue
            today = round(spend * (1 + 0.08 * math.sin(index / 3)), 2)
            impressions = int(today * 45)
            today_ctr = ctr
            # Cold_Interest visibly worsens after the logged 2026-09-15 change.
            today_cpa = cpa * 1.6 if name == "Cold_Interest" and day >= CHANGE_DAY else cpa
            if name == "Cold_Interest" and day >= CHANGE_DAY:
                today_ctr = ctr * 0.7
            conversions = 0
            if cpa:
                banked += today / today_cpa
                conversions, banked = int(banked), banked - int(banked)
            daily[platform].append([day.isoformat(), name, today, impressions,
                                    int(impressions * today_ctr), conversions])
            totals[(platform, day)] += conversions
    write("Meta_Daily.csv", ["Date", "Campaign", "Spend ($)", "Impressions", "Clicks", "Trials"],
          daily["meta"])
    write("Google_Daily.csv", ["Date", "Campaign", "Spend ($)", "Impressions", "Clicks", "Conversions"],
          daily["google"])

    posthog = []
    carried = {"meta": 0.0, "google": 0.0}
    for (platform, day), count in sorted(totals.items(), key=lambda kv: (kv[0][1], kv[0][0])):
        source = "facebook" if platform == "meta" else "google"
        # PostHog sits about 5% under platform totals, inside the 15% tolerance.
        carried[platform] += count * 0.95
        whole = int(carried[platform])
        carried[platform] -= whole
        posthog.append([day.isoformat(), source, whole])
    write("Trials_PostHog.csv", ["Date", "utm_source", "Trials"], posthog)

    weekly = []
    for name, campaign, spend, cpas, freq_start, freq_end, ctr in ADS:
        for index, cpa in enumerate(cpas):
            week = date(2026, 9, 7) + timedelta(weeks=index)
            conversions = round(spend / cpa) if cpa else 0
            frequency = round(freq_start + (freq_end - freq_start) * index / (len(cpas) - 1), 2)
            impressions = int(spend * 45)
            weekly.append([week.isoformat(), campaign, name, spend, impressions,
                           int(impressions * ctr), conversions, frequency,
                           round(spend / conversions, 2) if conversions else "-"])
    write("Meta_Ads_Weekly.csv", ["Week starting", "Campaign", "Ad name", "Spend ($)", "Impressions",
                                  "Clicks", "Trials", "Frequency", "CPA ($)"], weekly)

    write("Change_Log.csv", ["Date", "Change", "Platform", "Campaign", "Owner", "Negatives"], [
        ["2026-08-28", "Paused UK NonBrand", "google", "Search_NonBrand_UK", "Sample Owner", ""],
        ["2026-09-01", "Added 42 NonBrand negatives", "google", "Search_NonBrand_US", "Sample Owner",
         "; ".join(NEGATIVES)],
        [CHANGE_DAY.isoformat(), "Broadened interest stack", "meta", "Cold_Interest", "Sample Owner", ""],
    ])


if __name__ == "__main__":
    main()
