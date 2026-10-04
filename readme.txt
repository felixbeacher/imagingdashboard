Medical Imaging Dashboard — integrated file set

Unzip the package into one folder, preserving the images subfolder.
Use these deployment filenames exactly:
  index.html
  1_ai.html
  1_update_data_ai.py
  styles.css
  images/earth-hero.png

Requires Python 3.10+. Start from this folder:
  python3 1_update_data_ai.py --port 8080
Open http://127.0.0.1:8080/ for the landing page.
The AI page is http://127.0.0.1:8080/1_ai.html.
For a cloud server behind a reverse proxy, add --host 0.0.0.0.

Opening the HTML files directly provides a design preview. Run the Python server
for source retrieval and injected dashboard observations. The landing page uses
styles.css; the AI page retains its self-contained CSS with the matching palette.

Corrected integration issues:
- Both pages now link to the same numbered dashboard filenames.
- The root route opens the landing page rather than the AI page.
- The server serves the landing stylesheet and globe PNG with correct MIME types.
- Earlier unnumbered modality URLs remain supported as aliases.
- The landing page is the latest approved globe design, replacing the older
  image-free index file in the supplied set.
- The updater still uses exactly one DASHBOARD_DATA_PLACEHOLDER in the AI page;
  the design scaffold and blank-graph fallback remain intact.

Other modality pages were not included. Add 2_ct.html, 3_mri.html, 4_pet.html
and 5_xray.html beside these files when available. The server can also serve
ct.html, mri.html, pet.html and xray.html as legacy filename fallbacks.

Optional curated observations:
Copy dashboard_data.example.json to dashboard_data.json and enter sourced
observations. Then run:
  python3 1_update_data_ai.py --data dashboard_data.json
The template contains no invented numerical data. FDA-listed radiology AI
entries and relevant RSS headlines are fetched automatically; other indicators
remain unavailable until evidence-backed inputs are supplied. A complete data
contract is documented in the earlier AI dashboard readme.txt.

Checks passed: 13 Python tests plus running-server integration checks for Home,
AI, the stylesheet, binary image delivery, API data, URL aliases and restricted
file access. No full browser visual verification was possible in this session.
