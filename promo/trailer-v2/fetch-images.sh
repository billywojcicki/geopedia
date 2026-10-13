#!/bin/sh
# Downloads the callout photos named in cut.json (330 px Wikimedia Commons
# thumbnails) into cache/, retrying politely when rate limited.
set -e
DIR=$(cd "$(dirname "$0")" && pwd)
mkdir -p "$DIR/cache"
UA="GeopediaBuild/0.1 (https://github.com/billywojcicki/geopedia)"
node -e '
const c = require(process.argv[1]);
for (const x of c.callouts) {
  const name = x.img.slice(x.img.lastIndexOf("/") + 1), dir = x.img.slice(0, x.img.lastIndexOf("/") + 1);
  const enc = encodeURIComponent(name);
  console.log(`${x.img.replaceAll("/", "_")} https://upload.wikimedia.org/wikipedia/commons/thumb/${dir}${enc}/330px-${enc}`);
}' "$DIR/cut.json" | while read -r file url; do
  [ -s "$DIR/cache/$file" ] && continue
  for wait in 2 8 16 32; do
    code=$(curl -sS -A "$UA" -o "$DIR/cache/$file" -w "%{http_code}" "$url")
    [ "$code" = 200 ] && break
    rm -f "$DIR/cache/$file"; sleep $wait
  done
  echo "$code $file"
  sleep 2
done
