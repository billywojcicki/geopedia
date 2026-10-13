#!/usr/bin/env python3
"""Render each MIDI channel of score.mid to its own stereo stem with TinySoundFont.

Section doubling: most stems are rendered 2-3 times with small detune (cents),
small onset delays and different pan positions, then summed -> ensemble width.
Expression (CC11) is NOT applied here; mix.py applies it as a smooth gain curve.

Usage: render_stems.py <score.mid> <soundfont.sf2> <out.npz>
"""
import sys
import time

import mido
import numpy as np
import tinysoundfont

SR = 48000
RENDER_SEC = 30.4

# ch: (name, bank, program, drums, layers[(detune_semitones, pan, delay_s, gain)], offset_s, width)
STEMS = {
    0: ('violins', 0, 48, False, [(-0.07, -0.50, 0.000, 1.0), (0.07, -0.20, 0.011, 1.0)], -0.050, 0.9),
    1: ('strings_pad', 0, 49, False, [(-0.06, -0.45, 0.000, 1.0), (0.06, 0.45, 0.009, 1.0)], -0.060, 1.0),
    2: ('tremolo', 0, 44, False, [(-0.05, -0.65, 0.000, 1.0), (0.05, 0.25, 0.007, 1.0)], -0.020, 1.0),
    3: ('cellos', 0, 42, False, [(-0.06, 0.22, 0.000, 1.0), (0.06, 0.42, 0.008, 1.0)], -0.015, 0.6),
    4: ('basses', 0, 43, False, [(-0.05, 0.25, 0.000, 1.0), (0.05, 0.40, 0.006, 1.0)], -0.010, 0.4),
    5: ('horns', 0, 60, False, [(-0.06, -0.26, 0.000, 1.0), (0.06, 0.00, 0.012, 1.0), (0.0, -0.12, 0.006, 0.8)], -0.012, 0.8),
    6: ('trombones', 0, 57, False, [(-0.05, 0.28, 0.000, 1.0), (0.05, 0.48, 0.009, 1.0)], -0.010, 0.7),
    7: ('trumpets', 0, 56, False, [(-0.04, 0.10, 0.000, 1.0), (0.04, 0.30, 0.008, 1.0)], 0.000, 0.7),
    8: ('tuba', 0, 58, False, [(0.0, 0.30, 0.000, 1.0)], -0.010, 0.5),
    9: ('percussion', 128, 48, True, [(0.0, -0.05, 0.000, 1.0)], 0.000, 1.0),
    10: ('choir_aahs', 0, 52, False, [(-0.08, -0.55, 0.000, 1.0), (0.08, 0.55, 0.013, 1.0)], -0.050, 1.0),
    11: ('choir_oohs', 0, 53, False, [(-0.08, -0.60, 0.000, 1.0), (0.08, 0.60, 0.011, 1.0)], -0.010, 1.0),
    12: ('harp', 0, 46, False, [(0.0, -0.40, 0.000, 1.0)], 0.000, 1.0),
    13: ('celesta', 0, 8, False, [(0.0, 0.50, 0.000, 1.0)], 0.000, 1.0),
    14: ('timpani', 0, 47, False, [(0.0, 0.05, 0.000, 1.0)], 0.000, 1.0),
    15: ('violas', 0, 41, False, [(-0.06, 0.02, 0.000, 1.0), (0.06, 0.24, 0.009, 1.0)], -0.010, 0.7),
}


# Per-note rendering with a custom smooth release (seconds) for patches whose SoundFont release is
# abrupt (brass, short-release strings): the note is held in the synth and faded out by us after its
# MIDI note-off with a raised-cosine curve, so no note-off clicks.
CUSTOM_RELEASE = {'cellos': 0.12, 'violas': 0.12, 'basses': 0.20, 'horns': 0.22,
                  'trombones': 0.20, 'trumpets': 0.16, 'tuba': 0.25}


