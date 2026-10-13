#!/usr/bin/env python3
"""Geopedia trailer cue ("Sweep of History") - original composition.

Writes score.mid (type-1 GM MIDI, 16 channels) and cues.json.
D major, 4/4, 100 BPM (beat = 0.6 s, bar = 2.4 s), 12 bars + ring-out = 29.6 s.

Usage: compose.py <music_out_dir>
"""
import json
import os
import random
import sys

import mido

OUTDIR = sys.argv[1]
BPM = 100
SPB = 60.0 / BPM          # seconds per beat (0.6)
TPB = 960                 # MIDI ticks per beat
DURATION = 29.6           # seconds of audio
END_BEAT = DURATION / SPB
rng = random.Random(1492)

PCS = {'C': 0, 'D': 2, 'E': 4, 'F': 5, 'G': 7, 'A': 9, 'B': 11}


def P(s):
    """'F#4' -> 66 (C4 = 60)."""
    if isinstance(s, int):
        return s
    i, acc = 1, 0
    while s[i] in '#b':
        acc += 1 if s[i] == '#' else -1
        i += 1
    return 12 * (int(s[i:]) + 1) + PCS[s[0]] + acc


def PP(txt):
    return [P(t) for t in txt.split()]


# ---------------------------------------------------------------- harmony
# (start beat, end beat, name, root pc, bass pc, chord-tone pcs)
CHORDS = [
    (0, 4, 'Dadd9', 2, 2, (2, 6, 9, 4)),     # bar 1  intro
    (4, 8, 'D', 2, 2, (2, 6, 9)),            # bar 2  journey A
    (8, 12, 'Bm', 11, 11, (11, 2, 6)),       # bar 3
    (12, 14, 'G', 7, 7, (7, 11, 2)),         # bar 4
    (14, 16, 'Em7', 4, 4, (4, 7, 11, 2)),
    (16, 18, 'Asus4', 9, 9, (9, 2, 4)),      # bar 5
    (18, 20, 'A7', 9, 9, (9, 1, 4, 7)),
    (20, 24, 'G', 7, 7, (7, 11, 2)),         # bar 6  journey B
    (24, 26, 'D/F#', 2, 6, (2, 6, 9)),       # bar 7
    (26, 28, 'Em7', 4, 4, (4, 7, 11, 2)),
    (28, 30, 'G/A', 7, 9, (7, 11, 2, 9)),    # bar 8  build (dominant pedal)
    (30, 32, 'A', 9, 9, (9, 1, 4)),
    (32, 36, 'D', 2, 2, (2, 6, 9)),          # bar 9  climax
    (36, 38, 'Bm', 11, 11, (11, 2, 6)),      # bar 10
    (38, 40, 'G', 7, 7, (7, 11, 2)),
    (40, 42, 'Bb', 10, 10, (10, 2, 5)),      # bar 11 bVI
    (42, 44, 'C', 0, 0, (0, 4, 7)),          #        bVII
    (44, END_BEAT + 1, 'D', 2, 2, (2, 6, 9)),  # bar 12 END HIT (I)
]


def chord_at(b):
    for c in CHORDS:
        if c[0] <= b < c[1]:
            return c
    return CHORDS[-1]


def in_range(pc, lo):
    """Lowest pitch with pitch-class pc that is >= lo."""
    p = lo + ((pc - lo) % 12)
    return p


def intensity(b):
    if b < 4:
        return 0.6
    if b < 12:
        return 0.80
    if b < 20:
        return 0.86
    if b < 28:
        return 0.93
    if b < 32:
        return 0.97
    return 1.0


