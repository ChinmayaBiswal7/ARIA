// ══════════════════════════════════════════════════
//  ARIA COMMAND CENTER — ENGINE v2 (D3 Real Map)
// ══════════════════════════════════════════════════

// ─── CLOCK ───
function updateClock() {
  const n = new Date();
  const tbClock = document.getElementById('tb-clock');
  if (tbClock) {
    tbClock.textContent =
      `${String(n.getHours()).padStart(2,'0')}:${String(n.getMinutes()).padStart(2,'0')}:${String(n.getSeconds()).padStart(2,'0')}`;
  }
}
setInterval(updateClock, 1000); updateClock();

// ─── STATUS ───
function setStatus(s) {
  const dot = document.getElementById('status-dot');
  const lbl = document.getElementById('status-label');
  if (dot && lbl) {
    dot.className = 'status-dot';
    if (s === 'offline')  { dot.classList.add('offline');  lbl.textContent = 'OFFLINE'; }
    else if (s === 'thinking') { dot.classList.add('thinking'); lbl.textContent = 'PROCESSING'; }
    else                        { lbl.textContent = 'ONLINE'; }
  }
}

// ─── DIAGNOSTICS STREAM ───
let diagCount = 0;
const diagFeed = document.getElementById('diag-feed');
const BOOT_MSGS = [
  ['ok',   'Sensory buffer initialised'],
  ['ok',   'Memory vector store: LOADED'],
  ['info', 'Wake-word sentinel: ACTIVE'],
  ['ok',   'Voice pipeline: ONLINE'],
  ['info', 'Chroma knowledge base: READY'],
  ['ok',   'Intent classifier: WARM'],
  ['info', 'NLP semantic router: INDEXED'],
  ['ok',   'Dashboard socket: CONNECTED'],
  ['info', 'D3 world map: RENDERING'],
  ['ok',   'Live stream feeds: CONNECTED'],
  ['ok',   'Geo-intelligence: ONLINE'],
];
const TICK_MSGS = [
  ['info', 'Memory consolidation cycle: OK'],
  ['ok',   'Context engine latency: 38ms'],
  ['info', 'Semantic index refresh: OK'],
  ['ok',   'Voice SNR baseline calibrated'],
  ['info', 'Vision frame captured (1280×720)'],
  ['ok',   'Agent orchestrator heartbeat: OK'],
  ['info', 'Knowledge graph pruning: 0 orphans'],
  ['ok',   'Long-term memory: 1,247 vectors'],
  ['info', 'Viewport active state: CHECKED'],
  ['warn', 'Attention buffer 72% capacity'],
  ['ok',   'Buffer normalised, latency OK'],
];
function pushDiag(msg, cls) {
  diagCount++;
  const countEl = document.getElementById('diag-count');
  if (countEl) countEl.textContent = `${diagCount} events`;
  
  const n = new Date();
  const ts = `${String(n.getHours()).padStart(2,'0')}:${String(n.getMinutes()).padStart(2,'0')}:${String(n.getSeconds()).padStart(2,'0')}`;
  
  console.log(`[Diag] [${cls}] ${ts} - ${msg}`);
  
  if (diagFeed) {
    const el = document.createElement('div');
    el.className = 'diag-entry';
    el.innerHTML = `<span class="diag-time">${ts}</span><span class="diag-msg ${cls}">${msg}</span>`;
    diagFeed.appendChild(el);
    while (diagFeed.children.length > 80) diagFeed.removeChild(diagFeed.firstChild);
    diagFeed.scrollTop = diagFeed.scrollHeight;
  }
}
let bi = 0;
(function boot() { if (bi < BOOT_MSGS.length) { pushDiag(BOOT_MSGS[bi][1], BOOT_MSGS[bi][0]); bi++; setTimeout(boot, 150 + Math.random()*200); } })();
let ti = 0;
setInterval(() => { const m = TICK_MSGS[ti++ % TICK_MSGS.length]; pushDiag(m[1], m[0]); }, 5000);

// ═══════════════════════════════════════════════════
//  D3 REAL WORLD MAP
// ═══════════════════════════════════════════════════

let d3Projection = null;
let mapSvg = null;
let mapNodes = [];   // { lat, lon, headline, born, phase }
let mapNodeGroup = null;
const tooltip = document.getElementById('map-tooltip');
let selectedMapRegion = null;

const MAJOR_COUNTRIES = {
  'India': 'India',
  'United States of America': 'United States',
  'United States': 'United States',
  'China': 'China',
  'Russia': 'Russia',
  'Australia': 'Australia',
  'United Kingdom': 'United Kingdom',
  'Brazil': 'Brazil',
  'Germany': 'Germany',
  'Japan': 'Japan',
  'South Africa': 'South Africa'
};