def note_list(events):
    """Pair note-on/off (FIFO per key) -> [(start_s, end_s, key, vel)]."""
    pending, out = {}, []
    for (t, on, key, vel) in events:
        if on:
            pending.setdefault(key, []).append((t, vel))
        elif pending.get(key):
            s0, v = pending[key].pop(0)
            out.append((s0, t, key, v))
    return out


def render_layer_per_note(sfbytes, ch, bank, prog, detune, notes, n, rel):
    syn = tinysoundfont.Synth(samplerate=SR, gain=0)
    sid = syn.sfload(sfbytes, max_voices=512)
    syn.program_select(ch, sid, bank, prog, is_drums=False)
    syn.control_change(ch, 7, 127)
    syn.control_change(ch, 11, 127)
    if detune:
        syn.set_tuning(ch, detune)
    out = np.zeros((n, 2), np.float32)
    starts = np.array(sorted(nt[0] for nt in notes))
    for (t0, t1, key, vel) in notes:
        a = int(round(t0 * SR))
        hold = max(1, int(round((t1 - t0) * SR)))
        if a >= n:
            continue
        # legato successor (a note starting just before/at this note-off): short 60 ms crossfade;
        # phrase end / rest: the full smooth release
        legato = np.any((starts > t0 + 1e-4) & (starts >= t1 - 0.15) & (starts <= t1 + 0.03))
        rn = int((0.06 if legato else rel) * SR)
        fade = (0.5 * (1 + np.cos(np.linspace(0, np.pi, rn)))).astype(np.float32)
        syn.noteon(ch, key, vel)
        x = np.frombuffer(syn.generate_simple(hold + rn), dtype=np.float32).reshape(-1, 2).copy()
        syn.sounds_off(ch)
        syn.generate_simple(256)          # flush
        x[hold:] *= fade[:, None]
        b = min(n, a + len(x))
        out[a:b] += x[:b - a]
    del syn
    return out


# Brass is rendered with FluidSynth (honours the SoundFont's SF2.01 modulators, e.g. velocity -> filter
# cutoff, so soft notes are darker and loud notes brassier); everything else with TinySoundFont.
FLUID_STEMS = {'horns', 'trombones', 'trumpets', 'tuba'}
_SF_PATH = None


def render_layer_per_note_fs(ch, bank, prog, detune, notes, n, rel):
    import os
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from fs_engine import FS
    fs = FS(_SF_PATH, sr=SR, gain=0.5)
    fs.program(ch, bank, prog)
    fs.s.cc(ch, 7, 127)
    fs.s.cc(ch, 11, 127)
    fs.s.cc(ch, 91, 0)
    fs.s.cc(ch, 93, 0)
    if detune:
        fs.s.pitch_bend(ch, int(round(detune / 2.0 * 8192)))   # default bend range +-2 semitones
    out = np.zeros((n, 2), np.float32)
    starts = np.array(sorted(nt[0] for nt in notes))
    for (t0, t1, key, vel) in notes:
        a = int(round(t0 * SR))
        hold = max(1, int(round((t1 - t0) * SR)))
        if a >= n:
            continue
        legato = np.any((starts > t0 + 1e-4) & (starts >= t1 - 0.15) & (starts <= t1 + 0.03))
        rn = int((0.06 if legato else rel) * SR)
        fade = (0.5 * (1 + np.cos(np.linspace(0, np.pi, rn)))).astype(np.float32)
        fs.s.noteon(ch, key, vel)
        x = fs.render(hold + rn)
        fs.s.all_sounds_off(ch)
        fs.render(512)
        x[hold:] *= fade[:, None]
        b = min(n, a + len(x))
        out[a:b] += x[:b - a]
    fs.s.delete()
    return out * 2.0     # FluidSynth gain 0.5 -> roughly TinySoundFont scale (mix re-balances anyway)


