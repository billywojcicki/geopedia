#!/usr/bin/env python3
"""Mix the rendered stems: expression (CC11), dynamic brightness, EQ, balance,
convolution hall reverb, stereo width, master EQ + glue compression.

Usage: mix.py <stems_raw.npz> <score.mid> <render_stems.py> <out_premaster.wav> <analysis_dir>
"""
import importlib.util
import os
import sys
import wave

import mido
import numpy as np
from scipy import ndimage, signal

SR = 48000
DURATION = 29.6
N = int(round(DURATION * SR))
SECTIONS = [('intro', 0.0, 2.4), ('journeyA', 2.4, 12.0), ('journeyB', 12.0, 19.2),
            ('climax', 19.2, 26.4), ('end', 26.4, 29.6)]

# name: (reference section, target K-weighted level dB (relative), reverb send, bright dB, eq list)
# eq items: ('hp', f) ('lp', f) ('pk', f, gain, q) ('ls', f, gain) ('hs', f, gain)
MIX = {
    'violins':     ('climax', -1.0, 0.30, 4, [('hp', 160), ('pk', 420, -1.5, 1.0), ('pk', 3000, -1.5, 1.4), ('hs', 9000, 1.0)]),
    'strings_pad': ('climax', -7.0, 0.36, 3, [('hp', 100), ('pk', 300, -2.5, 0.8), ('lp', 12000)]),
    'tremolo':     ('intro', -15.0, 0.50, 0, [('hp', 400), ('hs', 8000, 1.5)]),
    'cellos':      ('climax', -6.0, 0.18, 0, [('hp', 40), ('pk', 250, -1.0, 1.0), ('pk', 2500, -1.5, 1.2)]),
    'violas':      ('climax', -9.0, 0.22, 0, [('hp', 90), ('pk', 400, -1.5, 1.0)]),
    'basses':      ('climax', -8.0, 0.12, 0, [('hp', 30), ('lp', 3000)]),
    'horns':       ('climax', -2.0, 0.45, 3, [('hp', 70), ('pk', 350, -1.5, 0.9), ('lp', 9000)]),
    'trombones':   ('climax', -5.0, 0.32, 3, [('hp', 50), ('pk', 300, -1.5, 0.9), ('lp', 10000)]),
    'trumpets':    ('climax', -8.0, 0.32, 3, [('hp', 150), ('pk', 3500, -2.0, 1.2), ('lp', 11000)]),
    'tuba':        ('climax', -10.0, 0.20, 0, [('hp', 30), ('lp', 2500)]),
    'percussion':  ('climax', -9.0, 0.30, 0, [('hp', 30), ('ls', 80, 1.0)]),
    'choir_aahs':  ('climax', -5.0, 0.50, 3, [('hp', 120), ('pk', 350, -2.0, 0.9), ('hs', 8000, 2.0)]),
    'choir_oohs':  ('climax', -12.0, 0.50, 0, [('hp', 150), ('pk', 300, -2.0, 0.9)]),
    'harp':        ('climax', -12.0, 0.38, 0, [('hp', 80), ('hs', 6000, 1.0)]),
    'celesta':     ('intro', -15.0, 0.55, 0, [('hp', 300)]),
    'timpani':     ('climax', -8.0, 0.30, 0, [('hp', 30), ('pk', 120, 1.5, 1.0)]),
}


