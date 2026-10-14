# Deploying Geopedia to Cloudflare

From this repo to a live site on your own domain, on Cloudflare Workers (static assets, free plan). About an hour of clicking, plus up to a day for a newly moved domain to go active. `geopedia.example` below stands for your real domain.

The repo is already set up for it:
- `wrangler.jsonc`: a static site, `404.html` for unknown paths.
- `.assetsignore`: keeps `promo/` (the trailers are over Cloudflare's 25 MiB per-file limit), `scripts/` and other non-site files out of the upload.
- `_headers`: caching (a year for versioned data and MapLibre, always fresh for the app itself).

None of these affect GitHub Pages.

## 1. Before you start

1. Merge `claude/wiki-map-timeline-h6jl7p` into `main`. Cloudflare deploys whatever is on `main`.
2. Replace `https://billywojcicki.github.io/geopedia/` with `https://geopedia.example/` in `index.html` (canonical, og:url, og:image, twitter:image and the JSON-LD block: 7 places).

## 2. Account and domain

1. Sign up at https://dash.cloudflare.com/sign-up (free plan).
2. Put the domain on Cloudflare:
   - **Buying it new:** Domain Registration > Register Domains. Nothing else to do.
   - **Already own it:** dashboard home > **Add a domain**, pick the Free plan, review the scanned DNS records (delete any for the bare domain or `www` that point at GitHub Pages; keep MX records for email), then swap your registrar's nameservers for the two Cloudflare shows. Wait for the domain to show **Active**.
3. In the domain's **SSL/TLS > Edge Certificates**, turn on **Always Use HTTPS**. Leave Rocket Loader off (it rewrites scripts and can break the map).

## 3. Deploy

1. **Workers & Pages > Create application**, then **Import a repository > Get started**.
2. Connect GitHub (only select repositories: `geopedia`) and pick the repo.
3. Settings:
   - Project name: `geopedia` (must match `"name"` in `wrangler.jsonc`)
   - Build command: empty
   - Deploy command: `npx wrangler deploy`
   - Root directory: empty
   - Branch: `main`
4. **Deploy.** The log should show about 930 assets uploaded and an address like `https://geopedia.<you>.workers.dev`. Open it: globe, timeline, a pin, "Continue reading".

## 4. Your domain

1. **Workers & Pages > geopedia > Settings > Domains & Routes > Add > Custom domain**, type `geopedia.example`. If it complains about an existing record, delete the old `@` record under DNS > Records and retry.
2. Send `www` to the main address:
   - DNS > Records > Add record: Type `AAAA`, Name `www`, address `100::`, Proxied.
   - Rules > Create rule > Redirect Rule, wildcard pattern: `https://www.geopedia.example/*` to `https://geopedia.example/${1}`, 301, preserve query string.

## 5. Check it

```sh
curl -sI https://geopedia.example/ | grep -iE "^HTTP|^cache-control"            # 200, no-cache
curl -sI "https://geopedia.example/data/index.json" | grep -i "^cache-control"   # no-cache
curl -sI https://geopedia.example/promo/geopedia-trailer-v2.mp4 | head -1        # 404 (not uploaded)
curl -sI https://geopedia.example/nope | head -1                                 # 404
curl -sI https://www.geopedia.example/ | grep -iE "^HTTP|^location"              # 301
```

Then on a real phone, including inside the X app: open the site, drag the timeline, open an article, press Back. Paste the URL into a draft post on X to check the card preview (don't post yet).

## 6. After launch

- **Old links:** keep GitHub Pages on and add this right after `<meta charset="utf-8">` in `index.html`, so old `github.io` links open the same view on the new domain:
  ```html
  <script>if (location.hostname === 'billywojcicki.github.io') location.replace('https://geopedia.example/' + location.hash);</script>
  ```
- **Visitor counts (optional):** Web Analytics > Add a site, copy the snippet to just before `</body>`. Free, no cookies.
- **Updating:** merge to `main`; it deploys in a couple of minutes.
- **Rolling back:** Workers & Pages > geopedia > Deployments > Rollback.
- **New preview image:** replace `og.jpg` and bump its `?v=` in `index.html` (X caches cards by URL).

## If something goes wrong

| What you see | Fix |
|---|---|
| "Asset too large ... .mp4" | `.assetsignore` must be in the repo root with `/promo/` in it. |
| Worker name mismatch | Make the dashboard project name and `wrangler.jsonc` both `geopedia`. |
| Custom domain won't add | Delete the old DNS record for that name, or wait for the domain to go Active. |
| Zoomed-in streets blank | OpenFreeMap is down; pins and articles keep working. |
| "Couldn't reach Wikipedia" | Wikipedia rate-limited that visitor; clears in a minute. |
