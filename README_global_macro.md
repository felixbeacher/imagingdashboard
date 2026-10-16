# Global Economy & Risk tab

The new global-macro.html page moves economic growth and consumer inflation out of the AI page. It includes the corrected five-component risk chart, a concise interpretation, three imaging implications, an accessible data table, sources, and a link to the supplied full report. Navigation is updated across Home, AI, CT, MRI, PET and X-ray.

## Build and serve

Run `python3 ai_update_data.py` to refresh AI and economic data and write both pages. The AI updater now preserves the leaner source in ai.template.html. Edit that template for subsequent AI layout changes. Edit global-macro.template.html for the new page.

Run `python3 ai_update_data.py --serve` to serve the site locally. The new routes are /global-macro.html and /api/macroeconomics. Static builds with --build also produce the new page and its risk assets beside the AI output. The active .github/workflows/weekly.yml refreshes AI and Glob Econ, publishes the macro page and risk assets, and preserves the other modality pages without invoking their unfinished updaters.

## Risk data

The supplied SVG used six components through December 2025, while the report and CSV used five through September 2026. risk.svg has been regenerated from the supplied risk-data.csv: 81 months, five equal-weight components, latest 78.717949, peak March 2022. The original external risk-tracker folder is untouched. The companion report is copied with broken links to unsupplied assets removed and its chart description corrected.

The chart is a historical snapshot, not a live risk feed. Economic refreshes do not advance the risk cutoff. The original calibration dataset and source manifest were not supplied; the published percentile scores were retained, not independently recalculated. CSV arithmetic, chronology and chart fingerprint are validated.

To replace the risk snapshot, supply updated scored CSV data, then regenerate the SVG with `python3 build_risk_chart.py` (matplotlib required only for chart regeneration). Update any period-specific explanatory text if extending the history. Routine site builds use only the Python standard library.

## Validation

Eleven macro regression tests: `python3 -m unittest test_macro_dashboard.py`. Browser checks confirmed populated macro figures, region switching, a fixed global risk chart, and correct AI metric-card alignment. A live build refreshed AI and IMF sources on 11 October 2026.

The invalid placeholder dashboard_data.json was removed. The updater uses automatic public sources when this optional file is absent.

## Glob Econ refinement

The navigation label is now Glob Econ. The new page is headed Global Economic Background and loads risk.svg. The AI regional introduction is now Summary: Global Market for Imaging AI in the global view and changes with the selected region. Economic projection and country-coverage detail is expandable to keep the new page concise. Existing dated observations were retained; this presentation update does not claim a new source refresh.

## Valuation and financing integration — 16 October 2026

Glob Econ now connects its historical risk chart and IMF outlook to financing, healthcare cost pressure and a qualitative valuation guide. The FTSE reference file supplied fixed series and a simulated refresh, so its figures and bubble scores were not imported. The new guide corrects scope and interpretation issues and links to primary reference sources. A clearly labelled, user-input purchasing-power calculator uses (1 + nominal growth) / (1 + inflation) - 1.

The macro builder accepts an optional financing callback. The AI updater supplies US EFFR and US medical-care CPI collection, preserving observation periods, source links and failure states. These US benchmarks do not change with regional economic selection. Routine weekly builds and the local macro API use the same implementation. No extra library is required.

Validation: 32 Python tests, an offline CLI publication check, a live macro build, desktop/mobile browser checks, region switching and calculator valid/empty-input checks.
