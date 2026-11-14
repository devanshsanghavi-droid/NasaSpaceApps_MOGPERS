# Build rules for every concept branch

1. **Work only on your concept's branch.** Never push to `main` or to another concept's branch. Put all code under `apps/<concept>/` so the branches can merge cleanly later.
2. **Use real data only.** If a source cannot be reached, record it in `apps/<concept>/BLOCKERS.md` with the error and what would unblock it, such as an Earthdata login or an API key. Use the best real alternative available. Never fabricate numbers. Mock data is allowed only for UI development; it must sit in `web/mock/` and the app must show a visible "MOCK DATA" banner whenever it uses it.
3. **Never commit credentials.** If a source needs a login or key, write the code path behind an environment variable or `~/.netrc` and document it.
4. **Keep the repo small.** Commit code, small processed outputs (JSON/parquet up to a few MB) and docs. Do not commit raw downloads (`data/raw/` is gitignored).
5. **Make the web app static,** using `apps/<concept>/web/index.html` with no build step. CDN libraries must use pinned versions (for example MapLibre GL, Chart.js). It must run from `python -m http.server` and be deployable to GitHub Pages. It must work at phone width and have no console errors.
6. **The farmer view must meet the challenge.** Compare at least 3 strategies including the current one. Each strategy shows why it is suggested, evidence, benefits, information gaps and risks needing local review. Use plain language and state uncertainty clearly. Include a "decision support, not a replacement for your agronomist" note.
7. **Show impact numbers with ranges and sources.** Keep a claims register at `apps/<concept>/CLAIMS.md` covering every number shown in the UI or pitch: value, source URL, and whether it is verified.
8. **Deliver these files:**
   - `apps/<concept>/README.md`: what it is, how to run it, data sources, method, validation results, limitations.
   - `apps/<concept>/PITCH.md`: a 7-slide deck outline (title + intro + 5) and a 30-second video script. Lead with the impact.
   - `apps/<concept>/VALIDATION.md`: out-of-time or held-out test results against baselines.
9. **Commit and push often,** at least after each working milestone, so progress is visible and safe. Use clear commit messages ending with the attribution line your environment specifies.
10. **Deadline:** Sunday, Nov 15, 2026, 11:59 pm. Deliver a working first iteration first, then improve it.