const COUNTRY_TO_CONTINENT = {
  // Asia
  'India': 'Asia', 'China': 'Asia', 'Japan': 'Asia', 'Indonesia': 'Asia', 'Pakistan': 'Asia', 'Bangladesh': 'Asia',
  'Turkey': 'MENA', 'South Korea': 'Asia', 'North Korea': 'Asia', 'Vietnam': 'Asia', 'Thailand': 'Asia',
  'Myanmar': 'Asia', 'Philippines': 'Asia', 'Iran': 'MENA', 'Iraq': 'MENA', 'Saudi Arabia': 'MENA',
  'Afghanistan': 'Asia', 'Nepal': 'Asia', 'Yemen': 'MENA', 'Syria': 'MENA', 'Israel': 'MENA', 'Jordan': 'MENA',
  'Lebanon': 'MENA', 'Palestine': 'MENA', 'Gaza': 'MENA', 'Taiwan': 'Asia', 'Sri Lanka': 'Asia', 'Kazakhstan': 'Asia',
  'United Arab Emirates': 'MENA', 'Qatar': 'MENA', 'Kuwait': 'MENA', 'Oman': 'MENA', 'Bahrain': 'MENA',
  // Europe
  'Russia': 'Europe', 'Germany': 'Europe', 'United Kingdom': 'Europe', 'France': 'Europe', 'Italy': 'Europe',
  'Spain': 'Europe', 'Ukraine': 'Europe', 'Poland': 'Europe', 'Romania': 'Europe', 'Netherlands': 'Europe',
  'Belgium': 'Europe', 'Greece': 'Europe', 'Sweden': 'Europe', 'Norway': 'Europe', 'Denmark': 'Europe',
  'Finland': 'Europe', 'Austria': 'Europe', 'Switzerland': 'Europe', 'Portugal': 'Europe', 'Ireland': 'Europe',
  // North America
  'United States of America': 'North America', 'Canada': 'North America', 'Mexico': 'North America',
  'Cuba': 'North America', 'Guatemala': 'North America', 'Honduras': 'North America', 'Nicaragua': 'North America',
  // South America
  'Brazil': 'South America', 'Argentina': 'South America', 'Colombia': 'South America', 'Peru': 'South America',
  'Venezuela': 'South America', 'Chile': 'South America', 'Ecuador': 'South America', 'Bolivia': 'South America',
  // Africa
  'South Africa': 'Africa', 'Nigeria': 'Africa', 'Egypt': 'MENA', 'Ethiopia': 'Africa', 'Kenya': 'Africa',
  'Algeria': 'MENA', 'Morocco': 'MENA', 'Tunisia': 'MENA', 'Libya': 'MENA', 'Ghana': 'Africa', 'Sudan': 'Africa', 'Uganda': 'Africa',
  // Oceania
  'Australia': 'Oceania', 'New Zealand': 'Oceania', 'Papua New Guinea': 'Oceania'
};

function getRegionFromCountry(countryName) {
  if (MAJOR_COUNTRIES[countryName]) return MAJOR_COUNTRIES[countryName];
  if (COUNTRY_TO_CONTINENT[countryName]) return COUNTRY_TO_CONTINENT[countryName];
  const c = countryName.toLowerCase();
  if (c.includes('libya') || c.includes('algeria') || c.includes('morocco') || c.includes('tunisia') || c.includes('egypt') || c.includes('syria') || c.includes('yemen') || c.includes('palestine') || c.includes('emirates') || c.includes('saudi') || c.includes('qatar') || c.includes('kuwait') || c.includes('lebanon') || c.includes('jordan') || c.includes('iraq') || c.includes('iran') || c.includes('israel') || c.includes('turkey')) return 'MENA';
  if (c.includes('guinea') || c.includes('congo') || c.includes('sudan') || c.includes('angola') || c.includes('madagascar') || c.includes('somalia') || c.includes('mali')) return 'Africa';
  if (c.includes('poland') || c.includes('croatia') || c.includes('ireland') || c.includes('czech') || c.includes('austria') || c.includes('belgium')) return 'Europe';
  if (c.includes('mexico') || c.includes('panama') || c.includes('costa') || c.includes('cuba') || c.includes('honduras')) return 'North America';
  if (c.includes('chile') || c.includes('peru') || c.includes('colombia') || c.includes('venezuela') || c.includes('argentina')) return 'South America';
  return 'Asia';
}

function isCountryInRegion(countryName, regionName) {
  if (countryName === regionName) return true;
  if (MAJOR_COUNTRIES[countryName] === regionName) return true;
  const cont = COUNTRY_TO_CONTINENT[countryName];
  return cont === regionName;
}

function handleCountryClick(countryName) {
  const region = getRegionFromCountry(countryName);
  selectedMapRegion = region;
  
  pushDiag(`Map Focus: ${countryName} (${region})`, 'active');
  showToast(`Focusing: ${region}`);
  
  // 1. Highlight clicked region paths
  mapSvg.selectAll('path.land')
    .transition().duration(250)
    .attr('fill', function(d) {
      const isSel = isCountryInRegion(d.properties.name, region);
      return isSel ? '#ff6c00' : '#0a1a24';
    });
    
  // 2. Update streams instantly
  updateAllStreams(region);
  
  // 3. Trigger backend search API for text headlines
  const headlinesTag = document.getElementById('headlines-tag');
  if (headlinesTag) headlinesTag.textContent = `${region.toUpperCase()} NEWS`;
  const headlinesList = document.getElementById('headlines-list');
  if (headlinesList) {
    headlinesList.innerHTML = `<div style="font-family:var(--mono);font-size:.56rem;color:var(--accent);text-align:center;padding:20px;">
      <span class="live-badge" style="background:#ff6c00;box-shadow:0 0 5px #ff6c00;animation:sdot 1.2s infinite;"></span> FETCHING LIVE GEO-NEWS FOR ${region.toUpperCase()}...
    </div>`;
  }
  
  fetch('/api/v1/dashboard/trigger-news', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ region: region })
  }).then(r => r.json())
    .then(res => {
      pushDiag(`Geo-news fetch requested for ${region}`, 'ok');
    }).catch(err => {
      pushDiag(`Geo-news fetch request failed: ${err}`, 'err');
    });
}

