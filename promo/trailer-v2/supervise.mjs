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
const WORKERS = Number(workersArg ?? 3), CHUNK = 60, STALL_MS = 120000;
const cfg = JSON.parse(fs.readFileSync(path.join(here, 'cut.json'), 'utf8'));
const total = Math.round(cfg.duration * Number(process.env.FPS || 30));
fs.mkdirSync(dir, { recursive: true });
const have = f => fs.existsSync(path.join(dir, `f${String(f).padStart(4, '0')}.jpg`));

// Windows of up to CHUNK frames, each listing the frames it still needs
// (they can be sparse: a 15 fps draft fills every other frame of 30 fps).
function chunks() {
  const out = [];
  for (let f = 0; f < total;) {
    if (have(f)) { f++; continue; }
    const b = Math.min(total, f + CHUNK), miss = [];
    for (let g = f; g < b; g++) if (!have(g)) miss.push(g);
    out.push(miss);
    f = b;
  }
  return out;
}

const queue = chunks();
console.log(`${queue.length} chunks, ${queue.reduce((n, c) => n + c.length, 0)} frames to render`);

function run(miss) {
  return new Promise(res => {
    const a = miss[0], b = miss.at(-1) + 1;
    const p = spawn('node', [path.join(here, 'capture.mjs'), dir, String(a), String(b)],
      { stdio: 'ignore', env: { ...process.env, FRAMES: miss.join(',') } });
    let count = 0, lastProgress = Date.now();
    const timer = setInterval(() => {
      const n = miss.filter(have).length;
      if (n !== count) { count = n; lastProgress = Date.now(); }
      if (Date.now() - lastProgress > STALL_MS) { console.log(`stall in ${a}-${b} at ${count} done: restarting`); p.kill('SIGKILL'); }
    }, 5000);
    p.on('exit', () => {
      clearInterval(timer);
      // Whatever is still missing goes back in the queue.
      const left = miss.filter(f => !have(f));
      if (left.length) queue.push(left);
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
