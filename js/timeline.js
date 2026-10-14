// Timeline: density histogram + scrubber with a non-linear year scale.

import { $, clamp, fmtYear, yearToPos, posToYear } from './util.js';
import { TICKS, MIN_YEAR, MAX_YEAR } from './config.js';

const MINOR_TICKS = [-1000, 500, 1700, 1950]; // hidden on narrow screens

export class Timeline {
  constructor({ onInput }) {
    this.hist = null; // { min, max, counts[] }, arrives after first paint
    this.onInput = onInput;
    this.track = $('#track');
    this.canvas = $('#hist');
    this.handle = $('#handle');
    this.windowEl = $('#window');
    this.year = 0;
    this.range = [0, 0];

    this.renderTicks();
    new ResizeObserver(() => this.draw()).observe(this.track);
    matchMedia('(prefers-color-scheme: dark)').addEventListener('change', () => this.draw());

    this.track.addEventListener('pointerdown', e => {
      const touch = e.pointerType !== 'mouse';
      const r = this.track.getBoundingClientRect();
      const at = ev => clamp((ev.clientX - r.left) / r.width, 0, 1);
      // A finger near the knob drags it from where it is instead of jumping it
      // under the finger; elsewhere, as with a mouse, the knob jumps there.
      const grab = touch && Math.abs(e.clientX - (r.left + yearToPos(this.year) * r.width)) < 28;
      let pos = grab ? yearToPos(this.year) : at(e);
      let live = !touch; // a touch waits to see whether it's a sideways drag
      let lastX = e.clientX, lastT = e.timeStamp;
      const emit = () => this.onInput(Math.round(posToYear(pos)), true);
      const start = () => { live = true; this.track.classList.add('dragging'); emit(); };
      const move = ev => {
        if (!live) {
          const dx = ev.clientX - e.clientX, dy = ev.clientY - e.clientY;
          if (Math.hypot(dx, dy) < 8) return;
          if (Math.abs(dy) > Math.abs(dx)) { end(false); return; } // a vertical swipe: not for us
          start();
        }
        if (touch) {
          // Slow fingers move in finer steps, so single years stay reachable.
          const dx = ev.clientX - lastX;
          const speed = Math.abs(dx) / Math.max(1, ev.timeStamp - lastT);
          pos = clamp(pos + (dx * (speed < 0.12 ? 0.25 : speed < 0.35 ? 0.5 : 1)) / r.width, 0, 1);
        } else {
          pos = at(ev);
        }
        lastX = ev.clientX; lastT = ev.timeStamp;
        emit();
      };
      const end = apply => {
        this.track.classList.remove('dragging');
        this.track.removeEventListener('pointermove', move);
        this.track.removeEventListener('pointerup', up);
        this.track.removeEventListener('pointercancel', cancel);
        if (this.track.hasPointerCapture(e.pointerId)) this.track.releasePointerCapture(e.pointerId);
        if (apply) this.onInput(this.year, false);
      };
      const up = () => {
        if (!live && !grab) { pos = at(e); emit(); } // a tap: go there
        end(true);
      };
      const cancel = () => end(live);
      this.track.setPointerCapture(e.pointerId);
      if (live) start();
      this.track.addEventListener('pointermove', move);
      this.track.addEventListener('pointerup', up);
      this.track.addEventListener('pointercancel', cancel);
    });
    this.track.addEventListener('keydown', e => {
      const step = e.shiftKey ? 10 : 1;
      const k = { ArrowLeft: -step, ArrowDown: -step, ArrowRight: step, ArrowUp: step, PageDown: -100, PageUp: 100 }[e.key];
      if (k) { e.preventDefault(); this.onInput(clamp(this.year + k, MIN_YEAR, MAX_YEAR), false); }
      if (e.key === 'Home') this.onInput(MIN_YEAR, false);
      if (e.key === 'End') this.onInput(MAX_YEAR, false);
    });
    // Trackpad / wheel scrubbing, scaled so it feels the same across eras.
    let acc = 0;
    this.track.addEventListener('wheel', e => {
      e.preventDefault();
      acc += (Math.abs(e.deltaX) > Math.abs(e.deltaY) ? e.deltaX : e.deltaY);
      const w = this.track.clientWidth;
      const p = clamp(yearToPos(this.year) + acc / (w * 6), 0, 1);
      const y = Math.round(posToYear(p));
      if (y !== this.year) { acc = 0; this.onInput(clamp(y, MIN_YEAR, MAX_YEAR), false); }
      // At either end the wheel can't move further: don't let it wind up.
      else if ((p === 0 && acc < 0) || (p === 1 && acc > 0)) acc = 0;
    }, { passive: false });
  }