const REGIONAL_STREAMS = {
  'India': [
    { label: 'India Today Live', ch: 'UCYPvAwZP8pZhSMW8qs7cVCw', genre: 'Live Headlines Feed' },
    { label: 'WION Live News', ch: 'UCkMV0o3fTtDZ2G2tFb8IXYA', genre: 'International Focus' },
    { label: 'NDTV Live India', ch: 'UCYSfYVdrOZvh5iPadUPTAg3', genre: 'Markets & Business' },
    { label: 'CNA Asian News', ch: 'UC83jt4dlz1Gjl58fzQrrKZg', genre: 'Regional / Economics' }
  ],
  'United States': [
    { label: 'CNA Asian News', ch: 'UC83jt4dlz1Gjl58fzQrrKZg', genre: 'Global / Asia Focus' },
    { label: 'WION Live News', ch: 'UCkMV0o3fTtDZ2G2tFb8IXYA', genre: 'International Focus' },
    { label: 'TRT World', ch: 'UC7fWeaHjqD4P-hZ5420SIA', genre: 'Middle East & Global' },
    { label: 'Al Jazeera Live', ch: 'UCNye-wNBqNL5ZzHSJj3l8Bg', genre: 'Global Headlines' }
  ],
  'China': [
    { label: 'CGTN Live News', ch: 'UCgrNz-aDmcr2uuto8_DL2jg', genre: 'Global Headlines' },
    { label: 'CNA Asian News', ch: 'UC83jt4dlz1Gjl58fzQrrKZg', genre: 'Regional / Economics' },
    { label: 'DW News Global', ch: 'UCknLrEdhRCp1aegoMqRaCZg', genre: 'International Focus' },
    { label: 'NHK World Live', ch: 'UCSPEjw8F2nQDtmUKPFNF7_A', genre: 'East Asia Focus' }
  ],
  'Russia': [
    { label: 'France 24 English', ch: 'UCQfwfsi5VrQ8yKZ-UWmAEFg', genre: 'European Focus' },
    { label: 'DW News Global', ch: 'UCknLrEdhRCp1aegoMqRaCZg', genre: 'European Focus' },
    { label: 'Al Jazeera Live', ch: 'UCNye-wNBqNL5ZzHSJj3l8Bg', genre: 'International News' },
    { label: 'TRT World', ch: 'UC7fWeaHjqD4P-hZ5420SIA', genre: 'Global Headlines' }
  ],
  'Australia': [
    { label: 'CNA Asian News', ch: 'UC83jt4dlz1Gjl58fzQrrKZg', genre: 'Regional Live' },
    { label: 'France 24 English', ch: 'UCQfwfsi5VrQ8yKZ-UWmAEFg', genre: 'European & Global' },
    { label: 'WION Live News', ch: 'UCkMV0o3fTtDZ2G2tFb8IXYA', genre: 'International Focus' },
    { label: 'DW News Global', ch: 'UCknLrEdhRCp1aegoMqRaCZg', genre: 'Tech & Innovation' }
  ],
  'United Kingdom': [
    { label: 'France 24 English', ch: 'UCQfwfsi5VrQ8yKZ-UWmAEFg', genre: 'European Focus' },
    { label: 'Al Jazeera Live', ch: 'UCNye-wNBqNL5ZzHSJj3l8Bg', genre: 'International Focus' },
    { label: 'TRT World', ch: 'UC7fWeaHjqD4P-hZ5420SIA', genre: 'Global Headlines' },
    { label: 'DW News Global', ch: 'UCknLrEdhRCp1aegoMqRaCZg', genre: 'Technology Focus' }
  ],
  'Brazil': [
    { label: 'France 24 English', ch: 'UCQfwfsi5VrQ8yKZ-UWmAEFg', genre: 'Global Broadcast' },
    { label: 'Al Jazeera Live', ch: 'UCNye-wNBqNL5ZzHSJj3l8Bg', genre: 'International Focus' },
    { label: 'TRT World', ch: 'UC7fWeaHjqD4P-hZ5420SIA', genre: 'Global Headlines' },
    { label: 'WION Live News', ch: 'UCkMV0o3fTtDZ2G2tFb8IXYA', genre: 'Finance / Markets' }
  ],
  'Germany': [
    { label: 'DW News Global', ch: 'UCknLrEdhRCp1aegoMqRaCZg', genre: 'European Broadcast' },
    { label: 'France 24 English', ch: 'UCQfwfsi5VrQ8yKZ-UWmAEFg', genre: 'Regional Headlines' },
    { label: 'TRT World', ch: 'UC7fWeaHjqD4P-hZ5420SIA', genre: 'Global Headlines' },
    { label: 'Al Jazeera Live', ch: 'UCNye-wNBqNL5ZzHSJj3l8Bg', genre: 'International Focus' }
  ],
  'Japan': [
    { label: 'NHK World Live', ch: 'UCSPEjw8F2nQDtmUKPFNF7_A', genre: 'National Broadcast' },
    { label: 'CNA Asian News', ch: 'UC83jt4dlz1Gjl58fzQrrKZg', genre: 'Regional Live' },
    { label: 'France 24 English', ch: 'UCQfwfsi5VrQ8yKZ-UWmAEFg', genre: 'European Focus' },
    { label: 'DW News Global', ch: 'UCknLrEdhRCp1aegoMqRaCZg', genre: 'Global Focus' }
  ],
  'South Africa': [
    { label: 'France 24 English', ch: 'UCQfwfsi5VrQ8yKZ-UWmAEFg', genre: 'Global Headlines' },
    { label: 'TRT World', ch: 'UC7fWeaHjqD4P-hZ5420SIA', genre: 'Global Live Feed' },
    { label: 'Al Jazeera Live', ch: 'UCNye-wNBqNL5ZzHSJj3l8Bg', genre: 'International Focus' },
    { label: 'DW News Global', ch: 'UCknLrEdhRCp1aegoMqRaCZg', genre: 'European Focus' }
  ],
  'Asia': [
    { label: 'CNA Asian News', ch: 'UC83jt4dlz1Gjl58fzQrrKZg', genre: 'Regional Headlines' },
    { label: 'CGTN Live Asia', ch: 'UCgrNz-aDmcr2uuto8_DL2jg', genre: 'Global Focus' },
    { label: 'NDTV Live India', ch: 'UCYSfYVdrOZvh5iPadUPTAg3', genre: 'South Asia Focus' },
    { label: 'WION Live News', ch: 'UCkMV0o3fTtDZ2G2tFb8IXYA', genre: 'Finance & Technology' }
  ],
  'Europe': [
    { label: 'DW News Live', ch: 'UCknLrEdhRCp1aegoMqRaCZg', genre: 'European News' },
    { label: 'France 24 English', ch: 'UCQfwfsi5VrQ8yKZ-UWmAEFg', genre: 'Regional Broadcast' },
    { label: 'TRT World', ch: 'UC7fWeaHjqD4P-hZ5420SIA', genre: 'International Focus' },
    { label: 'Al Jazeera Live', ch: 'UCNye-wNBqNL5ZzHSJj3l8Bg', genre: 'Finance & Technology' }
  ],
  'North America': [
    { label: 'CNA Asian News', ch: 'UC83jt4dlz1Gjl58fzQrrKZg', genre: 'Global Headlines' },
    { label: 'France 24 English', ch: 'UCQfwfsi5VrQ8yKZ-UWmAEFg', genre: 'Regional Broadcast' },
    { label: 'TRT World', ch: 'UC7fWeaHjqD4P-hZ5420SIA', genre: 'Global Live Feed' },
    { label: 'WION Live News', ch: 'UCkMV0o3fTtDZ2G2tFb8IXYA', genre: 'Markets & Technology' }
  ],
  'South America': [
    { label: 'France 24 English', ch: 'UCQfwfsi5VrQ8yKZ-UWmAEFg', genre: 'Regional Live' },
    { label: 'Al Jazeera Live', ch: 'UCNye-wNBqNL5ZzHSJj3l8Bg', genre: 'National Headlines' },
    { label: 'TRT World', ch: 'UC7fWeaHjqD4P-hZ5420SIA', genre: 'International Focus' },
    { label: 'WION Live News', ch: 'UCkMV0o3fTtDZ2G2tFb8IXYA', genre: 'Finance & Markets' }
  ],
  'Africa': [
    { label: 'France 24 English', ch: 'UCQfwfsi5VrQ8yKZ-UWmAEFg', genre: 'Continental Broadcast' },
    { label: 'TRT World', ch: 'UC7fWeaHjqD4P-hZ5420SIA', genre: 'Regional Broadcast' },
    { label: 'Al Jazeera Live', ch: 'UCNye-wNBqNL5ZzHSJj3l8Bg', genre: 'International Focus' },
    { label: 'DW News Global', ch: 'UCknLrEdhRCp1aegoMqRaCZg', genre: 'Finance & Technology' }
  ],
  'Oceania': [
    { label: 'CNA Asian News', ch: 'UC83jt4dlz1Gjl58fzQrrKZg', genre: 'Regional Live' },
    { label: 'France 24 English', ch: 'UCQfwfsi5VrQ8yKZ-UWmAEFg', genre: 'National Broadcast' },
    { label: 'TRT World', ch: 'UC7fWeaHjqD4P-hZ5420SIA', genre: 'Markets & Finance' },
    { label: 'DW News Global', ch: 'UCknLrEdhRCp1aegoMqRaCZg', genre: 'Technology Focus' }
  ],
  'Global': [
    { label: 'Al Jazeera Live', ch: 'UCNye-wNBqNL5ZzHSJj3l8Bg', genre: 'Global Headlines' },
    { label: 'DW News Live', ch: 'UCknLrEdhRCp1aegoMqRaCZg', genre: 'European Headlines' },
    { label: 'CNA Asian News', ch: 'UC83jt4dlz1Gjl58fzQrrKZg', genre: 'Business & Tech' },
    { label: 'WION Live News', ch: 'UCkMV0o3fTtDZ2G2tFb8IXYA', genre: 'Economics & Markets' }
  ],
  'MENA': [
    { label: 'Al Jazeera Arabic', ch: 'UC12_JjLd0uY8_D1G2Nn1-3g', genre: 'Arabic News' },
    { label: 'Al Arabiya Arabic', ch: 'UCahpxixMCwoANAftn6IxkTg', genre: 'Arabic Broadcast' },
    { label: 'Sky News Arabia', ch: 'UCIJXOvggjKtCagMfxvcCzAA', genre: 'Arabic Regional' },
    { label: 'Al Jazeera Live', ch: 'UCNye-wNBqNL5ZzHSJj3l8Bg', genre: 'English Global' }
  ]
};

