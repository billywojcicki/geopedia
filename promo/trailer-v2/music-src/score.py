#!/usr/bin/env python3
"""The trailer's score: an 80s synth anthem at 120 BPM with a 2001-style dawn.

Written to the picture in ../cut.json: a cold open (the comet race), a hush
of timpani and brass for the sunrise, a drop on the impact, the sweep through
history (a bell on every callout, a key change up a step at 20 s), the payoff,
a swell as the world collapses, and the final hit at 28 s.

Synths are numpy (synth.py); timpani, brass, horns, organ, strings, choir and
the orchestra hits come from the MuseScore General soundfont through FluidSynth.

Usage: score.py <soundfont.sf2> <out_dir>   -> premaster.wav, stems.npz, cues.json
"""
import json
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))  # synth.py, fs_engine.py (python -I skips it)
from synth import (SR, adsr, butter, chorus, clap, convolve, crash, expdecay, filt, fm_bell, gated_verb, hat, kick,
                   midi_hz, osc, pan, pingpong, place, reverb_ir, riser, secs, sidechain, snare_dry, sub_boom, supersaw,
                   tom, tvfilt)

HERE = os.path.dirname(os.path.abspath(__file__))
CUT = json.load(open(os.path.join(HERE, '..', 'cut.json')))
LEN = 31.0
N = int(LEN * SR)


def add(*xs):
    """Sum mono arrays of different lengths."""
    out = np.zeros(max(len(x) for x in xs))
    for x in xs:
        out[:len(x)] += x
    return out


def T(bar, pos=0.0):
    """Time of a 16th-note position in a bar (1-based bars, 2 s each)."""
    return (bar - 1) * 2.0 + pos * 0.125


# ---- harmony -----------------------------------------------------------------
CHORDS = [(0, 2, 'Dm'), (2, 3, 'Bb'), (3, 4, 'C'),
          (8, 10, 'Dm'), (10, 12, 'Bb'), (12, 14, 'F'), (14, 16, 'C'),
          (16, 18, 'Dm'), (18, 19, 'Bb'), (19, 20, 'C'),
          (20, 22, 'Em'), (22, 23, 'C'), (23, 24, 'D'),
          (24, 25, 'Em'), (25, 26, 'C'), (26, 27, 'G'), (27, 28, 'D'), (28, 31, 'E')]
PC = {'Dm': 2, 'Bb': 10, 'F': 5, 'C': 0, 'Em': 4, 'G': 7, 'D': 2, 'E': 4}
MINOR = {'Dm', 'Em'}


def triad(name):
    return [0, 3, 7] if name in MINOR else [0, 4, 7]


def near(lo, name):
    """The chord's root as the first MIDI note at or above lo."""
    return lo + (PC[name] - lo) % 12


def chord_at(t):
    for a, b, c in CHORDS:
        if a <= t < b:
            return c
    return None


GROOVE = [(0, 4), (8, 27)]  # where the band plays


def in_groove(t):
    return any(a <= t < b for a, b in GROOVE)


# ---- buses -------------------------------------------------------------------
def bus():
    return np.zeros((N, 2))


stems = {k: bus() for k in ('kick', 'snare', 'hats', 'cymbals', 'toms', 'bass', 'arp', 'pad', 'stabs', 'lead',
                            'bells', 'fx', 'boom')}
kicks = []