# ---------------------------------------------------------------- DSP helpers
def biquad(kind, f, gain=0.0, q=0.707):
    A = 10 ** (gain / 40.0)
    w0 = 2 * np.pi * f / SR
    cw, sw = np.cos(w0), np.sin(w0)
    if kind == 'pk':
        alpha = sw / (2 * q)
        b = [1 + alpha * A, -2 * cw, 1 - alpha * A]
        a = [1 + alpha / A, -2 * cw, 1 - alpha / A]
    elif kind in ('ls', 'hs'):
        alpha = sw / 2 * np.sqrt(2)
        sA = 2 * np.sqrt(A) * alpha
        if kind == 'ls':
            b = [A * ((A + 1) - (A - 1) * cw + sA), 2 * A * ((A - 1) - (A + 1) * cw), A * ((A + 1) - (A - 1) * cw - sA)]
            a = [(A + 1) + (A - 1) * cw + sA, -2 * ((A - 1) + (A + 1) * cw), (A + 1) + (A - 1) * cw - sA]
        else:
            b = [A * ((A + 1) + (A - 1) * cw + sA), -2 * A * ((A - 1) + (A + 1) * cw), A * ((A + 1) + (A - 1) * cw - sA)]
            a = [(A + 1) - (A - 1) * cw + sA, 2 * ((A - 1) - (A + 1) * cw), (A + 1) - (A - 1) * cw - sA]
    else:
        raise ValueError(kind)
    b, a = np.array(b) / a[0], np.array(a) / a[0]
    return signal.tf2sos(b, a)


def apply_eq(x, eq):
    for item in eq:
        if item[0] == 'hp':
            sos = signal.butter(2, item[1], 'highpass', fs=SR, output='sos')
        elif item[0] == 'lp':
            sos = signal.butter(2, item[1], 'lowpass', fs=SR, output='sos')
        else:
            sos = biquad(*item)
        x = signal.sosfilt(sos, x, axis=0)
    return x


def kweight(x):
    b1 = [1.53512485958697, -2.69169618940638, 1.19839281085285]
    a1 = [1.0, -1.69065929318241, 0.73248077421585]
    b2 = [1.0, -2.0, 1.0]
    a2 = [1.0, -1.99004745483398, 0.99007225036621]
    return signal.lfilter(b2, a2, signal.lfilter(b1, a1, x, axis=0), axis=0)


def klevel(x, t0, t1):
    seg = kweight(x)[int(t0 * SR):int(t1 * SR)]
    return 10 * np.log10(np.mean(np.sum(seg ** 2, axis=1)) + 1e-12) - 0.691


def expression_env(mid, ch, offset, n):
    t, pts = 0.0, []
    for msg in mid:
        t += msg.time
        if msg.type == 'control_change' and msg.channel == ch and msg.control == 11:
            pts.append((t + offset, msg.value))
    if not pts:
        return np.ones(n)
    ts = np.array([p[0] for p in pts])
    vs = np.array([p[1] for p in pts], dtype=float)
    # MIDI CC is a step function (sample-and-hold); smooth the steps (~2 x 40 ms box) to avoid zipper noise
    idx = np.searchsorted(ts, np.arange(n) / SR, side='right') - 1
    cc = np.where(idx >= 0, vs[np.clip(idx, 0, None)], vs[0])
    w = int(0.04 * SR)
    cc = ndimage.uniform_filter1d(ndimage.uniform_filter1d(cc, w), w)
    return cc / 127.0


def dyn_bright(x, e, amount_db):
    """Expression-dependent high band (>1.4 kHz): soft = darker, loud = brighter (brass/strings timbre)."""
    if amount_db == 0:
        return x
    sos = signal.butter(2, 1400, 'highpass', fs=SR, output='sos')
    hi = signal.sosfilt(sos, x, axis=0)
    shape = np.interp(e, [0.0, 0.3, 0.65, 0.8, 0.95, 1.0], [-1.0, -1.0, -0.8, -0.45, 0.0, 0.2])
    g = 10 ** (shape * amount_db / 20.0) - 1.0
    return x + hi * g[:, None]