# ---------------------------------------------------------------- parts
class Part:
    def __init__(self, name, ch, program, pan, rev=50, drums=False):
        self.name, self.ch, self.program, self.pan, self.rev, self.drums = name, ch, program, pan, rev, drums
        self.notes = []   # [beat, dur, pitch, vel]
        self.ccs = []     # (beat, cc, value)

    def add(self, beat, dur, pitch, vel, hum=0.0):
        pitch = P(pitch)
        if hum:
            beat += rng.uniform(-hum, hum)
            vel += rng.randint(-4, 4)
        beat = max(0.0, beat)
        self.notes.append([beat, dur, pitch, int(max(1, min(127, round(vel))))])

    def chord(self, beat, dur, pitches, vel, hum=0.0, spread=0.0):
        for i, p in enumerate(pitches if isinstance(pitches, (list, tuple)) else PP(pitches)):
            self.add(beat + i * spread, dur - i * spread, p, vel, hum)

    def env(self, points, step=0.125):
        """CC11 expression breakpoints [(beat, value), ...], linear ramps."""
        for (b0, v0), (b1, v1) in zip(points, points[1:]):
            n = max(1, int(round((b1 - b0) / step)))
            for i in range(n):
                t = i / n
                self.ccs.append((b0 + (b1 - b0) * t, 11, v0 + (v1 - v0) * t))
        self.ccs.append((points[-1][0], 11, points[-1][1]))

    def legato_line(self, line, vel, hum=0.012, overlap=0.06, transpose=0, vel_fn=None):
        for (b, d, p) in line:
            v = vel_fn(b) if vel_fn else vel
            self.add(b, d + overlap, P(p) + transpose, v, hum)

    def pad(self, voicings, vel_fn, hum=0.012, overlap=0.05, start_idx=0, end_beat=None):
        """Sustained chords following CHORDS; common tones are tied (not re-attacked)."""
        held = {}  # pitch -> note index
        for idx, c in enumerate(CHORDS):
            v = voicings.get(idx)
            if v is None:
                held = {}
                continue
            pitches = PP(v) if isinstance(v, str) else v
            end = c[1] if end_beat is None or idx < len(CHORDS) - 1 else end_beat
            new_held = {}
            for p in pitches:
                if p in held:
                    n = self.notes[held[p]]
                    n[1] = end - n[0] + overlap
                    new_held[p] = held[p]
                else:
                    self.add(c[0], end - c[0] + overlap, p, vel_fn(c[0]), hum)
                    new_held[p] = len(self.notes) - 1
            held = new_held

    def finalize(self):
        """No overlapping notes of the same pitch on one channel (clean MIDI)."""
        self.notes.sort(key=lambda n: (n[0], n[2]))
        last = {}
        for n in self.notes:
            p = n[2]
            if p in last:
                prev = last[p]
                if prev[0] + prev[1] > n[0] - 0.002:
                    prev[1] = max(0.02, n[0] - prev[0] - 0.002)
            last[p] = n
        for n in self.notes:
            if n[0] + n[1] > END_BEAT - 0.7:
                n[1] = max(0.05, END_BEAT - 0.7 - n[0])


parts = {}


def part(*a, **k):
    p = Part(*a, **k)
    parts[p.ch] = p
    return p


vio = part('Violins (Strings Fast)', 0, 48, pan=40, rev=45)
pad = part('Strings pad (Strings Slow)', 1, 49, pan=74, rev=55)
trem = part('High strings tremolo', 2, 44, pan=50, rev=65)
cel = part('Cellos ostinato', 3, 42, pan=84, rev=35)
cb = part('Contrabasses', 4, 43, pan=92, rev=35)
hrn = part('French Horns', 5, 60, pan=46, rev=70)
tbn = part('Trombones', 6, 57, pan=82, rev=60)
tpt = part('Trumpets', 7, 56, pan=76, rev=60)
tba = part('Tuba', 8, 58, pan=88, rev=55)
drm = part('Orchestral percussion (GM2/GS Orchestra Kit)', 9, 48, pan=64, rev=60, drums=True)
aah = part('Choir Aahs', 10, 52, pan=64, rev=80)
ooh = part('Choir Oohs', 11, 53, pan=64, rev=80)
hrp = part('Harp', 12, 46, pan=30, rev=60)
cele = part('Celesta', 13, 8, pan=96, rev=80)
tmp = part('Timpani', 14, 47, pan=64, rev=60)
vla = part('Violas ostinato', 15, 41, pan=72, rev=40)

# ---------------------------------------------------------------- melody (original)
MEL_A = [  # bars 2-5, horns
    (4, 1.5, 'D4'), (5.5, .5, 'E4'), (6, 1, 'F#4'), (7, 1, 'A4'),
    (8, 2, 'B4'), (10, 1, 'A4'), (11, 1, 'F#4'),
    (12, 1.5, 'G4'), (13.5, .5, 'F#4'), (14, 1, 'E4'), (15, 1, 'D4'),
    (16, 1.5, 'E4'), (17.5, .5, 'F#4'), (18, 1, 'G4'), (19, 1, 'A4'),
]
MEL_B = [  # bars 6-8, horns + violins
    (20, 1.5, 'B4'), (21.5, .5, 'C#5'), (22, 1, 'D5'), (23, 1, 'E5'),
    (24, 1.5, 'F#5'), (25.5, .5, 'E5'), (26, 2, 'D5'),
    (28, 3, 'A4'), (31, .5, 'B4'), (31.5, .5, 'C#5'),
]
MEL_C = [  # bars 9-10 climax (violins at this pitch, horns 8vb, trombones 15mb)
    (32, 1.5, 'D5'), (33.5, .5, 'E5'), (34, 1, 'F#5'), (35, 1, 'A5'),
    (36, 2, 'B5'), (38, 1, 'A5'), (39, 1, 'G5'),
]
CAD_TOP = [(40, 2, 'F5'), (42, 2, 'G5')]   # bar 11 bVI - bVII, top line
CAD_MID = [(40, 2, 'D5'), (42, 2, 'E5')]   # parallel thirds below


