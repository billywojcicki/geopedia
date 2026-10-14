// Bottom sheet for phones. The sidebar becomes a sheet with three resting
// heights (peek, half, full), dragged by its top (handle, search row, list
// header, article bar) and released with momentum. On wider screens it does
// nothing and the sidebar stays a side panel.

// Must match the phone media query in css/app.css. Landscape phones keep the
// side panel (a bottom sheet would leave them almost no map).
// Narrow screens are phones whatever the orientation: a keyboard that shrinks
// the page (Android in-app browsers) mustn't flip the layout mid-typing.
export const PHONE = matchMedia('(max-width: 600px), (max-width: 860px) and (orientation: portrait)');

const PEEK = 76; // handle + search row
const FULL_GAP = 52; // map left visible above a full sheet
const FLICK = 0.45; // px/ms: a release faster than this moves one step

export class Sheet {
  constructor(el, { onChange, onDismiss }) {
    this.el = el;
    this.onChange = onChange; // (state) after every snap
    this.onDismiss = onDismiss; // dragged down past the lowest allowed state
    this.state = 'peek';
    this.states = ['peek', 'half', 'full'];
    this.drag = null;
    this.safeBottom = 0;

    // Moves are followed on the window: a fast drag leaves the sheet at once.
    this.onMove = e => this.move(e);
    this.onUp = e => this.up(e);
    this.onCancel = e => this.up(e, true);
    el.addEventListener('pointerdown', e => this.down(e));
    el.querySelector('#grabber').addEventListener('click', () => {
      if (this.moved) return;
      const i = this.states.indexOf(this.state);
      this.snap(this.states[(i + 1) % this.states.length]);
    });
    // The screen changed size (rotation, a browser toolbar, the keyboard): jump
    // to the new position with the timeline instead of sliding behind it, and
    // let the map re-pad.
    const relayout = () => {
      this.measure();
      this.el.classList.add('dragging');
      this.apply();
      requestAnimationFrame(() => this.el.classList.remove('dragging'));
      if (this.active) this.onChange(this.state);
    };
    addEventListener('resize', relayout);
    // Its height follows 100dvh, which can change without a resize event.
    new ResizeObserver(() => { if (this.active && this.el.offsetHeight !== this.full) relayout(); }).observe(el);
    PHONE.addEventListener('change', () => { relayout(); this.onChange(this.state); });
    this.measure();
    this.apply();
  }

  get active() { return PHONE.matches; }

  // Resting heights, in px of sheet showing above the bottom of the screen.
  measure() {
    const probe = document.createElement('div');
    probe.style.cssText = 'position:fixed;bottom:0;height:env(safe-area-inset-bottom);visibility:hidden';
    document.body.append(probe);
    this.safeBottom = probe.offsetHeight;
    probe.remove();
    // The sheet's own height, not innerHeight: under iOS Safari's floating
    // toolbar the two disagree, and the sheet would show more than it should
    // (covering the timeline, which is placed from the same bottom edge).
    this.full = (this.active && this.el.offsetHeight) || innerHeight - FULL_GAP;
    this.heights = {
      peek: PEEK + this.safeBottom,
      half: Math.round((this.full + FULL_GAP) * 0.5),
      full: this.full,
    };
  }

  visible(state = this.state) {
    return this.active ? this.heights[state] : 0;
  }

  // Which states the sheet may rest in (reading an article: no peek).
  allow(states) {
    this.states = states;
    if (!states.includes(this.state)) this.snap(states[0]);
  }

  snap(state, notify = true) {
    this.state = state;
    this.apply();
    if (notify) this.onChange(state);
  }

  apply(offset = 0) {
    if (!this.active) {
      this.el.style.removeProperty('--sheet-y');
      this.el.style.removeProperty('--sheet-hidden');
      return;
    }
    const y = Math.max(0, this.full - this.heights[this.state] + offset);
    this.el.style.setProperty('--sheet-y', `${y}px`);
    // Lets the content scroll its last rows above the bottom of the screen.
    this.el.style.setProperty('--sheet-hidden', `${this.full - this.heights[this.state]}px`);
  }

  // Drags start on the sheet's top parts only; the content below scrolls.
  down(e) {
    if (!this.active || e.button > 0) return;
    if (!e.target.closest('.grabber, .search-row, .list-head, .article-bar')) return;
    this.moved = false;
    this.drag = { y0: e.clientY, last: e.clientY, lastT: e.timeStamp, v: 0, id: e.pointerId, live: false };
    addEventListener('pointermove', this.onMove);
    addEventListener('pointerup', this.onUp);
    addEventListener('pointercancel', this.onCancel);
  }

  move(e) {
    const d = this.drag;
    if (!d || e.pointerId !== d.id) return;
    const dy = e.clientY - d.y0;
    if (!d.live) {
      if (Math.abs(dy) < 6) return; // still a tap
      d.live = true;
      this.moved = true;
      this.el.classList.add('dragging');
      document.activeElement?.blur?.();
    }
    const dt = e.timeStamp - d.lastT;
    if (dt > 0) d.v = 0.7 * d.v + 0.3 * ((e.clientY - d.last) / dt);
    d.last = e.clientY;
    d.lastT = e.timeStamp;
    // Resist past the top.
    const top = this.full - this.heights[this.state] + dy;
    this.apply(top < 0 ? dy - top + top / 3 : dy);
  }

  up(e, cancelled = false) {
    const d = this.drag;
    if (!d || e.pointerId !== d.id) return;
    this.drag = null;
    removeEventListener('pointermove', this.onMove);
    removeEventListener('pointerup', this.onUp);
    removeEventListener('pointercancel', this.onCancel);
    this.el.classList.remove('dragging');
    if (!d.live) return;
    if (cancelled) { this.apply(); return; }
    const shown = this.heights[this.state] - (e.clientY - d.y0);
    const order = this.states;
    let target;
    if (Math.abs(d.v) > FLICK) {
      const i = order.indexOf(this.state) + (d.v < 0 ? 1 : -1);
      target = i < 0 ? null : order[Math.min(i, order.length - 1)];
    } else {
      target = order.reduce((best, s) => (Math.abs(this.heights[s] - shown) < Math.abs(this.heights[best] - shown) ? s : best), order[0]);
      // Pulled well below the lowest allowed state: dismiss.
      if (shown < this.heights[order[0]] * 0.6) target = null;
    }
    if (target === null) {
      if (this.onDismiss && order[0] !== 'peek') return this.onDismiss();
      target = order[0];
    }
    this.snap(target);
  }
}
