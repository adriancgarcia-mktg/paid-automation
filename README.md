# Paid Account Automation Playbook

**Audit → Plan → Build → QA: turns a performance plan into ready-to-launch campaigns**

**Purpose:** This is a self-contained automation spec. An LLM (or engineer) can drop this into a repo and run it end to end. It takes raw platform exports in, produces an audit, compiles a campaign plan, generates bulk-upload files for Meta and Google, and enforces a QA gate before anything goes live.

**Guardrails baked in (non-negotiable):**

- Every generated campaign, ad set, and ad launches PAUSED. Activation is a separate human-approved step.
- Budget math must reconcile to the monthly cap before files are written. If it doesn't, the build aborts.
- CPA targets are enforced as cost caps / tCPA values in the generated files, not left to defaults.
- No campaign is created that isn't in the approved plan. The plan is the single source of truth.

## Quick start

The repo ships with synthetic sample data, so this runs as is. Everything in `data/`, and so everything in `output/`, is illustrative.

```bash
pip install -r requirements.txt
```

```bash
python3 scripts/01_audit.py && python3 scripts/03_build_meta.py && python3 scripts/04_build_google.py && python3 scripts/05_qa.py
```

```bash
python3 -m unittest discover -s tests
```

To compile a new draft plan from audit verdicts, run `python3 scripts/02_compile_plan.py`. It writes to `output/plan.yaml` for review.

## Before using this on a real account

These are known gaps. None has been tested against a live platform.