def make_ir(seed, length=3.4, predelay=0.024):
    rng = np.random.default_rng(seed)
    n = int(length * SR)
    t = np.arange(n) / SR
    noise = rng.standard_normal(n)
    bands = [(20, 180, 2.7), (180, 400, 2.6), (400, 900, 2.4), (900, 2000, 2.1),
             (2000, 4000, 1.7), (4000, 8000, 1.25), (8000, 16000, 0.8)]
    ir = np.zeros(n)
    for lo, hi, rt in bands:
        sos = signal.butter(4, [lo, hi], 'bandpass', fs=SR, output='sos')
        ir += signal.sosfiltfilt(sos, noise) * np.exp(-6.91 * t / rt)
    ir *= 1.0 - np.exp(-t / 0.035)                     # diffuse build-up
    er = np.zeros(n)                                   # early reflections
    for k in range(14):
        d = rng.uniform(0.006, 0.085)
        er[int(d * SR)] += rng.choice([-1, 1]) * 0.55 * np.exp(-d / 0.05)
    er = signal.sosfilt(signal.butter(2, 5000, 'lowpass', fs=SR, output='sos'), er)
    ir = ir / np.sqrt(np.sum(ir ** 2)) + er * 0.6 / max(1e-9, np.sqrt(np.sum(er ** 2)))
    ir = np.concatenate([np.zeros(int(predelay * SR)), ir])
    ir = signal.sosfilt(signal.butter(2, 180, 'highpass', fs=SR, output='sos'), ir)
    ir = signal.sosfilt(signal.butter(2, 9000, 'lowpass', fs=SR, output='sos'), ir)
    return ir / np.sqrt(np.sum(ir ** 2))


def reverb(send):
    irs = [make_ir(s) for s in (11, 23, 37, 41)]
    L, R = send[:, 0], send[:, 1]
    conv = lambda a, b: signal.oaconvolve(a, b)[:len(a)]
    wl = 0.85 * conv(L, irs[0]) + 0.40 * conv(R, irs[1])
    wr = 0.85 * conv(R, irs[2]) + 0.40 * conv(L, irs[3])
    return np.stack([wl, wr], axis=1)


def compressor(x, thr_db, ratio, att_ms, rel_ms, knee_db=6.0):
    blk = 48
    nb = len(x) // blk
    ms = np.mean((x[:nb * blk] ** 2).reshape(nb, blk, 2), axis=(1, 2))
    ms = signal.lfilter([1 - np.exp(-1 / 8.0)], [1, -np.exp(-1 / 8.0)], ms)   # ~8 ms RMS
    lvl = 10 * np.log10(ms + 1e-12)
    over = lvl - thr_db
    slope = 1 - 1 / ratio
    gr = np.where(over <= -knee_db / 2, 0.0,
                  np.where(over >= knee_db / 2, over * slope, slope * (over + knee_db / 2) ** 2 / (2 * knee_db)))
    aa, ar = np.exp(-1.0 / att_ms), np.exp(-1.0 / rel_ms)
    g = np.empty(nb)
    s = 0.0
    for i in range(nb):
        tgt = gr[i]
        s = aa * s + (1 - aa) * tgt if tgt > s else ar * s + (1 - ar) * tgt
        g[i] = s
    gs = np.interp(np.arange(len(x)), np.arange(nb) * blk + blk / 2, g)
    return x * (10 ** (-gs / 20))[:, None], g


def write_wav_float(path, x):
    import struct
    data = x.astype('<f4').tobytes()
    with open(path, 'wb') as f:
        f.write(b'RIFF' + struct.pack('<I', 36 + len(data)) + b'WAVE')
        f.write(b'fmt ' + struct.pack('<IHHIIHH', 16, 3, 2, SR, SR * 8, 8, 32))
        f.write(b'data' + struct.pack('<I', len(data)) + data)


