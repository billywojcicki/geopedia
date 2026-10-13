#!/usr/bin/env python3
"""Visual + numeric inspection of a rendered wav: waveform, loudness curve, spectrogram.

Usage: analyze.py <in.wav> <out.png> [cues.json]
"""
import json
import sys
import wave

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np
from scipy import signal


def read_wav(path):
    with wave.open(path, 'rb') as w:
        sr, ch, sw, n = w.getframerate(), w.getnchannels(), w.getsampwidth(), w.getnframes()
        raw = w.readframes(n)
    if sw == 2:
        x = np.frombuffer(raw, '<i2').astype(np.float64) / 32768.0
    else:
        raise ValueError('expects 16-bit PCM; float premaster is read via soundfile-free path')
    return sr, x.reshape(-1, ch)


def read_any(path):
    with open(path, 'rb') as f:
        hdr = f.read(64)
    fmt = int.from_bytes(hdr[20:22], 'little')
    if fmt == 3:   # float32 written by mix.py (44-byte header)
        with open(path, 'rb') as f:
            f.seek(44)
            x = np.frombuffer(f.read(), '<f4').astype(np.float64).reshape(-1, 2)
        return 48000, x
    return read_wav(path)


def kweight(x):
    b1 = [1.53512485958697, -2.69169618940638, 1.19839281085285]
    a1 = [1.0, -1.69065929318241, 0.73248077421585]
    b2 = [1.0, -2.0, 1.0]
    a2 = [1.0, -1.99004745483398, 0.99007225036621]
    return signal.lfilter(b2, a2, signal.lfilter(b1, a1, x, axis=0), axis=0)


def main():
    path, out = sys.argv[1], sys.argv[2]
    cues = json.load(open(sys.argv[3])) if len(sys.argv) > 3 else None
    sr, x = read_any(path)
    n = len(x)
    t = np.arange(n) / sr
    k = kweight(x)
    p = np.sum(k ** 2, axis=1)
    hop = sr // 20
    def win_loud(w):
        L = int(w * sr)
        c = np.concatenate([[0], np.cumsum(p)])
        idx = np.arange(0, n, hop)
        lo = np.maximum(0, idx - L // 2); hi = np.minimum(n, idx + L // 2)
        return idx / sr, -0.691 + 10 * np.log10((c[hi] - c[lo]) / np.maximum(1, hi - lo) + 1e-12)
    tm, mom = win_loud(0.4)
    ts, st = win_loud(3.0)

    fig, ax = plt.subplots(3, 1, figsize=(16, 11), sharex=True, gridspec_kw={'height_ratios': [1, 1, 1.6]})
    blk = sr // 100
    nb = n // blk
    pk = np.abs(x[:nb * blk]).reshape(nb, blk, 2).max(axis=1)
    tb = np.arange(nb) * blk / sr
    ax[0].fill_between(tb, pk[:, 0], -pk[:, 1], color='#3b6ea5', lw=0)
    ax[0].set_ylim(-1.05, 1.05)
    ax[0].set_ylabel('peak (L up / R down)')
    ax[1].plot(tm, mom, color='#c0504d', lw=1, label='momentary (400 ms)')
    ax[1].plot(ts, st, color='#222', lw=1.6, label='short-term (3 s)')
    ax[1].set_ylim(-45, max(-5, np.nanmax(mom) + 2))
    ax[1].set_ylabel('LUFS (approx)')
    ax[1].legend(loc='upper left')
    f, tt, S = signal.spectrogram(np.mean(x, axis=1), fs=sr, nperseg=4096, noverlap=3072)
    S = 10 * np.log10(S + 1e-14)
    ax[2].pcolormesh(tt, f, S, shading='auto', vmin=S.max() - 90, vmax=S.max(), cmap='magma')
    ax[2].set_yscale('symlog', linthresh=100)
    ax[2].set_ylim(20, 20000)
    ax[2].set_ylabel('Hz')
    ax[2].set_xlabel('seconds')
    if cues:
        for b in cues['bars']:
            for a in ax:
                a.axvline(b['t'], color='#888', lw=0.6, ls=':')
        for s in cues['sections']:
            for a in ax:
                a.axvline(s['start'], color='#2a9d2a', lw=1.4)
            ax[0].text(s['start'] + 0.05, 0.92, s['name'], color='#2a9d2a', fontsize=10)
        ax[0].axvline(cues['endHit'], color='red', lw=1.6)
    plt.tight_layout()
    plt.savefig(out, dpi=80)
    print(f'duration {n/sr:.3f}s  sample peak {20*np.log10(np.abs(x).max()):.2f} dBFS  '
          f'max momentary {np.nanmax(mom):.1f}  max short-term {np.nanmax(st):.1f}')
    for name, a, b in [('intro', 0, 2.4), ('journeyA', 2.4, 12), ('journeyB', 12, 19.2), ('climax', 19.2, 26.4), ('end', 26.4, 29.6)]:
        sel = (ts >= a) & (ts < b)
        print(f'  {name:9s} short-term mean {np.mean(st[sel]):6.1f}  max momentary {np.max(mom[(tm>=a)&(tm<b)]):6.1f}')
    # spectral balance + stereo per section
    bands = [(20, 60), (60, 250), (250, 1000), (1000, 4000), (4000, 10000), (10000, 20000)]
    for name, a, b in [('journeyA', 2.4, 12), ('climax', 19.2, 26.4)]:
        seg = x[int(a * sr):int(b * sr)]
        F = np.fft.rfft(np.mean(seg, axis=1) * np.hanning(len(seg)))
        fr = np.fft.rfftfreq(len(seg), 1 / sr)
        P = np.abs(F) ** 2
        tot = P.sum()
        bl = ' '.join(f'{lo}-{hi}:{10*np.log10(P[(fr>=lo)&(fr<hi)].sum()/tot):6.1f}' for lo, hi in bands)
        corr = np.corrcoef(seg[:, 0], seg[:, 1])[0, 1]
        lr = 10 * np.log10(np.mean(seg[:, 0] ** 2) / np.mean(seg[:, 1] ** 2))
        print(f'  {name:9s} band dB (rel. total): {bl} | L/R corr {corr:.2f}, L-R balance {lr:+.1f} dB')
    # loudest momentary peaks
    order = np.argsort(mom)[::-1]
    picked = []
    for i in order:
        if all(abs(tm[i] - tm[j]) > 0.5 for j in picked):
            picked.append(i)
        if len(picked) == 6:
            break
    print('  loudest momentary moments:', ', '.join(f'{tm[i]:.2f}s ({mom[i]:.1f})' for i in sorted(picked)))


if __name__ == '__main__':
    main()