def vel_curve(base):
    return lambda b: base * intensity(b) / 0.93 if b < 32 else base


# Horns -------------------------------------------------------------------
hrn.legato_line(MEL_A, 0, vel_fn=lambda b: 98 + (6 if (b % 4) == 0 else 0))
hrn.legato_line(MEL_B, 0, vel_fn=lambda b: 104 + (6 if (b % 4) == 0 else 0) + (8 if b >= 28 else 0))
hrn.legato_line(MEL_C, 0, transpose=-12, vel_fn=lambda b: 116 + (8 if (b % 4) == 0 else 0))
hrn.legato_line(CAD_TOP, 120, transpose=-12)
hrn.legato_line(CAD_MID, 112, transpose=-12)
hrn.chord(44, 3.6, 'D4 F#4 A4', 127, hum=0.004)
hrn.env([(0, 100), (4, 98), (8, 106), (10, 100), (12, 98), (16, 104), (19.5, 108), (20, 104), (24, 110), (26, 112),
         (28, 104), (31.8, 122), (32, 120), (36, 127), (38, 122), (40, 120), (43.8, 127), (44.2, 127), (45.0, 104), (46.0, 80), (47.6, 46)])

# Violins -------------------------------------------------------------------
vio.legato_line(MEL_B, 0, vel_fn=lambda b: 90 + (6 if (b % 4) == 0 else 0))
vio.legato_line(MEL_C, 0, vel_fn=lambda b: 112 + (8 if (b % 4) == 0 else 0))
vio.legato_line(MEL_C, 0, transpose=-12, vel_fn=lambda b: 100)
vio.legato_line(CAD_TOP, 120)
vio.legato_line(CAD_MID, 110)
vio.chord(44, 4.6, 'D5 F#5 A5 D6', 116, hum=0.004)
vio.env([(0, 90), (20, 84), (24, 98), (28, 100), (31.8, 120), (32, 122), (35, 120), (36, 127), (38, 122), (40, 120),
         (43.8, 127), (44.2, 124), (45.0, 104), (46.5, 80), (48.6, 34)])

# String pad (Strings Slow) ------------------------------------------------------
PAD_V = {1: 'F#3 A3 D4', 2: 'F#3 B3 D4', 3: 'G3 B3 D4', 4: 'G3 B3 E4', 5: 'A3 D4 E4', 6: 'G3 C#4 E4',
         7: 'G3 B3 D4', 8: 'F#3 A3 D4', 9: 'G3 B3 E4', 10: 'G3 B3 D4', 11: 'A3 C#4 E4',
         12: 'D3 F#3 A3 D4', 13: 'D3 F#3 B3 D4', 14: 'D3 G3 B3 D4', 15: 'D3 F3 Bb3 D4', 16: 'E3 G3 C4 E4',
         17: 'D3 F#3 A3 D4 F#4 A4'}
pad.pad(PAD_V, lambda b: 112 if b >= 44 else (100 if b >= 32 else 84), end_beat=48.6)
pad.env([(0, 80), (4, 78), (8, 86), (10, 82), (12, 86), (16, 88), (19.5, 94), (20, 90), (24, 98), (28, 100),
         (31.8, 114), (32, 112), (36, 116), (40, 112), (43.8, 124), (44, 124), (45, 112), (46.5, 86), (48.6, 34)])

# High tremolo -------------------------------------------------------------------
TREM_V = {0: 'A4 D5 E5 F#5', 1: 'F#5 A5', 2: 'F#5 B5', 3: 'G5 B5', 4: 'G5 B5', 5: 'E5 A5', 6: 'E5 A5',
          7: 'G5 B5', 8: 'F#5 A5', 9: 'G5 B5', 10: 'G5 B5', 11: 'E5 A5',
          12: 'A5 D6', 13: 'B5 D6', 14: 'B5 D6', 15: 'Bb5 D6', 16: 'C6 E6', 17: 'A5 D6 F#6'}
trem.pad(TREM_V, lambda b: 70 if b < 4 else (78 if b < 32 else 92), end_beat=48.6)
trem.env([(0, 40), (3.8, 104), (4.3, 76), (6, 56), (19, 60), (20, 60), (28, 70), (31.8, 90), (32, 60),
          (43.6, 66), (44, 92), (45, 92), (48.6, 34)])

# Choir oohs -------------------------------------------------------------------
OOH_V = dict(PAD_V)
OOH_V[0] = 'A3 D4 F#4 A4'
OOH_V[17] = 'A3 D4 F#4 A4'
ooh.pad(OOH_V, lambda b: 64 if b < 4 else (72 if b < 32 else 90), end_beat=48.6)
ooh.env([(0, 36), (3.8, 90), (4, 86), (8, 76), (20, 70), (32, 74), (44, 90), (45, 88), (48.6, 30)])

