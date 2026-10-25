# Intel Feed backend

`Intel Feed Refresh` runs daily at 07:35 UTC and can be run manually in GitHub Actions. It collects RSS reports, classifies relevant imaging headlines, removes likely duplicates, and creates at most four new briefings per calendar day (UTC). The newest 80 briefings remain on the site; a 90-day seen-story list reduces re-ingestion. Keyword selection is selective and is not a comprehensive news review.

## Free default

No AI API calls are made by default. Automated headline digests include the publisher's headline, an attribution, a source link, general category-specific “What this means for you” guidance and “What to watch”. They do not pretend to summarise the complete source article. Missing dates, future dates, non-HTTPS URLs and unrelated reports are skipped. Source failures preserve the previous feed. No user uploads or private information are sent to third parties.

## Optional Gemini source briefings

To enable original AI prose, first confirm in Google AI Studio that the key's project uses an eligible **unpaid/free tier**, with billing disabled. A key's billing tier cannot be verified by this code. Flags and request limits are not a monetary spending cap if the project is changed to paid billing.

The workflow reads these GitHub repository settings:

- Secret `GEMINI_API_KEY`: an existing key can be reused; never put it in source files or the browser.
- Variable `INTEL_ENABLE_AI=true`: explicit opt-in to API calls.
- Variable `INTEL_FREE_TIER_CONFIRMED=true`: owner confirmation that the project is unpaid.
- Optional variable `INTEL_GEMINI_MODEL`: default `gemini-3.8-flash`; choose a model available on your free tier.

Both flags default to false even if the existing dashboard already has a key. No paid search grounding, upgrade or alternate provider is configured. A key alone does not activate writing. The collector makes at most one request for each new eligible story, stops further AI calls after the first error in a run, and never retries an API call. It requires at least 80 words of feed description; sparse feed items become headline digests instead. A free-tier quota error, invalid draft or missing key also produces a headline digest.

AI drafts use only the supplied feed title and excerpt, not the full linked article. Draft validation checks format, length, numerical tokens and an exact supporting source passage. These checks do **not** independently establish factual accuracy or clinical benefit; labels distinguish synthesis from verified reporting. Feed content is treated as untrusted data and rendered as escaped text.

## Publication

The collector archives `intel-articles.json` and the rendered HTML on `main`. A successful `Intel Feed Refresh` workflow triggers `Weekly Dashboard Update` through `workflow_run`, rebuilding and deploying the complete site from `main`. The collection workflow uses the same concurrency group as deployment to avoid racing updates. It does not replace the other dashboard pages. The `[skip ci]` archive commit avoids redundant push builds; the workflow completion event handles publication.

## Local checks

```bash
python -m unittest test_intel_backend -v
python intel_collect.py --limit 4
python intel_build.py
```

`--offline` skips all collection. The renderer is repeatable and has no network dependencies. Review `backend` in `intel-articles.json` for attempt date, source availability and drafting results; exception messages are not logged because they can contain request credentials.