# ---------------------------------------------------------------- main
def main():
    npz_path, midi_path, rs_path, out_wav, adir = sys.argv[1:6]
    os.makedirs(adir, exist_ok=True)
    spec = importlib.util.spec_from_file_location('render_stems', rs_path)
    rs = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(rs)
    name2ch = {v[0]: ch for ch, v in rs.STEMS.items()}
    offsets = {v[0]: v[5] for v in rs.STEMS.values()}
    mid = mido.MidiFile(midi_path)
    raw = np.load(npz_path)
    nr = raw['violins'].shape[0]

    proc, exprs = {}, {}
    for name, (sec, target, send, bright, eq) in MIX.items():
        x = raw[name].astype(np.float64)
        e = expression_env(mid, name2ch[name], offsets[name], nr)
        exprs[name] = e
        x = x * (e ** 2)[:, None]                 # CC11, 40*log10(cc/127) law
        x = dyn_bright(x, e, bright)
        x = apply_eq(x, eq)
        proc[name] = x

    # balance: gain so each stem hits its target K-weighted level in its reference section
    gains = {}
    for name, (sec, target, *_rest) in MIX.items():
        t0, t1 = [s for s in SECTIONS if s[0] == sec][0][1:]
        lvl = klevel(proc[name], t0, t1)
        gains[name] = target - lvl
        proc[name] *= 10 ** (gains[name] / 20)

    # report table
    hdr = f"{'stem':12s} {'gain':>6s} " + ' '.join(f'{s[0]:>9s}' for s in SECTIONS)
    lines = [hdr]
    for name in MIX:
        row = f"{name:12s} {gains[name]:6.1f} " + ' '.join(f'{klevel(proc[name], s[1], s[2]):9.1f}' for s in SECTIONS)
        lines.append(row)
    dry = sum(proc.values())
    lines.append(f"{'DRY SUM':12s} {'':6s} " + ' '.join(f'{klevel(dry, s[1], s[2]):9.1f}' for s in SECTIONS))

    send = sum(proc[n] * MIX[n][2] for n in MIX)
    wet = reverb(send) * 0.75
    mix = dry + wet
    lines.append(f"{'REVERB':12s} {'':6s} " + ' '.join(f'{klevel(wet, s[1], s[2]):9.1f}' for s in SECTIONS))

    # master EQ
    mix = apply_eq(mix, [('hp', 28), ('pk', 250, -1.0, 0.9), ('pk', 3200, 0.8, 1.0), ('hs', 5500, 1.5), ('hs', 11000, 1.5)])
    # stereo: mono below ~140 Hz, slightly wider above
    m = 0.5 * (mix[:, 0] + mix[:, 1])
    s = 0.5 * (mix[:, 0] - mix[:, 1])
    s = signal.sosfilt(signal.butter(2, 140, 'highpass', fs=SR, output='sos'), s) * 1.12
    mix = np.stack([m + s, m - s], axis=1)

    # glue compression (threshold relative to the climax level)
    clim = klevel(mix, 19.2, 26.4)
    mix, gr = compressor(mix, thr_db=clim - 3.0, ratio=2.0, att_ms=50, rel_ms=300)
    lines.append(f"compressor: max GR {gr.max():.1f} dB, climax mean GR {gr[int(19.2*1000):int(26.4*1000)].mean():.1f} dB")

    mix = mix[:N]
    # natural ending: raised-cosine fade over the last 1.0 s (28.6 -> 29.6), tiny fade-in
    fade = np.ones(N)
    f0 = int(28.6 * SR)
    fade[f0:] = 0.5 * (1 + np.cos(np.linspace(0, np.pi, N - f0)))
    fade[:240] = np.linspace(0, 1, 240)
    mix *= fade[:, None]
    mix *= 10 ** (-1.0 / 20) / np.abs(mix).max()
    write_wav_float(out_wav, mix.astype(np.float32))

    for name in ('intro', 'journeyA', 'journeyB', 'climax', 'end'):
        pass
    lines.append('section K-levels of premaster: ' + ', '.join(f'{s[0]} {klevel(mix, s[1], s[2]):.1f}' for s in SECTIONS))
    with open(os.path.join(adir, 'mix_report.txt'), 'w') as f:
        f.write('\n'.join(lines) + '\n')
    print('\n'.join(lines))


if __name__ == '__main__':
    main()