# Choir aahs -------------------------------------------------------------------
AAH_V = {7: 'B3 D4 G4', 8: 'A3 D4 F#4', 9: 'B3 D4 G4', 10: 'B3 D4 G4', 11: 'A3 C#4 E4',
         12: 'D3 A3 F#4 D5', 13: 'B2 B3 F#4 D5', 14: 'D3 B3 G4 D5', 15: 'D3 Bb3 F4 D5', 16: 'E3 C4 G4 E5',
         17: 'D3 A3 D4 F#4 A4 D5'}
aah.pad(AAH_V, lambda b: 118 if b >= 44 else (108 if b >= 32 else 86), end_beat=48.6)
aah.env([(0, 60), (20, 55), (24, 72), (28, 80), (31.8, 108), (32, 108), (36, 114), (40, 114), (43.8, 124),
         (44, 124), (45, 112), (46.5, 88), (48.6, 32)])

# Ostinato (cellos + violas), 3+3+2 accents -----------------------------------
OST_VEL = [112, 64, 74, 98, 64, 74, 100, 72]
OST_OCT = [0, 0, 12, 0, 0, 12, 0, 12]
for bar in range(2, 12):            # bars 2..11
    b0 = (bar - 1) * 4
    for i in range(8):
        b = b0 + i * 0.5
        c = chord_at(b)
        base = in_range(c[4], 38)    # bass pc in D2..C#3
        sc = 0.92 if bar < 6 else (0.97 if bar < 9 else 1.06)
        v = OST_VEL[i] * sc
        d = 0.5 if i in (0, 3, 6) else 0.40
        cel.add(b, d, base + OST_OCT[i], v, hum=0.006)
        if bar >= 6 and not (bar == 8 and i >= 6):
            # violas: chord root / fifth one octave up, same rhythm
            root = in_range(c[3], 50)          # D3..C#4
            fifth = root + 7
            vp = [root, root, fifth, root, root, fifth, root, fifth][i]
            vla.add(b, d, vp, v * 0.92, hum=0.006)
# bar 8 beat 4: viola scale run into the climax (A3 -> C#5)
for k, p in enumerate(PP('A3 B3 C#4 D4 E4 F#4 G4 A4 B4 C#5')):
    vla.add(31 + k * 0.1, 0.12, p, 70 + k * 5)
cel.chord(44, 4.4, 'D2 D3', 112)
vla.chord(44, 4.4, 'D3 A3 D4', 104)
cel.env([(0, 100), (4, 100), (12, 104), (20, 108), (28, 108), (31.8, 122), (32, 124), (43.9, 127), (44, 118), (45, 96), (46.5, 72), (48.6, 34)])
vla.env([(0, 95), (20, 100), (28, 104), (31.8, 120), (32, 122), (43.9, 127), (44, 116), (45, 94), (46.5, 70), (48.6, 34)])

# Contrabasses: low pedal in the intro, then 3+3+2 pulse on the bass note --------------
cb.add(0, 4.05, 'D1', 64)
for bar in range(2, 12):
    b0 = (bar - 1) * 4
    for off, d, v in ((0, 1.4, 112), (1.5, 1.4, 92), (3.0, 0.95, 96)):
        b = b0 + off
        c = chord_at(b)
        sc = 0.86 if bar < 6 else (0.95 if bar < 9 else 1.06)
        cb.add(b, d, in_range(c[4], 26), v * sc, hum=0.004)
cb.chord(44, 4.4, 'D1 D2', 127)
cb.env([(0, 56), (3.9, 100), (4, 104), (20, 108), (28, 108), (31.8, 124), (32, 124), (44, 127), (45, 116), (46.5, 90), (48.6, 40)])

# Trombones -----------------------------------------------------------------
TBN_B = [(24, 2, 'F#2 A2 D3'), (26, 2, 'E2 B2 G3'), (28, 2, 'A2 G3 B3'), (30, 2, 'A2 E3 C#4')]
for b, d, ch in TBN_B:
    tbn.chord(b, d + 0.05, ch, 78 + (b - 24) * 3, hum=0.008)
# trombones skip the A passing note of bar 10 (avoids a low G-A-B cluster against the pad)
TBN_C = [n for n in MEL_C if n[0] < 36] + [(36, 3, 'B5'), (39, 1, 'G5')]
tbn.legato_line(TBN_C, 0, transpose=-24, vel_fn=lambda b: 112 + (8 if (b % 4) == 0 else 0))
tbn.chord(40, 2.05, 'Bb2 F3 Bb3', 118, hum=0.006)
tbn.chord(42, 2.0, 'C3 G3 C4', 122, hum=0.006)
tbn.chord(44, 3.4, 'D2 A2 D3 A3', 127, hum=0.004)
tbn.env([(0, 70), (24, 70), (28, 86), (31.8, 116), (32, 118), (43.8, 127), (44.3, 120), (45.2, 90), (46.5, 60), (47.6, 40)])

