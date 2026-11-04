# Audit report

## Tracking reconciliation

Status: **OK** (tolerance 15%)

| utm_source | Platform | PostHog | Drift | Status |
|---|---|---|---|---|
| facebook | 656 | 623 | 5.3% | OK |
| google | 668 | 634 | 5.4% | OK |

## Meta

### Campaigns

| Object | Verdict | Spend | Conversions | CPA | Flags | Evidence |
|---|---|---|---|---|---|---|
| Cold_Broad | **SCALE_CANDIDATE** | $101,300 | 450 | $225 | - | $101,300 spend, 450 conversions, $225 CPA over 92 days |
| Cold_Interest | **CUT_CANDIDATE** | $46,045 | 124 | $371 | LOW_CTR | $46,045 spend, 124 conversions, $371 CPA over 92 days |
| Retargeting_30d | **SCALE_CANDIDATE** | $15,655 | 82 | $191 | - | $15,655 spend, 82 conversions, $191 CPA over 92 days |

### Ads

| Object | Verdict | Spend | Conversions | CPA | Flags | Evidence |
|---|---|---|---|---|---|---|
| Carousel_Old | **FATIGUE** | $10,800 | 26 | $415 | LOW_CTR, FATIGUE | $415 CPA lifetime, freq 1.6->3.1, weekly CPA $450->$600 |
| Static_BenefitStack_A | **KEEP** | $15,000 | 59 | $254 | - | $15,000 spend, 59 conversions, $254 CPA over 42 days |
| UGC_Founder_v2 | **RESHOOT_ANGLE** | $21,000 | 107 | $196 | FATIGUE | $196 CPA lifetime, freq 1.4->3.85, weekly CPA $233->$292 |
| Video_Hook_Test3 | **CUT** | $1,500 | 0 | n/a | - | $1,500 spend, 0 conversions in 21 days |

## Google

### Campaigns

| Object | Verdict | Spend | Conversions | CPA | Flags | Evidence |
|---|---|---|---|---|---|---|
| PMax_US | **KEEP** | $30,390 | 110 | $276 | - | $30,390 spend, 110 conversions, $276 CPA over 92 days |
| Search_Brand_US | **SCALE_CANDIDATE** | $23,944 | 217 | $110 | - | $23,944 spend, 217 conversions, $110 CPA over 92 days |
| Search_NonBrand_UK | **CUT** | $15,335 | 0 | n/a | - | $15,335 spend, 0 conversions in 27 days |
| Search_NonBrand_US | **KEEP** | $92,091 | 341 | $270 | - | $92,091 spend, 341 conversions, $270 CPA over 92 days |

## Monthly slices

| Platform | Month | Spend | Impressions | Clicks | Conversions |
|---|---|---|---|---|---|
| meta | 2026-08 | $55,605 | 2,502,201 | 44,454 | 233 |
| meta | 2026-09 | $52,678 | 2,370,480 | 40,732 | 212 |
| meta | 2026-10 | $54,717 | 2,462,223 | 41,033 | 211 |
| google | 2026-08 | $65,286 | 2,937,799 | 114,771 | 227 |
| google | 2026-09 | $47,321 | 2,129,408 | 90,434 | 216 |
| google | 2026-10 | $49,153 | 2,211,829 | 93,938 | 225 |

## Change impact (7 days after vs 7 days before)

- **CAUSED_BY_CHANGE**: Cold_Interest conversions moved -42% after "Broadened interest stack" (2026-09-15)
- **CAUSED_BY_CHANGE**: Cold_Interest CTR moved -30% after "Broadened interest stack" (2026-09-15)
- **CAUSED_BY_CHANGE**: Cold_Interest CPA moved +59% after "Broadened interest stack" (2026-09-15)

## Verdict JSON