1. **The CSV layouts probably won't import as they stand.** The column specs below stack several header rows in one file. To my knowledge, Ads Manager and Google Ads Editor both expect a single flat header row, so expect to add a flattening step or use the API route. Try a small test import first.
2. **Meta API calls are only tested against a mock.** `03_build_meta.py --push` has never reached Meta. Check `META_API_VERSION` (the spec's `v21.0` may be retired) and video creatives, which may also need a thumbnail.
3. **The bulk sheet can't carry the exclusion audience.** Its specified columns have no field for it, so only API payloads include it. If you upload the sheet, set the exclusion by hand.
4. **Meta budget level needs a decision.** The sheet fills both campaign and ad set budgets as specified, but Meta generally uses one or the other. The API payloads use ad set budgets.
5. **Replace all placeholders.** `config/plan.yaml` contains sample brand terms, URLs, copy and asset IDs, and QA does not detect placeholder text.

## Changes from the original spec

| Spec | This repo | Why |
|---|---|---|
| `daily_budget_cents` of 1667000 / 166700 / 333300 | 166667 / 16667 / 33333 | The originals are 10x too high: 1667000 cents is $16,670/day, not $1,667 |
| Google `monthly_budget: 55000` | `50000` | $65K + $55K + $5K reserve is $125K against a $120K cap, so the spec's own check aborts. Google's campaigns sum to $50K |
| Daily budgets rounded ($1,667, $266) | Exact monthly / 30 | Rounded values sum about $10 off, failing the $1 QA check |
| Compiler outputs `config/plan.yaml` (layout also shows `output/plan.yaml`) | Draft goes to `output/plan.yaml`; a person promotes it | Stops a compile overwriting the approved plan |
| `04_build_google.csv` | `04_build_google.py` | Typo |
| `TRIAL_START` | Kept in plan and sheet; sent as `START_TRIAL` in API calls | `START_TRIAL` is Meta's API enum |
| Fatigue: prose says rising week over week, sample code says CPA doubled | Prose: frequency above 2.0 and latest weekly CPA above the prior week | The spec says the rules are the contract, not the code |
| `RESHOOT_ANGLE` has no trigger rule | Fatigued ad not otherwise over target → `RESHOOT_ANGLE`; over target → `FATIGUE` | Inferred from the spec's example |
| "Metric dropped" has no threshold | 20% move, 7 days after vs 7 days before | Adjustable as `CHANGE_SHIFT` in `01_audit.py`. This shows timing, not proven cause |
| PMax has no bidding in the schema | `TARGET_CPA` at $280 | Guardrail: no default bidding |
| Search-terms analysis has no input among the 5 exports | Optional `data/Search_Terms.csv` | Zero-conversion terms with $100+ spend are flagged. Threshold is adjustable |
| 40-negative list source unspecified | `Negatives` column in `Change_Log.csv` | The build aborts below 40 |
| No PMax negative-list field in the columns | `Account negative list` row in the ad group section | Avoids adding columns |

**Additions:**

- `plan_status` in the plan, because builders refuse anything not `APPROVED`
- `replaces` on ads, which links a replacement to the ad it replaces
- `tcpa_deferred_until`, which documents NonBrand's exception to the tCPA rule
- `landing_url` and ad copy fields
- A 10th QA check that generated campaigns exactly match the plan
- `output/qa_status.json`, so `--push` refuses unless QA passed on that exact plan and those payloads

## Repo layout

```
paid-automation/
├── config/
│   ├── plan.yaml              # The approved campaign plan (source of truth)
│   ├── envelope.yaml          # Human-approved budget envelope for Phase 2
│   └── overrides.yaml         # Written reasons for keeping CUT_CANDIDATEs
├── data/                      # Synthetic samples: replace with real exports
│   ├── Meta_Daily.csv
│   ├── Meta_Ads_Weekly.csv
│   ├── Google_Daily.csv
│   ├── Trials_PostHog.csv
│   └── Change_Log.csv
├── scripts/
│   ├── common.py              # Shared paths, reconciliation and parsing
│   ├── make_sample_data.py    # Regenerates the synthetic data
│   ├── 01_audit.py            # Phase 1: audit engine
│   ├── 02_compile_plan.py     # Phase 2: audit verdicts → draft plan
│   ├── 03_build_meta.py       # Phase 3a: Meta bulk sheet + API payloads
│   ├── 04_build_google.py     # Phase 3b: Google Ads Editor CSV
│   └── 05_qa.py               # Phase 4: QA gate
├── tests/test_pipeline.py     # Breaks each guardrail and checks it holds
├── output/
│   ├── audit_report.md
│   ├── plan.yaml              # Draft from Phase 2
│   ├── meta_bulk_upload.csv
│   ├── meta_api_payloads.json
│   ├── pending_creatives.csv
│   ├── google_ads_editor.csv
│   ├── qa_report.md
│   └── qa_status.json
└── README.md
```

---

## Phase 1: Audit engine (`01_audit.py`)

**Input:** the 5 raw exports in `data/`.
**Output:** `output/audit_report.md` with verdicts per campaign and per ad.

The script does five things, in order:

1. **Aggregate** spend, impressions, clicks, and conversions by campaign, by ad, and by month (Aug / Sep / Oct slices).
2. **Reconcile** platform-reported conversions against PostHog trial signups by `utm_source`. If platform totals drift more than 15% from PostHog, flag `TRACKING_RISK` in the report and halt the build phase until resolved.
3. **Score** every campaign and ad against the funnel's normal ranges:
   - CPA vs target ($250–280): over target by >10% = `CUT_CANDIDATE`, within 10% = `KEEP`, under target = `SCALE_CANDIDATE`
   - CTR: below 1.5% on Meta = creative/hook problem flag
   - Frequency: above 2.0 with rising CPA week over week = `FATIGUE` flag
   - Zero conversions after 2+ weeks and $1K+ spend = `CUT` (no debate)
4. **Detect change-impact pairs:** cross-reference `Change_Log` dates against metric shifts in the 7 days after each change. A metric that dropped right after one change gets flagged `CAUSED_BY_CHANGE` with the change name attached.
5. **Emit verdicts** as structured JSON embedded at the bottom of the audit report:

```json
{
  "verdicts": [
    {"object": "Search_NonBrand_UK", "level": "campaign", "platform": "google",
     "verdict": "CUT", "evidence": "$15,090 spend, 0 conversions in 27 days"},
    {"object": "UGC_Founder_v2", "level": "ad", "platform": "meta",
     "verdict": "RESHOOT_ANGLE", "evidence": "$200 CPA lifetime, paused at freq 3.85"}
  ]
}
```

**Thresholds:** `TARGET_CPA = 265` (midpoint of the 250–280 band), `TARGET_TOLERANCE = 0.10`, `ZERO_CONV_MIN_SPEND = 1000`, `ZERO_CONV_MIN_DAYS = 14`, `FATIGUE_FREQ = 2.0`. See `scripts/01_audit.py` for the implementation.

**Audit report format (what the human reads):** one section per platform. For each object: verdict, the three numbers that decided it (spend, conversions, CPA), and the one-line evidence. Ends with the JSON verdict block that Phase 2 consumes.

---

## Phase 2: Plan compiler (`02_compile_plan.py`)

**Input:** audit report verdict JSON + a human-approved budget envelope.
**Output:** draft plan at `output/plan.yaml`, promoted by a person to `config/plan.yaml`.

| Audit verdict | Plan action |
|---|---|
| `CUT` | Object excluded from plan; its budget returns to the envelope |
| `CUT_CANDIDATE` | Excluded unless the plan author overrides with a written reason |
| `KEEP` | Carried forward at current or reduced budget |
| `SCALE_CANDIDATE` | Carried forward with budget increase, capped at +30% |
| `RESHOOT_ANGLE` | New ad created in plan with same angle, fresh creative flag |
| `FATIGUE` | Ad excluded; replacement ad required in plan before build passes QA |

The plan is then hand-edited by a human (or the LLM proposes edits for approval) before Phase 3 runs. The compiler never invents budgets; it only allocates the envelope the operator gives it. Spare dollars stay in `unallocated_monthly`, and the plan won't reconcile until a person allocates them.

**Plan schema:** see [`config/plan.yaml`](config/plan.yaml) for the full working example.

**Budget reconciliation** runs before any file is written and aborts if the platform and reserve totals miss the cap by more than $1, or if a platform's campaign budgets don't add up to its stated total. See `reconcile()` in `scripts/common.py`.

---

## Phase 3: Build generators

### 3a. Meta (`03_build_meta.py`)

Two output modes, both generated from `config/plan.yaml`:

**Mode 1: bulk sheet CSV** (for manual upload via Ads Manager import):

```
Campaign Name,Campaign Status,Campaign Objective,Campaign Daily Budget,Campaign Bid Strategy,Campaign Cost Cap
Cold_Consolidated,PAUSED,OUTCOME_SALES,1666.67,COST_CAP,280.00
Ad Set Name,Ad Set Status,Ad Set Daily Budget,Optimization Goal,Custom Event Type,Ad Set Name
Cold_Consolidated - Main,PAUSED,1666.67,OFFSITE_CONVERSIONS,TRIAL_START,Cold_Consolidated - Main
Ad Name,Ad Status,Format,Link URL,Primary Text,Headline,CTA
...
```

**Mode 2: API payloads** (for direct Marketing API calls). Every run writes `output/meta_api_payloads.json`. To send them after QA passes, set the environment variables and run:

```bash
python3 scripts/03_build_meta.py --push
```

Required variables: `META_ACCESS_TOKEN`, `META_AD_ACCOUNT`, `META_PIXEL_ID`, `META_PAGE_ID`, `META_EXCLUSION_AUDIENCE_ID`. Optional: `META_API_VERSION`.

**Rules the generator enforces:**

- One ad per ad set in the `Creative_Testing` campaign, with a 3-second video-viewer exclusion audience applied between ad sets.
- Cost cap is written as the CPA target in the account's smallest currency unit ($280 → 28000 cents).
- Ads are created only when `creative_status == READY` and an `asset_id` exists. Anything else goes to `pending_creatives.csv`, never into the API call.
- Every create call uses `status: PAUSED`. There is no code path that sets ACTIVE.

### 3b. Google (`04_build_google.py`)

Generates a Google Ads Editor import CSV with these columns:

```
Campaign,Daily Budget,Bid Strategy,Target CPA,Campaign Status,Networks,Location,Language
Search_Brand_US,266.67,Target CPA,200.00,Paused,Search; Search partners,United States,English
Ad group,Ad group type,Max CPC,Ad group status,Keywords,Keyword match type,Negatives
Brand_Core,Standard,,Paused,[brand term 1]; [brand term 2],Exact,
Ad type,Ad name,Headline 1,Headline 2,Headline 3,Description 1,Description 2,Final URL,Path 1,Path 2
...
```

**Rules the generator enforces:**

- PMax campaign gets a brand-terms negative list attached at the account level before its asset groups are written.
- `Search_NonBrand_US` carries the 40-negative list from the `Change_Log` plus any new negatives flagged in the audit's search-terms analysis.
- UK campaign is simply absent from the output. Nothing is generated for cut objects.
- Bidding: `MAXIMIZE_CONVERSIONS` for NonBrand until 30 conversions/month sustained, then tCPA 280 on the next build. The flip is a plan edit, not an automatic API change: the script reports eligibility, and `--apply-flip` makes the edit. That rewrite drops comments from `plan.yaml`.

---

## Phase 4: QA gate (`05_qa.py`)

Runs after files are generated, before anything is uploaded. Produces `output/qa_report.md`. **Build fails closed: any FAIL blocks upload.**

**Automated checks:**

1. Budget sum across all generated campaigns plus the reserve equals the monthly cap within $1.
2. Every campaign/ad set/ad in generated files has status PAUSED.
3. Every cost cap / tCPA value is within the $250–280 band (or the documented Brand exception at $200).
4. No object from a `CUT` verdict appears in any generated file.
5. Every `RESHOOT_ANGLE` ad has a corresponding new ad in the plan (replacement exists before the old one's budget is reallocated). The same applies to `FATIGUE`.
6. `Creative_Testing` campaign has exactly one ad per ad set and the exclusion audience is present.
7. PMax has brand negatives attached.
8. PostHog reconciliation passed in Phase 1 (no open `TRACKING_RISK` flag).
9. UTM parameters on every generated ad's final URL match the plan's naming convention (`utm_source=facebook|google`, `utm_campaign={campaign_name}`, `utm_content={ad_name}`) so PostHog attribution stays clean.
10. Generated campaigns exactly match the approved plan.

**Human QA checklist (the operator runs this after upload, before activation):**

- [ ] Open each new campaign in the platform UI and confirm: status PAUSED, budget matches plan, bid strategy and cap match plan.
- [ ] Confirm tracking: pixel/dataset fires trial-start on a test signup; Google conversion action fires on a test conversion; PostHog receives the event with correct `utm_source`.
- [ ] Confirm no legacy campaign is still spending that was marked CUT (pause confirmed in UI, not just absent from the new upload).
- [ ] Confirm retargeting audience windows and exclusions match plan (cold excludes all warm audiences).
- [ ] Confirm `pending_creatives.csv` items have owners and due dates assigned.
- [ ] Screenshot each campaign's settings page into `output/qa_screenshots/` for the change record.
- [ ] Log every change made in the account's `Change_Log` with date and owner, same format as the existing tab.

**Only after every box above is checked:** activate campaigns in this order: ads first, then ad sets, then campaigns, one platform at a time, and re-read each object's status as ACTIVE before moving to the next.

**Post-launch monitoring hook (day 3 and day 14):**

- **Day 3:** re-run `01_audit.py` on fresh exports. Any new campaign with 0 conversions and normal CTR is left alone (learning period). Any campaign spending 50%+ below its daily budget gets a cost-cap raise review, in steps, not a jump.
- **Day 14:** full audit re-run. `SCALE_CANDIDATE` objects get +10–30% budget. Any object that failed its kill condition (PMax probation) is paused via the same plan → build → QA pipeline, never by hand in the UI.

---

## How another LLM should use this file

1. Read `config/plan.yaml` (or generate it from Phase 2 rules given an audit report and a budget envelope).
2. Run or reimplement the Phase 1 audit against whatever export format exists; the verdict rules and thresholds above are the contract, not the code.
3. Generate the Phase 3 output files exactly per the column specs. Do not add fields not specified here.
4. Run the Phase 4 automated checks. Report PASS/FAIL per check. Do not skip the human checklist or mark it done on the operator's behalf.
5. Never output an ACTIVE status anywhere in generated files. Activation happens in the platform UI by a human, in the order specified, after the checklist.