function renderRightSidebarHeadlines(articles) {
  const headlinesList = document.getElementById('headlines-list');
  if (!headlinesList) return;
  const arts = articles || [];
  if (arts.length === 0) {
    headlinesList.innerHTML = `<div style="font-family:var(--mono);font-size:.56rem;color:var(--muted);text-align:center;padding:20px;">No headlines available for this region.</div>`;
  } else {
    headlinesList.innerHTML = arts.map((art) => {
      const sent = (art.sentiment || 'neutral').toLowerCase();
      return `
        <div class="headline-item" onclick="${art.url ? `window.open('${art.url}','_blank')` : ''}">
          <div class="headline-row">
            <span class="headline-sentiment-dot ${sent}" title="Sentiment: ${sent}"></span>
            <span class="headline-text">${art.headline || 'No Headline'}</span>
          </div>
          <div class="headline-meta">
            <span>${art.source || 'Web Search'}</span>
            <span style="color:var(--accent);">${art.category || 'Global'}</span>
          </div>
        </div>
      `;
    }).join('');
  }
}

function updateAllStreams(region) {
  const regionStreams = REGIONAL_STREAMS[region] || REGIONAL_STREAMS['Global'];
  const globalStreams = REGIONAL_STREAMS['Global'];
  
  const streams = [...regionStreams];
  for (let s of globalStreams) {
    if (streams.length >= 5) break;
    if (!streams.some(x => x.ch === s.ch)) {
      streams.push(s);
    }
  }
  while (streams.length < 5) {
    streams.push(globalStreams[0]);
  }

  const BASE = 'https://www.youtube.com/embed/live_stream?autoplay=1&mute=1&controls=1&rel=0&modestbranding=1&channel=';
  
  for (let i = 0; i < 2; i++) {
    const stream = streams[i];
    const iframe = document.getElementById(`stream-${i+1}`);
    const label = document.getElementById(`stream-${i+1}-label`);
    if (iframe && stream) {
      const newSrc = BASE + stream.ch;
      if (!iframe.src.includes(stream.ch)) iframe.src = newSrc;
      if (label) label.innerHTML = `<span class="live-badge" style="background:#ff6c00;box-shadow:0 0 5px #ff6c00;display:inline-block;width:5px;height:5px;border-radius:50%;margin-right:4px;"></span>${stream.label}`;
    }
  }

  for (let i = 2; i < 5; i++) {
    const stream = streams[i];
    const iframe = document.getElementById(`stream-${i+1}`);
    const label = document.getElementById(`stream-${i+1}-label`);
    if (iframe && stream) {
      const newSrc = BASE + stream.ch;
      if (!iframe.src.includes(stream.ch)) iframe.src = newSrc;
      if (label) label.innerHTML = `<span class="live-badge" style="background:#ff6c00;box-shadow:0 0 5px #ff6c00;display:inline-block;width:5px;height:5px;border-radius:50%;margin-right:4px;"></span>${stream.label}`;
    }
  }
  
  const bottomStreamsTag = document.getElementById('bottom-streams-tag');
  if (bottomStreamsTag) {
    bottomStreamsTag.textContent = `${region.toUpperCase()} FOCUS`;
  }
  pushDiag(`Streams updated for region: ${region}`, 'info');
}