# ---- drums ---------------------------------------------------------------------
for bar in range(1, 15):
    t0 = T(bar)
    if not in_groove(t0):
        continue
    late = t0 >= 16
    for pos in range(16):
        t = T(bar, pos)
        if not in_groove(t):
            continue
        fill = (bar == 2 and pos >= 12) or (bar == 12 and pos >= 8) or (bar == 8 and pos >= 14)
        # Kick: four on the floor, plus a push into the next bar on odd bars.
        if pos % 4 == 0 and not (bar == 2 and pos == 12):
            place(stems['kick'], pan(kick(1.0 if pos == 0 else 0.92), 0), t)
            kicks.append(t)
        if pos == 14 and bar % 2 == 1 and not fill:
            place(stems['kick'], pan(kick(0.7), 0), t)
            kicks.append(t)
        # Snare and clap on 2 and 4, through a gated room.
        if pos in (4, 12) and not (fill and pos == 12 and bar == 2):
            s = add(snare_dry(1.0), clap(0.9))
            place(stems['snare'], pan(s, 0), t); place(stems['snare'], gated_verb(s), t)
        # Hats: 16ths, accents on the 8ths; open hats on the off-beats later on.
        if not fill:
            if late and pos % 4 == 2:
                place(stems['hats'], pan(hat(True, 0.75), 0.25), t)
            else:
                place(stems['hats'], pan(hat(False, 0.9 if pos % 2 == 0 else 0.55), 0.3 if pos % 2 else -0.15), t)
        # Fills.
        if fill and bar == 2:
            m = [50, 47, 43, 40][pos - 12]
            place(stems['toms'], pan(tom(m, 1.0), [-0.5, -0.2, 0.2, 0.5][pos - 12]), t)
        if fill and bar == 8:
            s = snare_dry(0.8)
            place(stems['snare'], pan(s, 0), t); place(stems['snare'], gated_verb(s), t)
        if fill and bar == 12:
            k = pos - 8
            s = snare_dry(0.45 + 0.08 * k) * 1.0
            place(stems['snare'], pan(s, (-1) ** k * 0.15), t); place(stems['snare'], gated_verb(s) * 0.6, t)
            if pos in (8, 12, 14):
                place(stems['toms'], pan(tom([45, 41, 38][[8, 12, 14].index(pos)], 0.9), 0), t)
for t in (0.0, 8.0, 16.0, 20.0, 24.0):
    place(stems['cymbals'], pan(crash(1.0), -0.3), t)
    place(stems['cymbals'], pan(crash(0.8), 0.35), t + 0.004)
place(stems['cymbals'], pan(crash(1.0, 3.6), 0), 28.0)
# Reverse crashes into the impact and into the final hit.
for t_end, length in ((8.0, 1.0), (28.0, 1.05)):
    c = crash(1.0, length + 0.4)[:int(length * SR)][::-1]
    place(stems['cymbals'], pan(c, 0) * 1.2, t_end - length)
# Kick on the final hit.
place(stems['kick'], pan(kick(1.0), 0), 28.0)

# ---- bass: a galloping octave line ---------------------------------------------
for i in range(int(LEN * 8)):
    t = i * 0.125
    if not in_groove(t):
        continue
    c = chord_at(t)
    if c is None:
        continue
    root = near(34, c)  # Bb1 to A2
    m = root + (12 if i % 2 else 0)
    hold = 0.105
    n = int(0.2 * SR)
    f = midi_hz(m)
    x = 0.6 * osc('saw', f, n) + 0.5 * osc('pulse', f * 1.003, n, pw=0.3)
    env = adsr(n, hold, a=0.002, d=0.09, s=0.55, r=0.03)
    cut = 300 + 2600 * expdecay(n, 0.05, 0.001) + 900 * min(1, t / 24)
    x = tvfilt(x, 'lp', cut, q=1.6) * env
    x += np.sin(2 * np.pi * f * secs(n)) * env * (0.5 if i % 2 == 0 else 0.25)  # sub weight
    place(stems['bass'], pan(x, 0), t)
# Held bass through the collapse, and the final low E.
for t, m, length in ((27.0, 38, 1.0), (28.0, 28, 3.0)):
    n = int((length + 0.3) * SR)
    f = midi_hz(m)
    x = 0.6 * osc('saw', f, n) + 0.5 * osc('saw', f * 1.004, n) + np.sin(2 * np.pi * f * secs(n))
    env = adsr(n, length, a=0.01 if t < 28 else 0.003, d=1.0, s=0.8, r=0.25)
    if t < 28:
        env *= np.linspace(0.5, 1.2, n)
    x = filt(x, 'lp', 900 if t < 28 else 1400, 0.9) * env
    place(stems['bass'], pan(x, 0), t)

# ---- arpeggio: 16ths over the chord, two octaves, filter opening over time --------
pattern = [0, 1, 2, 3, 4, 5, 4, 3]
for i in range(int(LEN * 8)):
    t = i * 0.125
    if not in_groove(t):
        continue
    c = chord_at(t)
    base = near(58, c)
    tones = [base + iv for iv in triad(c)] + [base + 12 + iv for iv in triad(c)]
    m = tones[pattern[i % 8]]
    n = int(0.3 * SR)
    x = osc('square', midi_hz(m), n) * 0.6 + osc('saw', midi_hz(m) * 2.002, n) * 0.15
    env = adsr(n, 0.09, a=0.002, d=0.08, s=0.35, r=0.06)
    bright = 1100 + 2600 * min(1, max(0, (t - 8) / 16)) + (1000 if t >= 24 else 0)
    x = tvfilt(x, 'lp', bright * (0.5 + 0.9 * expdecay(n, 0.04, 0.001)), q=2.2) * env
    place(stems['arp'], pan(x * (1.0 if i % 2 == 0 else 0.75), -0.35 if i % 2 else 0.35), t)

