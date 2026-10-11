// Timeline: density histogram + scrubber with a non-linear year scale.

import { $, clamp, fmtYear, yearToPos, posToYear } from './util.js';
import { TICKS, MIN_YEAR, MAX_YEAR } from './config.js';

const MINOR_TICKS = [-1000, 500, 1700, 1950]; // hidden on narrow screens

export class Timeline {
  constructor({ hist, onInput }) {
    this.hist = hist; // { min, max, counts[] }
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

    const toYear = e => {
      const r = this.track.getBoundingClientRect();
      return Math.round(posToYear(clamp((e.clientX - r.left) / r.width, 0, 1)));
    };
    this.track.addEventListener('pointerdown', e => {
      this.track.setPointerCapture(e.pointerId);
      this.track.classList.add('dragging');
      this.onInput(toYear(e), true);
      const move = ev => this.onInput(toYear(ev), true);
      const up = () => {
        this.track.classList.remove('dragging');
        this.track.removeEventListener('pointermove', move);
        this.track.removeEventListener('pointerup', up);
        this.track.removeEventListener('pointercancel', up);
        this.onInput(this.year, false);
      };
      this.track.addEventListener('pointermove', move);
      this.track.addEventListener('pointerup', up);
      this.track.addEventListener('pointercancel', up);
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
    }, { passive: false });
  }

  renderTicks() {
    const ticks = $('#ticks');
    ticks.replaceChildren(...TICKS.map(y => {
      const s = document.createElement('span');
      s.style.left = `${yearToPos(y) * 100}%`;
      s.textContent = y === 1 ? 'AD 1' : y < 0 ? `${-y} BC` : String(y);
      if (MINOR_TICKS.includes(y)) s.className = 'minor';
      return s;
    }));
  }

  set(year, range) {
    this.year = year;
    this.range = range;
    this.handle.style.left = `${yearToPos(year) * 100}%`;
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
    if (!w) return;
    c.width = Math.round(w * dpr);
    c.height = Math.round(h * dpr);
    const ctx = c.getContext('2d');
    ctx.scale(dpr, dpr);
    const { min, counts } = this.hist;
    const cols = Math.floor(w / 2);
    const vals = new Float64Array(cols);
    for (let i = 0; i < cols; i++) {
      const y0 = Math.round(posToYear(i / cols)), y1 = Math.round(posToYear((i + 1) / cols));
      let s = 0;
      for (let y = y0; y < Math.max(y1, y0 + 1); y++) s += counts[y - min] || 0;
      vals[i] = Math.sqrt(s);
    }
    const max = Math.max(...vals) || 1;
    const dark = matchMedia('(prefers-color-scheme: dark)').matches;
    ctx.fillStyle = dark ? 'rgba(235,235,245,0.22)' : 'rgba(60,60,67,0.18)';
    for (let i = 0; i < cols; i++) {
      const bh = Math.max(1, (vals[i] / max) * (h - 4));
      ctx.fillRect(i * 2, h - bh, 1.4, bh);
    }
  }
}
