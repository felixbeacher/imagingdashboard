# Automatic dashboard data collection — 4 October 2026

## Install

Replace these files in the **repository root**, using these exact filenames:

- `1_update_data_ai.py`
- `modality_dashboard.py`
- `2_update_data_ct.py`
- `3_update_data_mri.py`
- `4_update_data_pet.py`
- `5_update_data_xray.py`

Keep the existing HTML templates, landing page, stylesheet and image assets.
The existing `weekly.yml` already runs these scripts correctly. It does not need changing for these additions. Commit the files, then run **Actions → Weekly Dashboard Update → Run workflow**. The existing push trigger may also start a run automatically.

The actual collection changes are in the AI updater and shared engine. The four wrappers have updated usage instructions; their execution behaviour is unchanged.

## What now fills automatically

| Indicator | Dashboards / views | Source and interpretation |
|---|---|---|
| Active registered studies (research proxy) | All five dashboards, all six views | ClinicalTrials.gov active interventional registrations matching a disclosed intervention-text search. This measures registered research activity, including planned research, not completed prospective evidence or clinical efficacy. |
| Country median reported scanner density | CT, MRI and PET, all six views | WHO DEVICES09 / DEVICES08 / DEVICES10. Unweighted median of each reporting country's latest published equipment density. Historical availability data, not a pooled regional or current operational installed base. |
| US overnight financing rate proxy | All five dashboards: Global and North America only | New York Fed effective federal funds rate. US interbank rate, not a global/G7 rate or vendor borrowing cost. |
| US medical-care CPI proxy | All five dashboards: Global and North America only | BLS CUUR0000SAM: medical-care CPI-U, not seasonally adjusted. YoY = (latest month / same month last year − 1) × 100. US-only; no cross-country aggregation. Consumer prices are not hospital input costs. |
| FDA benchmarks and headlines | Existing shared sections | Existing FDA and RSS collectors remain enabled. A blocked individual RSS feed can still produce a warning while other feeds work. |

No new package dependencies or API keys are required. All scripts still use the Python standard library.

## Coverage and limits

- A regional selector does not make a sample representative of the whole region. Regional WHO and registry results use the explicit samples below; every populated card names its actual source geography and period.
- **North America:** United States and Canada.
- **Europe:** United Kingdom, Germany, France, Italy, Spain, Netherlands, Sweden, Poland and Switzerland.
- **Asia-Pacific:** China, Japan, India, South Korea, Australia, New Zealand, Singapore, Taiwan and Thailand.
- **Middle East sample:** Israel, Saudi Arabia, United Arab Emirates, Iran, Turkey and Egypt. This is the dashboard's editorial country grouping.
- **LATAM:** Brazil, Mexico, Argentina, Chile, Colombia and Peru.
- WHO medians use only countries in the relevant sample with usable observations. The global WHO median includes all usable reporting countries, including countries outside the regional samples. Country values and reporting periods are embedded in `data_collection.automatic_sources`.
- WHO data can be several years old: the live source checked for this update contained observations up to 2021. Fetching them today does not make them current. The cards disclose the actual observation-period range.
- Registry regional counts include registrations with a site in at least one selected country. A multinational registration may appear in multiple regional views. The global total is queried directly, never calculated by adding regional counts.
- Intervention-text matching can include use of imaging within a wider clinical study; it is not a validated census of imaging technology trials. The exact query is provided in each card's methodology/source link.
- US financing and CPI benchmarks appear only in Global and North America. Other regions are not populated with a US number masquerading as local data.
- These additions do **not** connect every indicator. With successful sources and no curated data, expect **1 of 12 core cards** populated in each AI and X-ray view, **2 of 12** in each CT/MRI/PET view, plus the two US context cards in Global/North America and the existing FDA/news sections.

## What still needs sourced inputs

AI production sites, scan usage, renewal rates, reporting/waiting times, workforce shortfall, paid AI claims, measured time savings, procurement times, contract awards, funding, vendor revenues and inference costs are not populated by these collectors.

For the modality dashboards, examination volumes/growth, waiting/reporting times, vacancies, procurement times/awards, replacement-age shares, advanced-system shares, dose/protocol performance, tracer disruptions, digital/reject rates, equipment mixes, expenditure and vendor revenues still need a suitable source or curated input. Equity benchmark returns also remain unconnected.

The unchanged JSON input contracts still work: `dashboard_data.json`, `ct_data.json`, `mri_data.json`, `pet_data.json`, `xray_data.json`. Keep source name/URL, geography, period, as-of date and methodology with every observation. A data file is optional for the automatic sources.

Supplied non-null observations take priority; invalid supplied values are withheld rather than silently replaced. Empty/null example placeholders permit automatic filling. Set `"automatic": false` on a null observation to explicitly withhold that automatic indicator. Set top-level `"auto_sources": false` to disable the new collectors while leaving existing FDA/news collection enabled.

## Failure handling and checks

- A missing/blocked/invalid source produces a missing observation with an explanatory reason. It never becomes a made-up zero.
- A genuine zero from a valid registry response is retained as zero.
- BLS missing index values are skipped. A YoY calculation requires the matching prior-year month; another period is never substituted.
- The local `.dashboard_cache` shares responses for one hour across the five builds to reduce API requests, especially BLS requests. An expired response is not silently served after a failed fetch. The cache is not part of the published website and need not be committed.
- `--offline` disables external collection and keeps the existing blank design/data behaviour. Do not use it for the live GitHub build.
- Build into a separate output file: `python 1_update_data_ai.py --build _site/1_ai.html`. The source template must retain its data placeholder for future builds.


## Verification completed

All five live dashboard builds succeeded with no observation-validation errors. FDA and headline collection also returned data for all five in this check; individual feed warnings may remain. The HTML JavaScript was exercised with the new embedded payloads through all six region views and did not fall back to design preview.

The existing 21 backend checks and 8 new source-collection tests passed. The included focused tests can be run with `python test_public_sources.py` from the repository root. They check failure isolation, valid zero counts, exact-month CPI calculations, country medians, source conflicts, curated precedence and offline behaviour.