# ---- pad: wide supersaw chords ---------------------------------------------------
for a, b, c in CHORDS:
    if a >= 28:
        continue
    if not in_groove(a):
        continue
    root = near(46, c)
    notes = [root - 12] + [root + iv for iv in triad(c)] + [root + 12 + triad(c)[1]]
    length = b - a
    n = int((length + 0.5) * SR)
    x = sum(supersaw(midi_hz(m), n, seed=m) for m in notes) / len(notes)
    env = adsr(n, length, a=0.03, d=0.6, s=0.85, r=0.3)
    cut = 2400 if a < 24 else 4200
    x = filt(x, 'lp', cut, 0.8) * env
    st = chorus(x)
    place(stems['pad'], st, a)
# Final E major: big and long.
n = int(3.2 * SR)
x = sum(supersaw(midi_hz(m), n, seed=m) for m in (40, 52, 56, 59, 64, 68, 71)) / 7
x = filt(x, 'lp', 5200, 0.8) * adsr(n, 2.0, a=0.004, d=1.4, s=0.6, r=0.9)
place(stems['pad'], chorus(x) * 1.3, 28.0)

# ---- synth brass stabs on the chord changes ------------------------------------------
for a, b, c in CHORDS:
    if not in_groove(a) and a != 28:
        continue
    root = near(58, c)
    notes = [root + iv for iv in triad(c)] + [root + 12]
    times = [a] + ([a - 0.25] if a > 0 and a not in (8, 24, 28) else [])
    for t in times:
        length = 0.2 if a != 28 else 1.8
        n = int((length + 0.3) * SR)
        x = sum(osc('saw', midi_hz(m), n, phase=0.1 * k) + osc('saw', midi_hz(m) * 1.006, n) for k, m in enumerate(notes))
        env = adsr(n, length, a=0.006, d=0.12, s=0.6, r=0.12)
        x = tvfilt(x / len(notes), 'lp', 800 + 5200 * expdecay(n, 0.09, 0.008), q=1.1) * env
        place(stems['stabs'], chorus(x, depth=0.002), t)

# ---- lead: the hook ----------------------------------------------------------------
HOOK1 = [(0, 3, 74), (3, 1, 72), (4, 2, 74), (6, 2, 77), (8, 3, 76), (11, 1, 74), (12, 2, 72), (14, 2, 69)]
HOOK2_BB = [(0, 6, 70), (6, 2, 69), (8, 4, 65), (12, 2, 67), (14, 2, 69)]       # all Bb
HOOK2_BBC = [(0, 6, 70), (6, 2, 69), (8, 4, 67), (12, 2, 64), (14, 2, 67)]      # Bb then C
HOOK3 = [(0, 3, 72), (3, 1, 69), (4, 2, 72), (6, 2, 77), (8, 3, 76), (11, 1, 72), (12, 2, 74), (14, 2, 76)]
HOOK4 = [(0, 6, 76), (6, 2, 74), (8, 4, 72), (12, 2, 67), (14, 2, 69)]
melody = []


def bar_notes(bar, notes, shift=0):
    for pos, d, m in notes:
        melody.append((T(bar, pos), d * 0.125, m + shift))


bar_notes(1, HOOK1); bar_notes(2, HOOK2_BBC)
bar_notes(5, HOOK1); bar_notes(6, HOOK2_BB); bar_notes(7, HOOK3); bar_notes(8, HOOK4)
bar_notes(9, HOOK1); bar_notes(10, HOOK2_BBC)
bar_notes(11, HOOK1, 2); bar_notes(12, HOOK2_BBC, 2)
melody += [(24.0, 0.75, 83), (24.75, 0.25, 81), (25.0, 0.5, 79), (25.5, 0.5, 76),
           (26.0, 0.75, 86), (26.75, 0.25, 83), (27.0, 0.98, 81), (28.0, 2.2, 88)]
