# QA report

Automated gate: **PASS**

| # | Check | Result | Detail |
|---|---|---|---|
| 1 | Budget sum equals the monthly cap within $1 | PASS | Meta $65,000.10 + Google $50,000.10 + reserve $5,000 = $120,000.20 vs $120,000 cap |
| 2 | Every generated object is PAUSED | PASS | All generated objects are paused |
| 3 | Cost caps and tCPAs are in band or the Brand exception | PASS | All caps are within $250-$280 or the Brand $200 exception |
| 4 | No CUT object appears in any generated file | PASS | None of 2 CUT objects appear |
| 5 | RESHOOT_ANGLE and FATIGUE ads have replacements in the plan | PASS | All 2 have replacements |
| 6 | Creative_Testing has one ad per ad set and its exclusion | PASS | 3 ad sets with one ad each; exclusion audience present |
| 7 | PMax has brand negatives attached | PASS | PMax_US has 2 brand negatives attached first |
| 8 | PostHog reconciliation passed (no open TRACKING_RISK) | PASS | Phase 1 tracking status: OK |
| 9 | UTMs match the naming convention | PASS | 7 ad URLs match the naming convention |
| 10 | Generated campaigns exactly match the approved plan | PASS | Generated campaigns match the 6 in the plan |

## Human checklist (operator, after upload and before activation)

- [ ] Open each new campaign in the platform UI and confirm: status PAUSED, budget matches plan, bid strategy and cap match plan.
- [ ] Confirm tracking: pixel/dataset fires trial-start on a test signup; Google conversion action fires on a test conversion; PostHog receives the event with correct utm_source.
- [ ] Confirm no legacy campaign is still spending that was marked CUT (pause confirmed in UI, not just absent from the new upload).
- [ ] Confirm retargeting audience windows and exclusions match plan (cold excludes all warm audiences).
- [ ] Confirm pending_creatives.csv items have owners and due dates assigned.
- [ ] Screenshot each campaign's settings page into output/qa_screenshots/ for the change record.
- [ ] Log every change made in the account's Change_Log with date and owner, same format as the existing tab.

Only after every box is checked: activate ads first, then ad sets, then campaigns, one platform at a time, re-reading each object's status as ACTIVE before moving on.