def load_events(path):
    mid = mido.MidiFile(path)
    ev = {ch: [] for ch in range(16)}
    t = 0.0
    for msg in mid:                      # merged, delta time in seconds (tempo map applied)
        t += msg.time
        if msg.type == 'note_on' and msg.velocity > 0:
            ev[msg.channel].append((t, 1, msg.note, msg.velocity))
        elif msg.type == 'note_off' or (msg.type == 'note_on' and msg.velocity == 0):
            ev[msg.channel].append((t, 0, msg.note, 0))
    for ch in ev:
        ev[ch].sort(key=lambda e: (e[0], e[1]))   # note-offs before note-ons at equal times
    return ev


def pan_stereo(x, pan, width):
    m = 0.5 * (x[:, 0] + x[:, 1])
    s = 0.5 * (x[:, 0] - x[:, 1]) * width
    th = (pan + 1.0) * np.pi / 4.0
    gl, gr = np.cos(th) * np.sqrt(2.0), np.sin(th) * np.sqrt(2.0)
    return np.stack([m * gl + s, m * gr - s], axis=1)


def render_layer(sfbytes, ch, bank, prog, drums, detune, events, n):
    syn = tinysoundfont.Synth(samplerate=SR, gain=0)
    sid = syn.sfload(sfbytes, max_voices=512)
    syn.program_select(ch, sid, bank, prog, is_drums=drums)
    syn.control_change(ch, 7, 127)
    syn.control_change(ch, 11, 127)
    if detune:
        syn.set_tuning(ch, detune)
    out = np.zeros((n, 2), np.float32)
    pos = 0
    for (t, on, key, vel) in events:
        k = min(n, int(round(t * SR)))
        if k > pos:
            out[pos:k] = np.frombuffer(syn.generate_simple(k - pos), dtype=np.float32).reshape(-1, 2)
            pos = k
        if on:
            syn.noteon(ch, key, vel)
        else:
            syn.noteoff(ch, key)
    if pos < n:
        out[pos:] = np.frombuffer(syn.generate_simple(n - pos), dtype=np.float32).reshape(-1, 2)
    del syn
    return out


def shift(x, sec):
    k = int(round(sec * SR))
    if k == 0:
        return x
    y = np.zeros_like(x)
    if k > 0:
        y[k:] = x[:-k]
    else:
        y[:k] = x[-k:]
    return y


def main():
    global _SF_PATH
    midi_path, sf_path, out_path = sys.argv[1:4]
    _SF_PATH = sf_path
    sfbytes = open(sf_path, 'rb').read()
    ev = load_events(midi_path)
    n = int(RENDER_SEC * SR)
    stems = {}
    for ch, (name, bank, prog, drums, layers, offset, width) in STEMS.items():
        t0 = time.time()
        acc = np.zeros((n, 2), np.float32)
        norm = 1.0 / np.sqrt(sum(g * g for *_, g in layers))
        for (detune, pan, delay, g) in layers:
            if name in FLUID_STEMS:
                x = render_layer_per_note_fs(ch, bank, prog, detune, note_list(ev[ch]), n, CUSTOM_RELEASE[name])
            elif name in CUSTOM_RELEASE:
                x = render_layer_per_note(sfbytes, ch, bank, prog, detune, note_list(ev[ch]), n, CUSTOM_RELEASE[name])
            else:
                x = render_layer(sfbytes, ch, bank, prog, drums, detune, ev[ch], n)
            x = shift(x, offset + delay)
            acc += pan_stereo(x, pan, width) * (g * norm)
        stems[name] = acc
        pk = float(np.abs(acc).max())
        print(f'{name:12s} ch{ch:2d} notes {sum(1 for e in ev[ch] if e[1]):4d}  peak {20*np.log10(pk+1e-12):6.1f} dBFS  {time.time()-t0:4.1f}s', flush=True)
    np.savez(out_path, **stems)


if __name__ == '__main__':
    main()