function initMap(world) {
  const wrap = document.getElementById('map-wrap');
  if (!wrap) return;
  const W = wrap.clientWidth;
  const H = wrap.clientHeight;

  const countries = topojson.feature(world, world.objects.countries);

  d3Projection = d3.geoNaturalEarth1()
    .fitSize([W, H], countries)
    .translate([W/2, H/2]);

  const path = d3.geoPath(d3Projection);

  mapSvg = d3.select('#worldmap')
    .attr('width', W)
    .attr('height', H)
    .attr('viewBox', `0 0 ${W} ${H}`);

  // Ocean background
  mapSvg.append('rect')
    .attr('width', W).attr('height', H)
    .attr('fill', '#030508');

  // Graticule (grid lines)
  const graticule = d3.geoGraticule()();
  mapSvg.append('path')
    .datum(graticule)
    .attr('class','graticule')
    .attr('d', path);

  // Countries
  mapSvg.selectAll('path.land')
    .data(countries.features)
    .join('path')
    .attr('class','land')
    .attr('d', path)
    .on('mouseover', function(event, d) {
      const isSelected = selectedMapRegion && isCountryInRegion(d.properties.name, selectedMapRegion);
      d3.select(this).attr('fill', isSelected ? '#ff8a00' : '#122a38');
    })
    .on('mouseout', function(event, d) {
      const isSelected = selectedMapRegion && isCountryInRegion(d.properties.name, selectedMapRegion);
      d3.select(this).attr('fill', isSelected ? '#ff6c00' : '#0a1a24');
    })
    .on('click', function(event, d) {
      handleCountryClick(d.properties.name);
    });

  // Group for news nodes (on top)
  mapNodeGroup = mapSvg.append('g').attr('class','node-layer');

  // Radar sweep overlay (animated conic arc)
  const radarGroup = mapSvg.append('g').attr('class','radar-layer');
  const sweepPath = radarGroup.append('path')
    .attr('fill','rgba(0,229,255,0.04)')
    .attr('stroke','none');
  const radarCircle = radarGroup.append('circle')
    .attr('cx', W*.45).attr('cy', H*.5)
    .attr('r', Math.min(W,H)*.38)
    .attr('fill','none')
    .attr('stroke','rgba(0,229,255,0.05)')
    .attr('stroke-width','1');

  let angle = 0;
  function animateRadar() {
    angle = (angle + 0.8) % 360;
    const cx = W*.45, cy = H*.5;
    const r  = Math.min(W,H)*.38;
    const a0 = (angle - 40) * Math.PI/180;
    const a1 = angle * Math.PI/180;
    const x0 = cx + r*Math.cos(a0), y0 = cy + r*Math.sin(a0);
    const x1 = cx + r*Math.cos(a1), y1 = cy + r*Math.sin(a1);
    sweepPath.attr('d', `M${cx},${cy} L${x0},${y0} A${r},${r} 0 0,1 ${x1},${y1} Z`);
    requestAnimationFrame(animateRadar);
  }
  animateRadar();

  const nodeLabel = document.getElementById('map-node-label');
  if (nodeLabel) nodeLabel.textContent = 'Map ready — awaiting news';
  pushDiag('D3 world map rendered successfully', 'ok');

  // Render any nodes already queued
  redrawMapNodes();
  updateAllStreams('Global');
}

// Load TopoJSON locally, fallback to CDN
fetch('/public/countries-110m.json')
  .then(r => r.json())
  .then(world => initMap(world))
  .catch(err => {
    pushDiag('Local map load failed — trying CDN fallback', 'warn');
    fetch('https://cdn.jsdelivr.net/npm/world-atlas@2/countries-110m.json')
      .then(r => r.json())
      .then(world => initMap(world))
      .catch(() => pushDiag('Map completely unavailable', 'err'));
  });