```json
{
  "verdicts": [
    {
      "object": "Cold_Broad",
      "level": "campaign",
      "platform": "meta",
      "verdict": "SCALE_CANDIDATE",
      "evidence": "$101,300 spend, 450 conversions, $225 CPA over 92 days",
      "spend": 101300.0,
      "conversions": 450.0,
      "cpa": 225.11,
      "days": 92,
      "ctr": 0.019,
      "flags": [],
      "current_monthly": 33032.61
    },
    {
      "object": "Cold_Interest",
      "level": "campaign",
      "platform": "meta",
      "verdict": "CUT_CANDIDATE",
      "evidence": "$46,045 spend, 124 conversions, $371 CPA over 92 days",
      "spend": 46045.48,
      "conversions": 124.0,
      "cpa": 371.33,
      "days": 92,
      "ctr": 0.011,
      "flags": [
        "LOW_CTR"
      ],
      "current_monthly": 15014.83
    },
    {
      "object": "Retargeting_30d",
      "level": "campaign",
      "platform": "meta",
      "verdict": "SCALE_CANDIDATE",
      "evidence": "$15,655 spend, 82 conversions, $191 CPA over 92 days",
      "spend": 15655.46,
      "conversions": 82.0,
      "cpa": 190.92,
      "days": 92,
      "ctr": 0.0239,
      "flags": [],
      "current_monthly": 5105.04
    },
    {
      "object": "Carousel_Old",
      "level": "ad",
      "platform": "meta",
      "verdict": "FATIGUE",
      "evidence": "$415 CPA lifetime, freq 1.6->3.1, weekly CPA $450->$600",
      "spend": 10800.0,
      "conversions": 26.0,
      "cpa": 415.38,
      "days": 42,
      "ctr": 0.012,
      "flags": [
        "LOW_CTR",
        "FATIGUE"
      ],
      "campaign": "Cold_Interest"
    },
    {
      "object": "Static_BenefitStack_A",
      "level": "ad",
      "platform": "meta",
      "verdict": "KEEP",
      "evidence": "$15,000 spend, 59 conversions, $254 CPA over 42 days",
      "spend": 15000.0,
      "conversions": 59.0,
      "cpa": 254.24,
      "days": 42,
      "ctr": 0.018,
      "flags": [],
      "campaign": "Cold_Broad"
    },
    {
      "object": "UGC_Founder_v2",
      "level": "ad",
      "platform": "meta",
      "verdict": "RESHOOT_ANGLE",
      "evidence": "$196 CPA lifetime, freq 1.4->3.85, weekly CPA $233->$292",
      "spend": 21000.0,
      "conversions": 107.0,
      "cpa": 196.26,
      "days": 42,
      "ctr": 0.021,
      "flags": [
        "FATIGUE"
      ],
      "campaign": "Cold_Broad"
    },
    {
      "object": "Video_Hook_Test3",
      "level": "ad",
      "platform": "meta",
      "verdict": "CUT",
      "evidence": "$1,500 spend, 0 conversions in 21 days",
      "spend": 1500.0,
      "conversions": 0.0,
      "cpa": null,
      "days": 21,
      "ctr": 0.016,
      "flags": [],
      "campaign": "Cold_Interest"
    },
    {
      "object": "PMax_US",
      "level": "campaign",
      "platform": "google",
      "verdict": "KEEP",
      "evidence": "$30,390 spend, 110 conversions, $276 CPA over 92 days",
      "spend": 30389.99,
      "conversions": 110.0,
      "cpa": 276.27,
      "days": 92,
      "ctr": 0.012,
      "flags": [],
      "current_monthly": 9909.78
    },
    {
      "object": "Search_Brand_US",
      "level": "campaign",
      "platform": "google",
      "verdict": "SCALE_CANDIDATE",
      "evidence": "$23,944 spend, 217 conversions, $110 CPA over 92 days",
      "spend": 23943.63,
      "conversions": 217.0,
      "cpa": 110.34,
      "days": 92,
      "ctr": 0.11,
      "flags": [],
      "current_monthly": 7807.71
    },
    {
      "object": "Search_NonBrand_UK",
      "level": "campaign",
      "platform": "google",
      "verdict": "CUT",
      "evidence": "$15,335 spend, 0 conversions in 27 days",
      "spend": 15335.07,
      "conversions": 0.0,
      "cpa": null,
      "days": 27,
      "ctr": 0.028,
      "flags": [],
      "current_monthly": 17038.97
    },
    {
      "object": "Search_NonBrand_US",
      "level": "campaign",
      "platform": "google",
      "verdict": "KEEP",
      "evidence": "$92,091 spend, 341 conversions, $270 CPA over 92 days",
      "spend": 92090.92,
      "conversions": 341.0,
      "cpa": 270.06,
      "days": 92,
      "ctr": 0.035,
      "flags": [],
      "current_monthly": 30029.65
    }
  ],
  "tracking": {
    "status": "OK",
    "by_source": {
      "facebook": {
        "platform": 656.0,
        "posthog": 623.0,
        "drift": 0.053,
        "status": "OK"
      },
      "google": {
        "platform": 668.0,
        "posthog": 634.0,
        "drift": 0.0536,
        "status": "OK"
      }
    }
  },
  "change_impacts": [
    {
      "flag": "CAUSED_BY_CHANGE",
      "change": "Broadened interest stack",
      "date": "2026-09-15",
      "object": "Cold_Interest",
      "metric": "conversions",
      "before": 12.0,
      "after": 7.0,
      "shift": -0.417
    },
    {
      "flag": "CAUSED_BY_CHANGE",
      "change": "Broadened interest stack",
      "date": "2026-09-15",
      "object": "Cold_Interest",
      "metric": "CTR",
      "before": 0.013,
      "after": 0.0091,
      "shift": -0.3
    },
    {
      "flag": "CAUSED_BY_CHANGE",
      "change": "Broadened interest stack",
      "date": "2026-09-15",
      "object": "Cold_Interest",
      "metric": "CPA",
      "before": 308.1333,
      "after": 490.88,
      "shift": 0.593
    }
  ],
  "new_negatives": []
}
```