for t, d, m in melody:
    n = int((d + 0.35) * SR)
    tt = secs(n)
    vib = 1 + 0.006 * np.sin(2 * np.pi * 5.6 * tt) * np.clip((tt - 0.18) / 0.2, 0, 1)
    f = midi_hz(m) * vib
    x = 0.55 * osc('saw', f, n) + 0.45 * osc('saw', f * 1.005, n, phase=0.3) + 0.35 * osc('square', f * 0.5, n)
    env = adsr(n, d * 0.95, a=0.006, d=0.25, s=0.8, r=0.09 if t < 28 else 0.6)
    x = tvfilt(x, 'lp', 2400 + 2000 * expdecay(n, 0.12, 0.005) + (700 if t >= 20 else 0), q=1.3) * env
    v = 1.0 if t < 28 else 1.15
    place(stems['lead'], pan(x * v, 0.05), t)
    if 16 <= t < 28:  # the octave above, quieter, for lift
        x2 = (0.5 * osc('square', f * 2, n)) * env
        place(stems['lead'], pan(filt(x2, 'lp', 5000) * 0.28, -0.1), t)

# ---- bells on every callout --------------------------------------------------------
for k, co in enumerate(CUT['callouts']):
    t = co['t']
    c = chord_at(t) or 'Dm'
    m = 84 + PC[c] + triad(c)[2] - (12 if PC[c] + triad(c)[2] > 9 else 0)
    x = filt(add(fm_bell(m, 1.8, index=2.4) * 0.8, fm_bell(m + 12, 1.2, index=1.4) * 0.3), 'lp', 7000)
    place(stems['bells'], pan(x, -0.45 if k % 2 else 0.45), t)

# ---- fx ------------------------------------------------------------------------------
place(stems['fx'], pan(riser(1.15, 400, 9000), -0.2), 8.0 - 1.15)          # into the impact
place(stems['fx'], pan(riser(0.6, 800, 7000, seed=9), 0.3) * 0.6, 0.15)       # the lead comet whooshes in
place(stems['fx'], pan(riser(2.0, 300, 8000, seed=12), 0.1) * 0.8, 22.0)       # into the payoff
place(stems['fx'], pan(riser(1.05, 200, 11000, seed=14), 0), 28.0 - 1.05)      # the collapse
for t in (8.0, 28.0):
    place(stems['boom'], pan(sub_boom(2.4), 0), t)
place(stems['boom'], pan(sub_boom(1.2, 50, 30), 0) * 0.5, 4.0)                  # the cut to the dawn


# ---- soundfont parts ------------------------------------------------------------------
def sf_render(sf, program, notes, length=LEN, bank=0, gain=0.6):
    """notes: [(t, dur, midi, vel)] -> stereo array."""
    import fs_engine
    fs = fs_engine.FS(sf, SR, gain)
    fs.program(0, bank, program)
    ev = []
    for t, d, m, v in notes:
        ev.append((t, 1, m, v))
        ev.append((t + d, 0, m, 0))
    ev.sort(key=lambda e: (e[0], e[1]))
    out = np.zeros((int(length * SR), 2), np.float32)
    pos = 0
    for t, on, m, v in ev:
        i = min(len(out), int(t * SR))
        if i > pos:
            out[pos:i] = fs.render(i - pos)
            pos = i
        if on:
            fs.s.noteon(0, int(m), int(v))
        else:
            fs.s.noteoff(0, int(m))
    if pos < len(out):
        out[pos:] = fs.render(len(out) - pos)
    fs.s.delete()
    return out.astype(np.float64)


