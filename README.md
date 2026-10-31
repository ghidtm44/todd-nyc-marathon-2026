# Todd’s 2026 NYC Marathon spectator guide

A static, mobile-friendly page for friends and family: the official 2026 NYRR course map annotated with Todd’s estimated mile times, a complete arrival table, and sourced spectator suggestions.

## Timing

- Sunday, November 1, 2026, planned start **10:55 a.m. America/New_York (EST, UTC−05:00)**.
- Pink, Wave 4, Corral E.
- First mile **9:22** (within Todd’s stated 9:15–9:30 range); remaining miles **8:50/mile**.
- Use the full **42.195 km** marathon distance for the finish: **2:47:08 p.m. EST**, elapsed **3:52:08**. Visible map labels round to the nearest minute.
- All projections assume the planned start is Todd’s actual start-line crossing. Any start delay shifts every estimate; actual pace, stops, and conditions can change arrivals.

The precomputed values are in `source/estimates.json`. The website has no JavaScript, API calls, live tracking, controls, or backend. All map assets are served locally.

## Map and sources

The map is the official [2026 NYRR course PDF](https://cms.prod.nyrr.org/api/document-files/file/TCSNYCM26_Map_Course_090226_RD3.pdf), linked from [NYRR’s course page](https://prod.nyrr.org/tcsnycmarathon/the-course). Original map copyright remains with NYRR. Time annotations are personal projections, not NYRR timing predictions. Pink-specific early markers are used; the 2026 Bronx course is retained.

The original PDF and NYRR-linked Google My Maps KML are preserved under `source/`. `scripts/build_maps.py` creates the annotated map panels after explicitly reviewing the marker positions in the published PDF. Labels refer to the map’s marked positions, not newly surveyed coordinates.

Viewing advice is based on qualitative past runner and spectator experience, not measured crowd statistics or guaranteed quiet. Direct sources and current NYRR access restrictions are linked on the page.

## Develop and verify

Serve this directory with `python3 -m http.server 8000`. No build or package installation is required for hosting. To regenerate map assets, install Python PyMuPDF and Pillow, then run `python3 scripts/build_maps.py`.

`python3 scripts/verify_static.py` verifies the clock times and local assets. The verification workflow also checks mobile and desktop layout with Playwright. It uses dependencies only for tests; the published site remains plain HTML, CSS, and image assets.

## Publishing

GitHub Pages should publish the repository’s `gh-pages` branch from `/` (root). The original mounted Halloween project is unrelated and was not modified.
