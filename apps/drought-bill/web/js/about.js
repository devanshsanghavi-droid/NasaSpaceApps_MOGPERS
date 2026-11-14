// About / method panel: data sources (NASA flagged), method in plain words, caveats, links to validation and claims.
import { esc } from './util.js';

const REPO = 'https://github.com/devanshsanghavi-droid/NasaSpaceApps_MOGPERS/blob/drought-bill/apps/drought-bill';

export function renderAbout(D, mockFiles) {
  const src = D.meta?.data_sources || [];
  const cav = D.meta?.caveats || [];
  const nasaN = src.filter((s) => s.nasa).length;
  document.getElementById('about-body').innerHTML = `
    <div class="about-grid">
      <div>
        <h3>How the bill is built</h3>
        <ol class="method">
          <li><b>Drought hazard from NASA.</b> Summer rainfall deficits, extreme heat and root-zone soil moisture for every county since 1981 (NASA POWER), plus vegetation stress from MODIS.</li>
          <li><b>Losses from USDA.</b> Crop-insurance drought payouts per insured acre by county and year (USDA RMA Cause of Loss and Summary of Business).</li>
          <li><b>Rotation diversity from space.</b> Crop sequences since 2008 from the USDA Cropland Data Layer give each county a rotation diversity score and its continuous-corn share.</li>
          <li><b>Model.</b> How payouts scale with drought, and how diversity changes that, controlling for soils and irrigation. Trained on years through 2020, tested on 2021–2024.</li>
          <li><b>Expected bill.</b> The loss model run over every summer's weather since 1981; the 2045 bill shifts that weather with NASA NEX-GDDP-CMIP6 climate projections.</li>
        </ol>
        <p><a href="${REPO}/VALIDATION.md" target="_blank" rel="noopener">Validation results (VALIDATION.md)</a> · <a href="${REPO}/CLAIMS.md" target="_blank" rel="noopener">Claims register with sources (CLAIMS.md)</a> · <a href="${REPO}/README.md" target="_blank" rel="noopener">README</a></p>
      </div>
      <div>
        <h3>Data sources <span class="muted small">${nasaN} of ${src.length} from NASA</span></h3>
        ${src.length ? `<ul class="sources">${src.map((s) => `
          <li>${s.nasa ? '<span class="nasa-badge">NASA</span>' : '<span class="src-badge">partner</span>'}
            <div><b>${s.url ? `<a href="${esc(s.url)}" target="_blank" rel="noopener">${esc(s.name)}</a>` : esc(s.name)}</b><br><span class="muted small">${esc(s.role || '')}</span></div></li>`).join('')}</ul>`
        : '<p class="empty">meta.json not available.</p>'}
      </div>
      <div>
        <h3>Caveats</h3>
        <ul class="caveats">
          ${cav.map((c) => `<li>${esc(c)}</li>`).join('')}
          <li>The bill counts insured losses paid by crop insurance, not every dollar a drought costs a farm.</li>
          <li>The taxpayer share is estimated as the county's premium-subsidy share of the bill.</li>
          <li>Diversity effects are estimated from what similar counties experienced, not from controlled trials on your farm.</li>
        </ul>
        <p class="small muted">${D.meta?.generated_at ? `Data generated ${esc(D.meta.generated_at)}.` : ''} ${mockFiles.length ? `<b class="red">Mock files in use: ${mockFiles.map(esc).join(', ')}.</b>` : ''}</p>
      </div>
    </div>`;
}