# Trumpets (climax only) --------------------------------------------------------
for b, d, ch, v in [(32, 2, 'F#4 A4', 108), (34, 2, 'A4 D5', 112), (36, 2, 'B4 D5', 114), (38, 2, 'B4 D5', 106),
                    (40, 2, 'Bb4 D5', 116), (42, 2, 'C5 E5', 122), (44, 2.6, 'A4 D5 F#5', 127)]:
    tpt.chord(b, d, ch, v, hum=0.006)
tpt.env([(0, 110), (32, 112), (36, 116), (40, 114), (43.8, 127), (44.3, 118), (45.2, 84), (46.6, 50)])

# Tuba -------------------------------------------------------------------
for b, d, p, v in [(28, 4, 'A1', 88), (32, 4, 'D2', 116), (36, 2, 'B1', 112), (38, 2, 'G1', 112),
                   (40, 2, 'Bb1', 118), (42, 2, 'C2', 122), (44, 3.4, 'D2', 127)]:
    tba.add(b, d + 0.04, p, v, hum=0.004)
tba.env([(0, 100), (28, 86), (31.8, 118), (32, 116), (44, 127), (45, 112), (47.6, 54)])

# Harp -------------------------------------------------------------------
def harp_arp(b0, b1, step, start_lo, up_n, vel, accent=10, updown=False):
    p_prev = None
    seq_dir = 1
    count = 0
    b = b0
    while b < b1 - 1e-6:
        c = chord_at(b)
        tones = c[5]
        if count == 0:
            p = in_range(c[4], start_lo)
        else:
            if seq_dir > 0:
                p = p_prev + 1
                while p % 12 not in tones:
                    p += 1
            else:
                p = p_prev - 1
                while p % 12 not in tones:
                    p -= 1
        v = vel + (accent if abs((b % 4)) < 1e-6 else (accent / 2 if abs(b % 2) < 1e-6 else 0))
        hrp.add(b, min(step * 3.0, c[1] - b + 0.08), p, v, hum=0.004)
        p_prev = p
        count += 1
        if updown and count % up_n == 0:
            seq_dir = -seq_dir
        if not updown and count % up_n == 0:
            count = 0
        b += step


for bar in range(2, 6):      # 8ths, one rising sweep per bar
    harp_arp((bar - 1) * 4, bar * 4, 0.5, 50, 8, 82)
for nn in list(hrp.notes):   # celesta sparkle: top half of each rising harp sweep, 8va
    if 4 <= nn[0] < 20 and (nn[0] % 4) >= 2:
        cele.add(nn[0], 0.9, nn[2] + 12, 44 + (nn[0] % 4 - 2) * 4)
for bar in range(6, 9):      # 16ths, up-down
    end = bar * 4 if bar < 8 else 31
    harp_arp((bar - 1) * 4, end, 0.25, 50, 8, 80, updown=True)
for k, p in enumerate(PP('D4 E4 F#4 G4 A4 B4 C#5 D5 E5 F#5 G5 A5 B5 C#6')):   # glissando into bar 9
    hrp.add(31 + k * (1.0 / 14), min(0.6, 32.04 - (31 + k * (1.0 / 14))), p, 70 + k * 2)
for bar in range(9, 12):     # climax 16ths
    harp_arp((bar - 1) * 4, bar * 4, 0.25, 50, 8, 88, updown=True)
for k, p in enumerate(PP('D2 A2 D3 F#3 A3 D4 F#4 A4 D5 F#5 A5 D6')):   # rolled final chord
    hrp.add(44 + k * 0.03, 4.4 - k * 0.03, p, 108 - k * 2)
for k, p in enumerate(PP('D5 F#5 A5 D6 F#6')):
    hrp.add(46 + k * 0.5, 2.2, p, 52 - k * 3)
hrp.env([(0, 120), (44, 120), (48.6, 96)])

# Celesta -------------------------------------------------------------------
for k, p in enumerate(PP('A5 D6 E6 F#6 A6 F#6 E6 D6')):
    cele.add(k * 0.5, 1.2, p, 46 + k * 4, hum=0.006)
for b, p in [(4, 'F#6'), (12, 'D6'), (20, 'B6'), (24, 'A6')]:
    cele.add(b, 1.5, p, 66)
cele.chord(44, 3.0, 'D6 A6', 86)
for k, p in enumerate(PP('D6 F#6 A6 D7 F#7')):
    cele.add(45 + k * 0.5, 1.6, p, 62 - k * 3)
cele.env([(0, 127)])

# Timpani -------------------------------------------------------------------
TIMP = {'Dadd9': 'D2', 'D': 'D2', 'Bm': 'B2', 'G': 'G2', 'Em7': 'E2', 'Asus4': 'A2', 'A7': 'A2',
        'D/F#': 'F#2', 'G/A': 'A2', 'A': 'A2', 'Bb': 'Bb2', 'C': 'C3'}


