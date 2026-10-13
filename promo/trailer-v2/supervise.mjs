// Renders every missing frame in short chunks, each in a fresh browser, a few
// at a time; a chunk that stops making progress is killed and its remaining
// frames go back in the queue.
//   node supervise.mjs frames [workers]          (FPS and SCALE pass through)
import { spawn } from 'node:child_process';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const here = path.dirname(fileURLToPath(import.meta.url));
const [,, dir, workersArg] = process.argv;
const WORKERS = Number(workersArg ?? 3), CHUNK = 40, STALL_MS = 120000;
const cfg = JSON.parse(fs.readFileSync(path.join(here, 'cut.json'), 'utf8'));
const total = Math.round(cfg.duration * Number(process.env.FPS || 30));
fs.mkdirSync(dir, { recursive: true });
const have = f => fs.existsSync(path.join(dir, `f${String(f).padStart(4, '0')}.png`));

function chunks() {
  const out = [];
  for (let f = 0; f < total; f++) {
    if (have(f)) continue;
    const last = out.at(-1);
    if (last && last[1] === f && f - last[0] < CHUNK) last[1] = f + 1;
    else out.push([f, f + 1]);
  }
  return out;
}

const queue = chunks();
console.log(`${queue.length} chunks, ${queue.reduce((n, [a, b]) => n + b - a, 0)} frames to render`);

function run([a, b]) {
  return new Promise(res => {
    const p = spawn('node', [path.join(here, 'capture.mjs'), dir, String(a), String(b)], { stdio: 'ignore' });
    let count = 0, lastProgress = Date.now();
    const timer = setInterval(() => {
      let n = 0;
      for (let f = a; f < b; f++) if (have(f)) n++;
      if (n !== count) { count = n; lastProgress = Date.now(); }
      if (Date.now() - lastProgress > STALL_MS) { console.log(`stall in ${a}-${b} at ${count} done: restarting`); p.kill('SIGKILL'); }
    }, 5000);
    p.on('exit', () => {
      clearInterval(timer);
      // Whatever is still missing in this range goes back in the queue.
      let f = a;
      while (f < b) {
        if (have(f)) { f++; continue; }
        let g = f;
        while (g < b && !have(g)) g++;
        queue.push([f, g]);
        f = g;
      }
      res();
    });
  });
}

async function worker() {
  while (queue.length) {
    await run(queue.shift());
    const done = [...Array(total).keys()].filter(have).length;
    console.log(`${new Date().toISOString().slice(11, 19)} ${done}/${total} frames`);
  }
}
await Promise.all([...Array(WORKERS)].map(worker));
console.log('missing after run:', [...Array(total).keys()].filter(f => !have(f)).length);