def orchestra(sf):
    o = {}
    # The dawn: fanfare D-A-D, a major chord; again, a minor chord; timpani answers.
    fan = []
    for t0, third in ((4.0, 66), (6.0, 65)):
        fan += [(t0, 0.48, 50, 112), (t0, 0.48, 62, 112), (t0 + 0.5, 0.48, 57, 116), (t0 + 0.5, 0.48, 69, 116),
                (t0 + 1.0, 0.3, 62, 122), (t0 + 1.0, 0.3, 74, 122)]
        fan += [(t0 + 1.25, 0.72 if t0 < 6 else 0.72, m, 124) for m in (50, 57, 62, third, 69, 74)]
    # The payoff and the final chord.
    pay = [(24.0, 0.95, m, 96) for m in (52, 59, 64, 67)] + [(25.0, 0.95, m, 96) for m in (48, 55, 60, 64)] + \
          [(26.0, 0.95, m, 100) for m in (55, 59, 62, 67)] + [(27.0, 0.98, m, 92) for m in (50, 57, 62, 66)]
    fin = [(28.0, 2.4, m, 127) for m in (40, 47, 52, 56, 59, 64, 68)]
    o['brass'] = sf_render(sf, 61, fan + pay + fin)
    o['trumpets'] = sf_render(sf, 56, [n for n in fan if n[2] >= 62] + [(28.0, 2.4, 76, 127), (28.0, 2.4, 71, 120)])
    o['horns'] = sf_render(sf, 60, [(5.25, 0.75, m, 110) for m in (54, 57, 62)] + [(7.25, 0.75, m, 115) for m in (53, 57, 62)] +
                           [(28.0, 2.4, m, 120) for m in (52, 56, 59)])
    tim = [(4.0, 0.4, 38, 127)]
    for k, t in enumerate((5.5, 5.625, 5.75, 5.875)):
        tim.append((t, 0.1, 38 if k % 2 == 0 else 33, 70 + 12 * k))
    tim.append((6.0, 0.4, 38, 127))
    roll = np.arange(7.5, 7.98, 0.0625)
    tim += [(t, 0.06, 38, int(60 + 60 * (t - 7.5) / 0.48)) for t in roll]
    tim.append((8.0, 0.5, 38, 127))
    roll2 = np.arange(27.25, 27.98, 0.0625)
    tim += [(t, 0.06, 40, int(55 + 70 * (t - 27.25) / 0.73)) for t in roll2]
    tim += [(28.0, 1.5, 40, 127), (28.0, 1.5, 35, 110)]
    o['timpani'] = sf_render(sf, 47, tim)
    o['organ'] = sf_render(sf, 19, [(4.0, 3.98, 26, 100), (4.0, 3.98, 38, 100), (28.0, 2.6, 28, 110), (28.0, 2.6, 40, 110)])
    o['strings'] = sf_render(sf, 48, [(6.0, 1.98, m, 100) for m in (50, 57, 62, 65, 69)] +
                             [(24.0, 3.98, m, 95) for m in (64, 71, 76)] + [(28.0, 2.6, m, 120) for m in (52, 59, 64, 68, 71, 76)])
    o['choir'] = sf_render(sf, 52, [(6.0, 1.98, m, 100) for m in (62, 65, 69)] + [(28.0, 2.6, m, 115) for m in (64, 68, 71)])
    o['orchhit'] = sf_render(sf, 55, [(0.0, 0.4, m, 127) for m in (62, 65, 69)] + [(8.0, 0.4, m, 127) for m in (62, 65, 69)] +
                             [(24.0, 0.4, m, 127) for m in (64, 67, 71)] + [(28.0, 0.6, m, 127) for m in (64, 68, 71)])
    return o


def swell(n, pts):
    """Gain automation through (time, gain) points."""
    ts, gs = zip(*pts)
    return np.interp(secs(n), ts, gs)[:, None]