def roll(p, key, b0, b1, v0, v1, step=0.125, curve=1.6):
    n = int(round((b1 - b0) / step))
    for i in range(n):
        t = i / max(1, n - 1)
        p.add(b0 + i * step, step * 0.85, key, v0 + (v1 - v0) * (t ** curve) + rng.uniform(-4, 4))


roll(tmp, 'D2', 2.0, 4.0, 16, 62)
for bar in range(2, 12):
    b0 = (bar - 1) * 4
    if bar == 8:
        tmp.add(b0, 1.0, 'A2', 104)
        roll(tmp, 'A2', 29.0, 32.0, 34, 104, curve=1.4)
        continue
    hits = [(0, 96)]
    if bar >= 4:
        hits += [(2, 70)]
    if bar >= 6:
        hits = [(0, 106), (1.5, 78), (2, 88), (3, 80)]
    if bar >= 9:
        hits = [(0, 118), (1.5, 90), (2, 104), (3, 96)]
    if bar == 11:
        hits = [(0, 118), (1.5, 90), (2, 106)]
    for off, v in hits:
        c = chord_at(b0 + off)
        tmp.add(b0 + off, min(2.0 if off == 0 else 1.0, c[1] - (b0 + off) + 0.05), TIMP[c[2]], v)
for b, p, v in [(43.0, 'C3', 100), (43.25, 'C3', 96), (43.5, 'A2', 106), (43.75, 'A2', 114)]:
    tmp.add(b, 0.22, p, v)
tmp.add(44, 4.4, 'D2', 127)       # END HIT
tmp.add(44, 4.4, 'D3', 110)
tmp.env([(0, 94), (43.9, 96), (44, 127)])

# Orchestra-kit percussion ----------------------------------------------------
BD, SN, CR1, CR2, SPL, TRI, BELLTREE, TAIKO_S, TAIKO_L = 36, 38, 57, 59, 55, 81, 84, 86, 87
roll(drm, CR1, 2.5, 4.0, 8, 44)
for bar in range(2, 12):
    b0 = (bar - 1) * 4
    if bar < 6:
        drm.add(b0, 3.0, TAIKO_L, 96)
        drm.add(b0, 3.0, BD, 76)
        drm.add(b0 + 1.5, 1.0, TAIKO_S, 64)
        drm.add(b0 + 3.0, 1.0, TAIKO_S, 70)
        if bar in (2, 4):
            drm.add(b0, 3.5, TRI, 62)
    elif bar < 8:
        drm.add(b0, 3.0, TAIKO_L, 102)
        drm.add(b0, 2.0, BD, 86)
        drm.add(b0 + 2.0, 1.5, BD, 60)
        drm.add(b0 + 1.5, 1.0, TAIKO_S, 76)
        drm.add(b0 + 3.0, 0.5, TAIKO_S, 80)
        drm.add(b0 + 3.5, 0.5, TAIKO_S, 62)
        drm.add(b0 + 1.5, 0.5, SN, 46)
        drm.add(b0 + 3.0, 0.5, SN, 54)
        drm.add(b0 + 3.75, 0.25, SN, 40)
        if bar == 6:
            drm.add(b0, 3.5, SPL, 64)
    elif bar == 8:
        drm.add(b0, 3.0, TAIKO_L, 104)
        drm.add(b0, 2.0, BD, 90)
        roll(drm, SN, 29.0, 31.0, 24, 96, curve=1.3)
        roll(drm, CR2, 29.0, 32.0, 12, 84, curve=1.8)
        for k in range(4):
            drm.add(31 + k * 0.25, 0.25, TAIKO_S, 84 + k * 9)
            drm.add(31 + k * 0.25, 0.2, SN, 92 + k * 8)
    else:
        drm.add(b0, 3.0, TAIKO_L, 118)
        drm.add(b0, 2.0, BD, 118)
        drm.add(b0 + 2.0, 1.5, BD, 100)
        drm.add(b0 + 1.5, 1.0, TAIKO_S, 96)
        drm.add(b0 + 3.0, 0.5, TAIKO_S, 100)
        drm.add(b0 + 1.5, 0.5, SN, 80)
        drm.add(b0 + 3.0, 0.5, SN, 86)
        if bar < 11:
            drm.add(b0 + 3.5, 0.5, TAIKO_S, 84)
drm.add(32, 4.0, CR1, 116)
drm.add(32, 4.0, CR2, 104)
drm.add(40, 3.0, CR1, 92)
for k in range(4):
    drm.add(43 + k * 0.25, 0.22, SN, 86 + k * 10)
    drm.add(43 + k * 0.25 + 0.0, 0.22, TAIKO_S, 92 + k * 9) if k >= 2 else None