// Resize handler
window.addEventListener('resize', () => {
  if (!d3Projection || !mapSvg) return;
  const wrap = document.getElementById('map-wrap');
  if (!wrap) return;
  const W = wrap.clientWidth, H = wrap.clientHeight;
  mapSvg.attr('width', W).attr('height', H).attr('viewBox', `0 0 ${W} ${H}`);
});

// ─── GEO REGION LOOKUP ───
const GEO_DB = {
  'india':[20.59,78.96],'us':[37.09,-95.71],'usa':[37.09,-95.71],'united states':[37.09,-95.71],
  'uk':[55.38,-3.44],'united kingdom':[55.38,-3.44],'britain':[55.38,-3.44],
  'china':[35.86,104.2],'russia':[61.52,105.32],'europe':[54.5,15.25],
  'australia':[-25.27,133.78],'brazil':[-14.23,-51.93],'africa':[-8.78,34.51],
  'japan':[36.2,138.25],'canada':[56.13,-106.35],'germany':[51.17,10.45],
  'france':[46.23,2.21],'italy':[41.87,12.57],'spain':[40.46,-3.75],
  'pakistan':[30.37,69.34],'iran':[32.43,53.69],'turkey':[38.96,35.24],
  'south korea':[35.91,127.77],'mexico':[23.63,-102.55],'argentina':[-38.42,-63.62],
  'ukraine':[48.38,31.17],'israel':[31.05,34.85],'egypt':[26.82,30.8],
  'nigeria':[9.08,8.68],'kenya':[-0.02,37.91],'saudi arabia':[23.89,45.08],
  'myanmar':[16.87,96.19],'iraq':[33.22,43.68],
  'syria':[34.8,38.99],'lebanon':[33.88,35.86],'yemen':[15.55,48.52],
  'gaza':[31.35,34.31],'palestine':[31.35,34.31],'taiwan':[23.7,120.96],
  'north korea':[40.34,127.51],'indonesia':[-0.79,113.92],'vietnam':[14.06,108.28],
  'thailand':[15.87,100.99],'philippines':[12.88,121.77],'bangladesh':[23.68,90.36],
  'nepal':[28.39,84.12],'afghanistan':[33.93,67.71],'new zealand':[-40.9,174.89],
  'south africa':[-30.56,22.94],'ghana':[7.95,-1.02],'ethiopia':[9.15,40.49],
  'colombia':[4.57,-74.3],'chile':[-35.68,-71.54],'peru':[-9.19,-75.02],
  'venezuela':[6.42,-66.59],'greece':[39.07,21.82],'poland':[51.92,19.14],
  'sweden':[60.13,18.64],'norway':[60.47,8.47],'denmark':[56.26,9.5],
};

function articleToGeo(art) {
  const text = ((art.headline||'')+(art.summary||'')).toLowerCase();
  for (const [region, coords] of Object.entries(GEO_DB)) {
    if (text.includes(region)) return coords;
  }
  const fallbacks = [[20.59,78.96],[37.09,-95.71],[50,10],[-14.23,-51.93],[35.86,104.2],[9.08,8.68],[36.2,138.25],[-25.27,133.78]];
  return fallbacks[Math.floor(Math.random()*fallbacks.length)];
}

// ─── PUSH NEWS NODE ONTO REAL MAP ───
function pushMapNode(article) {
  const [lat, lon] = articleToGeo(article);
  mapNodes.push({
    lat: lat + (Math.random()-.5)*2,
    lon: lon + (Math.random()-.5)*2,
    headline: article.headline || '',
    born: Date.now(),
    phase: Math.random()*Math.PI*2,
    article: article
  });
  const live = mapNodes.filter(n => Date.now()-n.born < 90000);
  const countEl = document.getElementById('map-node-count');
  const labelEl = document.getElementById('map-node-label');
  if (countEl) countEl.textContent = `${live.length} nodes active`;
  if (labelEl) labelEl.textContent = `${live.length} news events geo-mapped`;
  redrawMapNodes();
}

function redrawMapNodes() {
  if (!mapNodeGroup || !d3Projection) return;
  const now = Date.now();
  mapNodes = mapNodes.filter(n => now - n.born < 90000);

  mapNodeGroup.selectAll('.news-node').remove();

  mapNodes.forEach(node => {
    const [px, py] = d3Projection([node.lon, node.lat]);
    const age = now - node.born;
    const alpha = Math.max(0.25, 1 - age / 90000);

    const g = mapNodeGroup.append('g')
      .attr('class','news-node')
      .attr('transform', `translate(${px},${py})`);

    // Outer glow ring
    g.append('circle')
      .attr('class','pulse')
      .attr('r', 9)
      .attr('fill','none')
      .attr('stroke',`rgba(255,107,0,${alpha*0.35})`)
      .attr('stroke-width','1');

    // Core dot
    g.append('circle')
      .attr('r', 3.5)
      .attr('fill','#ff6c00')
      .attr('opacity', alpha)
      .style('filter','drop-shadow(0 0 5px #ff6c00)');

    // Tooltip on hover
    g.on('mouseover', (event) => {
      if (tooltip) {
        tooltip.textContent = node.headline.substring(0,120);
        tooltip.classList.add('show');
        tooltip.style.left = (px+12)+'px';
        tooltip.style.top  = (py-10)+'px';
      }
    }).on('mouseout', () => {
      if (tooltip) tooltip.classList.remove('show');
    });

    // Click handler to open floating story card modal
    g.on('click', () => {
      openStoryModal(node.article);
    });
  });
}