  renderTicks() {
    const ticks = $('#ticks');
    this.tickEls = [];
    ticks.replaceChildren(...TICKS.map(y => {
      const s = document.createElement('span');
      s.style.left = `${yearToPos(y) * 100}%`;
      this.tickEls.push([s, yearToPos(y)]);
      s.textContent = y === 1 ? 'AD 1' : y < 0 ? `${-y} BC` : String(y);
      if (MINOR_TICKS.includes(y)) s.className = 'minor';
      return s;
    }));
  }

  setHist(hist) {
    this.hist = hist;
    this.cum = null;
    this.draw();
  }

  set(year, range) {
    this.year = year;
    this.range = range;
    const p = yearToPos(year);
    this.handle.style.left = `${p * 100}%`;
    // The knob's label sits where a tick label would: that one steps aside.
    const w = this.track.clientWidth;
    for (const [s, tp] of this.tickEls) s.classList.toggle('covered', Math.abs(tp - p) * w < 24);
    const a = yearToPos(range[0]), b = yearToPos(range[1]);
    this.windowEl.style.left = `${a * 100}%`;
    this.windowEl.style.width = `max(2px, ${(b - a) * 100}%)`;
    this.track.setAttribute('aria-valuenow', year);
    this.track.setAttribute('aria-valuetext', fmtYear(year));
  }

  // Histogram of recorded happenings, one bar per pixel column, sqrt-scaled.
  draw() {
    const c = this.canvas, dpr = devicePixelRatio || 1;
    const w = c.clientWidth, h = c.clientHeight;
    if (!w || !this.hist) return;
    c.width = Math.round(w * dpr);
    c.height = Math.round(h * dpr);
    const ctx = c.getContext('2d');
    ctx.scale(dpr, dpr);
    const { min, counts } = this.hist;
    // Running totals make each column's sum one subtraction.
    if (!this.cum) {
      this.cum = new Float64Array(counts.length + 1);
      for (let i = 0; i < counts.length; i++) this.cum[i + 1] = this.cum[i] + counts[i];
    }
    const sum = (y0, y1) => {
      const a = Math.max(0, Math.min(counts.length, y0 - min)), b = Math.max(a + 1, Math.min(counts.length, y1 - min));
      return this.cum[b] - this.cum[a];
    };
    const cols = Math.floor(w / 2);
    const vals = new Float64Array(cols);
    let max = 1;
    for (let i = 0; i < cols; i++) {
      vals[i] = Math.sqrt(sum(Math.round(posToYear(i / cols)), Math.round(posToYear((i + 1) / cols))));
      if (vals[i] > max) max = vals[i];
    }
    const dark = matchMedia('(prefers-color-scheme: dark)').matches;
    ctx.fillStyle = dark ? 'rgba(235,235,245,0.22)' : 'rgba(60,60,67,0.18)';
    const bars = new Path2D(); // one fill instead of hundreds
    for (let i = 0; i < cols; i++) {
      const bh = Math.max(1, (vals[i] / max) * (h - 4));
      bars.rect(i * 2, h - bh, 1.4, bh);
    }
    ctx.fill(bars);
  }
}