# END HIT
drm.add(44, 4.4, 35, 127)
drm.add(44, 4.4, BD, 127)
drm.add(44, 4.4, TAIKO_L, 127)
drm.add(44, 4.4, CR1, 122)
drm.add(44, 4.4, CR2, 114)
drm.add(44.5, 3.9, BELLTREE, 60)
# light shaker: 8ths in bars 4-5, 16ths in bars 6-11 (energy builds every few bars)
SHAKER = 82
for bar in range(4, 12):
    b0 = (bar - 1) * 4
    sub = 0.5 if bar < 6 else 0.25
    lift = 0 if bar < 6 else (8 if bar < 9 else 14)
    for i in range(int(4 / sub)):
        b = b0 + i * sub
        if bar == 8 and b >= 31:
            break
        acc = 34 if abs(b % 1) < 1e-6 else (26 if abs(b % 0.5) < 1e-6 else 20)
        drm.add(b, sub * 0.9, SHAKER, acc + lift + rng.randint(-3, 3))
drm.env([(0, 92), (43.9, 92), (44, 127)])

# ---------------------------------------------------------------- pre-hit breath
# Sustained parts release at beat 43.6 so the endHit (beat 44 = 26.4 s) lands after a short gap;
# the low strings push 16ths on C with the timpani/snare fill.
for p in (vio, pad, trem, aah, ooh, hrn, tbn, tpt, tba, cb):
    for nn in p.notes:
        if nn[0] < 43.6 < nn[0] + nn[1]:
            nn[1] = 43.6 - nn[0]
for p, key, base_v in ((cel, 'C3', 92), (vla, 'C4', 84), (cb, 'C2', 92)):
    p.notes = [nn for nn in p.notes if not (43.0 <= nn[0] < 44.0)]
    for k in range(4):
        p.add(43 + k * 0.25, 0.2, key, base_v + k * 10)


# ---------------------------------------------------------------- harmony check
def check():
    issues = []
    pitched = [p for p in parts.values() if not p.drums and p.ch != 14]
    t = 4.0
    while t < 48:
        c = chord_at(t + 0.01)
        sounding = []
        for p in pitched:
            for (b, d, k, v) in p.notes:
                if b <= t + 0.01 < b + d - 0.08:
                    sounding.append((p.name, k, b, d))
        for name, k, b, d in sounding:
            if k % 12 not in c[5] and d >= 0.75 and abs(b - t) < 0.02:
                issues.append(f"beat {t:5.2f} {c[2]:6s} non-chord {k} ({name}, dur {d:.2f})")
        t += 0.25
    return issues


# ---------------------------------------------------------------- write MIDI
def write_midi(path):
    mid = mido.MidiFile(type=1, ticks_per_beat=TPB)
    cond = mido.MidiTrack()
    mid.tracks.append(cond)
    cond.append(mido.MetaMessage('track_name', name='Geopedia trailer - Sweep of History (original)', time=0))
    cond.append(mido.MetaMessage('copyright', text='Original composition for Geopedia, 2026', time=0))
    cond.append(mido.MetaMessage('time_signature', numerator=4, denominator=4, time=0))
    cond.append(mido.MetaMessage('key_signature', key='D', time=0))
    cond.append(mido.MetaMessage('set_tempo', tempo=mido.bpm2tempo(BPM), time=0))
    marks = [(0, 'intro'), (4, 'journey'), (20, 'journey B (build)'), (32, 'climax'), (44, 'endHit / end card')]
    last = 0
    for b, txt in marks:
        tk = int(round(b * TPB))
        cond.append(mido.MetaMessage('marker', text=txt, time=tk - last))
        last = tk
    tk = int(round(END_BEAT * TPB))
    cond.append(mido.MetaMessage('end_of_track', time=tk - last))

    for ch in sorted(parts):
        p = parts[ch]
        p.finalize()
        tr = mido.MidiTrack()
        mid.tracks.append(tr)
        ev = []
        ev.append((0, 0, mido.MetaMessage('track_name', name=p.name)))
        if not p.drums:
            ev.append((0, 1, mido.Message('control_change', channel=ch, control=0, value=0)))
        ev.append((0, 2, mido.Message('program_change', channel=ch, program=p.program)))
        ev.append((0, 3, mido.Message('control_change', channel=ch, control=7, value=100)))
        ev.append((0, 3, mido.Message('control_change', channel=ch, control=10, value=p.pan)))
        ev.append((0, 3, mido.Message('control_change', channel=ch, control=91, value=p.rev)))
        lastcc = None
        for (b, num, val) in sorted(p.ccs, key=lambda x: x[0]):
            val = int(round(max(0, min(127, val))))
            if (num, val) == lastcc:
                continue
            lastcc = (num, val)
            ev.append((int(round(b * TPB)), 4, mido.Message('control_change', channel=ch, control=num, value=val)))
        for (b, d, k, v) in p.notes:
            on = int(round(b * TPB))
            off = max(on + 1, int(round((b + d) * TPB)))
            ev.append((on, 6, mido.Message('note_on', channel=ch, note=k, velocity=v)))
            ev.append((off, 5, mido.Message('note_off', channel=ch, note=k, velocity=0)))
        ev.sort(key=lambda e: (e[0], e[1]))
        last = 0
        for tk, _, msg in ev:
            tr.append(msg.copy(time=tk - last))
            last = tk
        tr.append(mido.MetaMessage('end_of_track', time=0))
    mid.save(path)