function openStoryModal(article) {
  if (!article) return;
  const modal = document.getElementById('story-card-modal');
  if (!modal) return;
  document.getElementById('story-modal-cat').textContent = article.category || 'Global';
  document.getElementById('story-modal-headline').textContent = article.headline || '';
  document.getElementById('story-modal-body').textContent = article.summary || '';
  document.getElementById('story-modal-source').textContent = article.source || '';
  
  const sent = (article.sentiment || 'neutral').toLowerCase();
  const badge = document.getElementById('story-modal-sentiment');
  if (badge) {
    badge.textContent = sent;
    badge.className = `story-card-badge ${sent}`;
  }

  const btn = document.getElementById('story-modal-btn');
  if (btn) {
    if (article.url) {
      btn.style.display = 'block';
      btn.onclick = () => window.open(article.url, '_blank');
    } else {
      btn.style.display = 'none';
    }
  }

  modal.classList.add('show');
}

function closeStoryModal() {
  const modal = document.getElementById('story-card-modal');
  if (modal) modal.classList.remove('show');
}

// Periodically refresh node pulsing + expiry
setInterval(redrawMapNodes, 8000);

// ═══════════════════════════════════════════════════
//  VIEWPORT SYSTEM
// ═══════════════════════════════════════════════════

let currentTab = 'AMBIENT';
const tabPayloads = {
  AMBIENT: null, NEWS: null, SPORTS: null, WEATHER: null,
  STOCKS: null, SEARCH: null, PEOPLE: null, PRODUCTS: null, VIDEOS: null
};

// ─── STREAM CHANNEL SETS ───
const STREAM_SETS = {
  NEWS:    [
    { ch: 'UCNye-wNBqNL5ZzHSJj3l8Bg', label: 'AL JAZEERA' },
    { ch: 'UCknLrEdhRCp1aegoMqRaCZg', label: 'DW NEWS' },
  ],
  SPORTS:  [
    { ch: 'UCNNgtBEdsBIYh3dv5j61BYA', label: 'SKY SPORTS' },
    { ch: 'UCiWLfSweyRNmLpgEHekhoAg', label: 'ESPN' },
  ],
  cricket: [
    { ch: 'UCCkCNFVSMHvbQSXHCE6Xx1g', label: 'STAR SPORTS' },
    { ch: 'UCNNgtBEdsBIYh3dv5j61BYA', label: 'SKY SPORTS' },
  ],
  football: [
    { ch: 'UCNNgtBEdsBIYh3dv5j61BYA', label: 'SKY SPORTS' },
    { ch: 'UC9aHkKBEFsHDVD39CwNamkQ', label: 'PREMIER LEAGUE' },
  ],
  soccer: [
    { ch: 'UCNNgtBEdsBIYh3dv5j61BYA', label: 'SKY SPORTS' },
    { ch: 'UC9aHkKBEFsHDVD39CwNamkQ', label: 'PREMIER LEAGUE' },
  ],
  basketball: [
    { ch: 'UCiWLfSweyRNmLpgEHekhoAg', label: 'ESPN' },
    { ch: 'UCWX3yGbOAA0gFOA_OcGDjpA', label: 'NBA' },
  ],
  nba: [
    { ch: 'UCWX3yGbOAA0gFOA_OcGDjpA', label: 'NBA' },
    { ch: 'UCiWLfSweyRNmLpgEHekhoAg', label: 'ESPN' },
  ],
  f1: [
    { ch: 'UCB_qr75-ydFVKSF9Dmo6izg', label: 'F1 OFFICIAL' },
    { ch: 'UCNNgtBEdsBIYh3dv5j61BYA', label: 'SKY SPORTS F1' },
  ],
  formula1: [
    { ch: 'UCB_qr75-ydFVKSF9Dmo6izg', label: 'F1 OFFICIAL' },
    { ch: 'UCNNgtBEdsBIYh3dv5j61BYA', label: 'SKY SPORTS F1' },
  ],
  tennis: [
    { ch: 'UCmuB_tMVdDGe94fqnBRfHrw', label: 'ATP TENNIS' },
    { ch: 'UCNNgtBEdsBIYh3dv5j61BYA', label: 'SKY SPORTS' },
  ],
  AMBIENT:  null,
  WEATHER:  null,
  STOCKS:   null,
  SEARCH:   null,
  PEOPLE:   null,
  PRODUCTS: null,
  VIDEOS:   null,
};

function updateStreams(tab, sportType) {
  // Bypassed: undivided news dashboard uses updateAllStreams
}

function switchTab(tab) {
  closeStoryModal();
  fetch('/api/v1/viewport/set-tab', {
    method:'POST', headers:{'Content-Type':'application/json'},
    body: JSON.stringify({tab: 'NEWS'})
  }).catch(()=>{});
}

// ─── SOURCE EMOJI HELPER ───
function getSourceEmoji(source) {
  const s = (source || '').toLowerCase();
  if (s.includes('bbc'))        return '🇧🇳';
  if (s.includes('reuters'))    return '📰';
  if (s.includes('al jazeera')) return '🇶🇦';
  if (s.includes('cnn'))        return '🇺🇸';
  if (s.includes('guardian'))   return '🇬🇧';
  if (s.includes('ndtv') || s.includes('hindustan') || s.includes('india')) return '🇮🇳';
  if (s.includes('times'))      return '📰';
  if (s.includes('dw'))         return '🇩🇪';
  if (s.includes('sky'))        return '🇧🇳';
  return '📰';
}

// ─── IMAGE RENDER HELPER ───
function imgOrPlaceholder(url, cls, icon='📰') {
  if (url && url.startsWith('http')) {
    return `<img class="${cls}" src="${url}" alt="" loading="lazy" onerror="this.replaceWith(makePlaceholder('${icon}','${cls}'))">`;
  }
  return `<div class="${cls} news-img-placeholder">${icon}</div>`;
}