def main():
    sf, out = sys.argv[1], sys.argv[2]
    os.makedirs(out, exist_ok=True)
    o = orchestra(sf)
    o['organ'] *= swell(N, [(0, 0.6), (4, 0.6), (7.9, 1.0), (8.0, 0), (27.9, 0), (28, 1), (31, 1)])
    o['strings'] *= swell(N, [(0, 0.3), (6, 0.3), (7.95, 1.0), (8.05, 0.0), (23.9, 0), (24, 0.7), (27.9, 1.0), (28, 1.0), (31, 1)])
    o['choir'] *= swell(N, [(0, 0.2), (6, 0.2), (7.95, 1.0), (8.05, 0), (27.9, 0), (28, 1), (31, 1)])
    stems.update(o)

    # Levels: each stem to a target loudness over the time it plays (dB RMS).
    target = {'kick': -15, 'snare': -18, 'hats': -32.5, 'cymbals': -28.5, 'toms': -20, 'bass': -17, 'arp': -24, 'pad': -22,
              'stabs': -24, 'lead': -18.5, 'bells': -26, 'fx': -25, 'boom': -17, 'brass': -18.5, 'trumpets': -23,
              'horns': -21, 'timpani': -17, 'organ': -20.5, 'strings': -24, 'choir': -25, 'orchhit': -19}
    for k, x in stems.items():
        act = np.abs(x).max(axis=1) > 1e-3
        if not act.any():
            continue
        rms = np.sqrt(np.mean(x[act] ** 2))
        stems[k] = x * 10 ** ((target[k] - 20 * np.log10(rms + 1e-12)) / 20)

    # The band builds from the drop to the payoff.
    grp = swell(N, [(0, 1.0), (4, 1.0), (8, 0.84), (12, 0.88), (16, 0.94), (20, 1.0), (24, 1.1), (27, 1.1), (28, 1.0), (31, 1.0)])
    for k in ('kick', 'snare', 'hats', 'toms', 'bass', 'arp', 'pad', 'stabs', 'lead'):
        stems[k] *= grp

    # Ducking under the kick.
    sc = sidechain(N, kicks, depth=0.5)[:, None]
    for k in ('pad', 'arp', 'stabs'):
        stems[k] *= sc
    stems['bass'] *= sidechain(N, kicks, depth=0.3, rel=0.08)[:, None]

    # Sends: one hall for everything, a ping-pong for the arp, lead and bells.
    ir = reverb_ir(2.6)
    send = {'snare': 0.08, 'arp': 0.18, 'pad': 0.22, 'stabs': 0.2, 'lead': 0.22, 'bells': 0.45, 'fx': 0.25,
            'brass': 0.38, 'trumpets': 0.35, 'horns': 0.4, 'timpani': 0.4, 'organ': 0.3, 'strings': 0.4,
            'choir': 0.45, 'orchhit': 0.3, 'toms': 0.15}
    rev_in = sum(stems[k] * v for k, v in send.items())
    wet = convolve(rev_in, ir)[:N] * 0.5
    echo = pingpong(stems['arp'] * 0.5 + stems['lead'] * 0.35 + stems['bells'] * 0.6, 0.375, fb=0.42)[:N]
    # The world collapsing: the final chord's reverb, reversed, swells into it.
    final = (stems['orchhit'] + stems['brass'] + stems['pad'])[int(28 * SR):int(29.2 * SR)]
    rv = convolve(final, ir)[:int(1.0 * SR)][::-1] * 0.35
    swellbus = np.zeros((N, 2))
    place(swellbus, rv, 28.0 - len(rv) / SR)

    mix = sum(stems.values()) + wet + echo * 0.6 + swellbus
    mix = butter(mix, 'hp', 28)
    # Fade out at the very end (the picture ends at 30 s).
    fade = np.clip((30.0 - secs(N)) / 0.6, 0, 1) ** 1.5
    mix *= fade[:, None]
    # Glue: gentle saturation.
    peak = np.abs(mix).max()
    mix = np.tanh(mix / peak * 1.4) / np.tanh(1.4) * 0.8
    mix = mix[:int(30.0 * SR)]

    with open(os.path.join(out, 'premaster.wav'), 'wb') as f:
        import struct
        d = mix.astype('<f4').tobytes()
        f.write(b'RIFF' + struct.pack('<I', 36 + len(d)) + b'WAVE')
        f.write(b'fmt ' + struct.pack('<IHHIIHH', 16, 3, 2, SR, SR * 8, 8, 32))
        f.write(b'data' + struct.pack('<I', len(d)) + d)
    np.savez_compressed(os.path.join(out, 'stems.npz'), **{k: v[:int(30 * SR)].astype(np.float32) for k, v in stems.items()})
    cues = {'bpm': 120, 'beat': 0.5, 'bar': 2.0,
            'sections': {'race': [0, 4], 'dawn': [4, 8], 'impact': 8, 'rush': [8, 24], 'key_change': 20,
                         'payoff': [24, 27], 'collapse': [27, 28], 'final_hit': 28, 'end': 30},
            'callout_bells': [c['t'] for c in CUT['callouts']], 'chords': CHORDS}
    json.dump(cues, open(os.path.join(out, 'cues.json'), 'w'), indent=1)
    for k, x in stems.items():
        print(f'{k:10s} peak {20 * np.log10(np.abs(x).max() + 1e-12):6.1f} dBFS')


if __name__ == '__main__':
    main()