# ---------------------------------------------------------------- cues
def write_cues(path):
    beats = []
    i = 0
    while i * SPB < DURATION - 1e-9:
        beats.append({'t': round(i * SPB, 4), 'bar': i // 4 + 1, 'beat': i % 4 + 1})
        i += 1
    bars = [{'bar': b['bar'], 't': b['t']} for b in beats if b['beat'] == 1]
    sections = [
        {'name': 'intro', 'start': 0.0, 'end': 2.4, 'bars': '1',
         'desc': 'soft shimmer: high string tremolo, celesta, choir oohs, low D pedal; swells into bar 2'},
        {'name': 'journey', 'start': 2.4, 'end': 19.2, 'bars': '2-8',
         'desc': 'pulse (cello/viola/bass ostinato, taiko, timpani) + horn melody; strong downbeat on every bar'},
        {'name': 'climax', 'start': 19.2, 'end': 26.4, 'bars': '9-11',
         'desc': 'full orchestra + choir, crash at 19.2, bVI-bVII cadence in bar 11 (24.0-26.4)'},
        {'name': 'endCard', 'start': 26.4, 'end': DURATION, 'bars': '12-13',
         'desc': 'endHit (timpani + bass drum + crash + full D major chord), chord rings out and fades'},
    ]
    markers = [
        {'name': 'journeyStart', 't': 2.4, 'note': 'bar 2: pulse (ostinato, taiko, timpani) + horn melody enter'},
        {'name': 'journeyLayer2', 't': 7.2, 'note': 'bar 4: shaker and off-beat timpani join'},
        {'name': 'journeyBuild', 't': 12.0, 'note': 'bar 6: phrase 2 - violins, violas, choir aahs, snare, splash'},
        {'name': 'riser', 't': 16.8, 'note': 'bar 8: dominant build, timpani/snare/cymbal rolls, run into climax'},
        {'name': 'climaxHit', 't': 19.2, 'note': 'bar 9 downbeat: crash + full orchestra + choir'},
        {'name': 'finalCadence', 't': 24.0, 'note': 'bar 11: Bb -> C (bVI-bVII), drum fill from 25.8'},
        {'name': 'preHitGap', 't': 26.16, 'note': 'sustained parts release; only the drum/low-string fill plays'},
        {'name': 'endHit', 't': 26.4, 'note': 'bar 12 downbeat: the one big hit (timpani, bass drum, taiko, crash, full D major)'},
        {'name': 'fadeStart', 't': 28.6, 'note': 'final 1.0 s fade of the ringing chord'},
        {'name': 'musicEnd', 't': DURATION},
    ]
    hits = [round((bar - 1) * 4 * SPB, 4) for bar in range(2, 13)]
    cues = {
        'file': 'music.wav / music.m4a',
        'tempoBpm': BPM, 'timeSignature': '4/4', 'beatSec': SPB, 'barSec': 4 * SPB,
        'durationSec': DURATION, 'sampleRate': 48000, 'key': 'D major',
        'endHit': 26.4,
        'sections': sections,
        'markers': markers,
        'downbeatAccents': hits,
        'beatTimes': [b['t'] for b in beats],
        'barTimes': [b['t'] for b in bars],
        'bars': bars,
        'beats': beats,
        'notes': ('All times in seconds from the first sample of music.wav. Fixed tempo: beat n is at n*0.6 s. '
                  'Every downbeat from 2.4 s to 24.0 s carries a timpani/taiko/ostinato accent; '
                  '19.2 s (crash) and 26.4 s (endHit) are the two biggest hits. '
                  'Bar 13 (28.8 s) is only the ring-out tail.'),
    }
    with open(path, 'w') as f:
        json.dump(cues, f, indent=1)


if __name__ == '__main__':
    os.makedirs(OUTDIR, exist_ok=True)
    for p in parts.values():
        p.finalize()
    for line in check():
        print('HARMONY:', line)
    write_midi(os.path.join(OUTDIR, 'score.mid'))
    write_cues(os.path.join(OUTDIR, 'cues.json'))
    n = sum(len(p.notes) for p in parts.values())
    print(f'wrote score.mid ({n} notes, {len(parts)} parts) and cues.json')