// ─── VIEWPORT RENDERER ───
function renderViewport(tab, data) {
  if (!data) return;

  let arts = [];
  if (data.articles) {
    arts = data.articles;
  } else if (data.headlines) {
    arts = data.headlines.map(h => ({
      headline: h,
      source: 'System',
      category: 'Status',
      sentiment: 'neutral'
    }));
  }

  renderRightSidebarHeadlines(arts);

  mapNodes = [];
  arts.forEach(a => pushMapNode(a));
  redrawMapNodes();

  const activeRegion = selectedMapRegion || 'Global';
  updateAllStreams(activeRegion);

  pushDiag(`Dashboard updated: ${arts.length} headlines displayed`, 'ok');
}

// ─── DEFAULT AMBIENT (never empty) ───
function renderDefaultAmbient() {
  const now = new Date();
  const tv = now.toLocaleTimeString([],{hour:'2-digit',minute:'2-digit'});
  const dv = now.toLocaleDateString([],{weekday:'long',month:'long',day:'numeric',year:'numeric'});
  renderViewport('AMBIENT', {
    time: tv, date: dv,
    weather_summary: 'ARIA Systems Nominal',
    headlines: [
      'ARIA Command Center initialised — all systems online',
      'Geo-intelligence map loaded with real country data',
      'Live news streams active — Al Jazeera & DW News',
      'Ask ARIA anything to populate this panel with live data'
    ],
    next_event: 'Awaiting your first query...'
  });
}
renderDefaultAmbient();
// Refresh ambient clock every minute
setInterval(() => {
  if (currentTab === 'AMBIENT' && !tabPayloads['AMBIENT']) renderDefaultAmbient();
}, 60000);

// ─── ACTIVE STATE POLLING ───
const TAB_MAP = {
  'SPORTS_WIDGET':'SPORTS','NEWS_WIDGET':'NEWS','WEATHER_WIDGET':'WEATHER',
  'STOCK_WIDGET':'STOCKS','SEARCH_WIDGET':'SEARCH','PERSON_WIDGET':'PEOPLE',
  'PRODUCT_WIDGET':'PRODUCTS','VIDEO_WIDGET':'VIDEOS','AMBIENT_WIDGET':'AMBIENT',
};

function fetchActiveState() {
  fetch('/api/v1/viewport/active-state')
    .then(r => r.json())
    .then(state => {
      if (!state) return;
      setStatus('online');
      let changed = false;

      if (state.ambient_widget_data && state.ambient_widget_data.view_type) {
        const tab = TAB_MAP[state.ambient_widget_data.view_type];
        if (tab) {
          const np = state.ambient_widget_data.payload;
          if (JSON.stringify(tabPayloads[tab]) !== JSON.stringify(np)) {
            tabPayloads[tab] = np;
            changed = true;
          }
        }
      }

      if (state.ambient_active_tab && state.ambient_active_tab !== currentTab) {
        const nt = state.ambient_active_tab;
        currentTab = nt;
        document.querySelectorAll('.vp-tab').forEach(b => b.classList.remove('active'));
        const btn = document.getElementById(`vp-tab-${nt}`);
        if (btn) btn.classList.add('active');
        const activeLabel = document.getElementById('vp-active-label');
        if (activeLabel) activeLabel.textContent = nt;
        changed = true;
        pushDiag(`Viewport switched → ${nt}`, 'ok');
        const st = (nt === 'SPORTS' && tabPayloads['SPORTS'])
          ? (tabPayloads['SPORTS'].sport_type || 'general').toLowerCase()
          : null;
        updateStreams(nt, st);
      }

      if (changed) {
        renderViewport(currentTab, tabPayloads[currentTab]);
      }
    })
    .catch(() => setStatus('offline'));
}

setInterval(fetchActiveState, 2000);
setTimeout(fetchActiveState, 800);

// ─── TOAST ───
let _tt;
function showToast(msg) {
  const t = document.getElementById('toast');
  if (t) {
    t.textContent = msg; t.classList.add('show');
    clearTimeout(_tt); _tt = setTimeout(() => t.classList.remove('show'), 2500);
  }
}

// ─── FIREBASE / COMMAND CONSOLE ───
const firebaseConfig = {
  apiKey:            "AIzaSyA5l74ebBKR8-veakGNISlwkIdasA-vQaQ",
  authDomain:        "aria-3e1da.firebaseapp.com",
  projectId:         "aria-3e1da",
  storageBucket:     "aria-3e1da.firebasestorage.app",
  messagingSenderId: "968886942490",
  appId:             "1:968886942490:web:8ab8c8a061ae6d79a94aa3"
};
firebase.initializeApp(firebaseConfig);
const db = firebase.firestore();

function sendCommand(text) {
  if (!text.trim()) return Promise.resolve();
  return db.collection("commands").doc("latest").set({
    id:        "cmd_" + Date.now(),
    text:      text.trim(),
    timestamp: Date.now()
  });
}

function sendCustomCommand() {
  const el = document.getElementById("cmd-input");
  if (!el) return;
  const t  = el.value.trim();
  if (!t) return;
  sendCommand(t).then(() => {
    showToast('Command Sent: "' + t + '"');
    pushDiag(`Command executed via console: ${t}`, 'ok');
  }).catch(err => {
    showToast("Failed to send command: " + err);
    pushDiag(`Failed to execute command: ${err}`, 'err');
  });
  el.value = "";
}

const cmdInput = document.getElementById("cmd-input");
if (cmdInput) {
  cmdInput.addEventListener("keydown", e => {
    if (e.key === "Enter") sendCustomCommand();
  });
}
