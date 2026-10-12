// Live Wikipedia content for the reading panel (summaries and full articles).
// Map data is static; article text is fetched on demand from the public API.

const summaries = new Map();
const articles = new Map();

export function fetchSummary(title) {
  if (!summaries.has(title)) {
    const url = `https://en.wikipedia.org/api/rest_v1/page/summary/${encodeURIComponent(title.replace(/ /g, '_'))}`;
    summaries.set(title, fetch(url).then(r => (r.ok ? r.json() : null)).catch(() => null).then(v => {
      if (!v) summaries.delete(title); // don't remember failures (e.g. a flaky prefetch)
      return v;
    }));
  }
  return summaries.get(title);
}

const DROP = [
  'style', 'link', 'script', 'noscript', '.mw-editsection', '.navbox', '.vertical-navbox', '.sistersitebox',
  '.noprint', '.mw-empty-elt', '.ambox', '.metadata', '.authority-control', '.reflist', '.refbegin',
  'ol.references', '.shortdescription', '.hatnote', '.navigation-not-searchable', '.mw-references-wrap',
  'sup.reference', '.portalbox', '.side-box', '.stub',
];
const DROP_SECTIONS = /^(references|notes|citations|sources|bibliography|further reading|external links|see also|footnotes|works cited|notes and references)$/i;

export function fetchArticle(title) {
  if (!articles.has(title)) {
    const url = 'https://en.wikipedia.org/w/api.php?action=parse&format=json&formatversion=2&origin=*'
      + '&prop=text&redirects=1&disableeditsection=1&disabletoc=1&mobileformat=1&page=' + encodeURIComponent(title);
    articles.set(title, fetch(url).then(r => r.json()).then(j => clean(j?.parse?.text || '')).catch(() => null));
  }
  return articles.get(title);
}

function clean(html) {
  const doc = new DOMParser().parseFromString(html, 'text/html');
  const root = doc.body;
  for (const sel of DROP) root.querySelectorAll(sel).forEach(n => n.remove());

  // Drop reference-y sections (heading plus everything up to the next heading).
  for (const h of [...root.querySelectorAll('h2')]) {
    if (!DROP_SECTIONS.test(h.textContent.trim())) continue;
    const head = h.closest('.mw-heading') || h;
    let n = head.nextElementSibling;
    while (n && !(n.matches('h2, .mw-heading2') || n.querySelector(':scope > h2'))) {
      const next = n.nextElementSibling;
      n.remove();
      n = next;
    }
    head.remove();
  }

  for (const n of root.querySelectorAll('*')) {
    for (const a of [...n.attributes]) if (a.name.startsWith('on') || a.name === 'style') n.removeAttribute(a.name);
  }
  for (const a of root.querySelectorAll('a')) {
    const h = a.getAttribute('href') || '';
    if (h.startsWith('/wiki/') || h.startsWith('./')) a.href = 'https://en.wikipedia.org/wiki/' + h.replace(/^(\/wiki\/|\.\/)/, '');
    else if (h.startsWith('#') || !h) { a.removeAttribute('href'); continue; }
    a.target = '_blank';
    a.rel = 'noopener';
  }
  for (const img of root.querySelectorAll('img')) {
    for (const attr of ['src', 'srcset']) {
      const v = img.getAttribute(attr);
      if (v) img.setAttribute(attr, v.replace(/(^|\s|,)\/\//g, '$1https://'));
    }
    img.loading = 'lazy';
  }
  return root.innerHTML;
}
