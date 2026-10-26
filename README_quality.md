# Dashboard data and browser quality checks

The public dashboard is a scheduled static publication. Collection dates are not observation dates.

## OECD coverage and status

- Fetch total-provider and hospital-only equipment data. Select one provider definition for each country, modality and indicator; never splice those provider histories together.
- Retain OECD observation flags from all four status columns. In particular, E means a source estimate, B a break and D a definition difference. An unflagged value is not proof of perfect comparability.
- Keep national coverage notes alongside the chosen provider code. The OECD 2025 diagnostic-technologies comparison is the reference; it does not establish identical definitions in every historical year.
- A country can have total-provider CT data and hospital-only MRI data. Individual chart scopes and source-value tables take precedence over a shared country label.

## Conservative review rules

Values above these deliberately broad engineering thresholds are **flagged and retained**, not replaced or treated as zero:

| Unit | CT | MRI | PET |
|---|---:|---:|---:|
| Scanners per million inhabitants | 500 | 300 | 100 |
| Examinations per 1,000 inhabitants per year | 3,000 | 2,000 | 500 |

These are not recommended scanner densities, clinical limits or statistical outlier estimates. Consecutive-year changes above 50% are flagged when the absolute change also exceeds 5 scanners/million or 10 examinations/1,000. Missing years and zero denominators are not used to calculate those changes.

Recent flags B/U/V/F or a recent scale/change warning withhold modelled extensions; reported readings remain visible. Historical lines stop at B. Definition breaks also prevent automated utilisation comparisons across the affected interval. Source estimates remain labelled as estimates.

## Risk snapshot

The build verifies monthly continuity, finite/ranged scores, component sums and averages, monotonic raw-to-percentile ordering and the CSV/SVG fingerprint. These checks passed for the supplied snapshot. The original 312-month calibration histories are absent; calibration remains explicitly unverified. A current revised public download would not, by itself, reproduce the original data vintage.

## Public payload packaging

The build validates the canonical AI dataset before `public_build.py` removes that build-only JSON from the public HTML. `ai-data`, charts, source dates, fallback tables and browser runtime remain identical. The canonical dataset remains in the source snapshot for build validation.

## Browser regression checks

The publication workflow runs `scripts/browser_qa.cjs` with development-only, version-pinned Playwright and axe-core. No testing libraries ship with the dashboard. The runner already has Chromium-compatible system libraries, so only the pinned browser binary is downloaded; no full OS dependency upgrade is run. It checks 14 pages at 375, 768 and 1440 pixel viewports, expandable content, WCAG A/AA rules, JavaScript errors, duplicate IDs, navigation clipping and region filters. Additional scenarios cover CDN failure, zero/null values, invalid calculator inputs and a throttled mobile smoke test (150 ms latency, 200 KiB/s download and 4× CPU slowdown). Screenshots and a JSON report are retained as the `dashboard-browser-qa` Actions artifact.

Automated accessibility tests do not certify usability with every screen reader or real device, and local test-server timings are not real-world mobile network performance measurements.
