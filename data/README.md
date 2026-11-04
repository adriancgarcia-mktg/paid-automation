# Sample data

Every CSV here is **synthetic**, written by `scripts/make_sample_data.py`. None of it comes from a real ad account. Replace these files with your own exports before relying on any verdict.

Expected columns:

| File | Columns |
|---|---|
| `Meta_Daily.csv` | Date, Campaign, Spend ($), Impressions, Clicks, Trials |
| `Meta_Ads_Weekly.csv` | Week starting, Campaign, Ad name, Spend ($), Impressions, Clicks, Trials, Frequency, CPA ($) |
| `Google_Daily.csv` | Date, Campaign, Spend ($), Impressions, Clicks, Conversions |
| `Trials_PostHog.csv` | Date, utm_source, Trials |
| `Change_Log.csv` | Date, Change, Platform, Campaign, Owner, Negatives (semicolon-separated) |
| `Search_Terms.csv` (optional) | Search term, Campaign, Spend ($), Conversions |

Keep real exports out of any repo that isn't private.
