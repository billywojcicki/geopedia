#!/usr/bin/env python3
"""Mastering: gain to target, true-peak lookahead limiter, ffmpeg loudnorm (two-pass, linear),
TPDF-dithered 16-bit WAV, AAC 256k M4A, verification.

Usage: master.py <premaster_f32.wav> <music_dir> <work_dir>
"""
import json
import os
import re
import struct
import subprocess
import sys

import numpy as np
from scipy import ndimage, signal

SR = 48000
DURATION = 29.6
N = int(round(DURATION * SR))
TARGET_I = -14.0
TARGET_TP = -1.5
FFMPEG = '/usr/bin/ffmpeg'


def read_f32(path):
    with open(path, 'rb') as f:
        data = f.read()
    # find 'data' chunk
    i = data.find(b'data')
    n = struct.unpack('<I', data[i + 4:i + 8])[0]
    fmt = struct.unpack('<H', data[20:22])[0]
    if fmt == 3:
        x = np.frombuffer(data[i + 8:i + 8 + n], '<f4').astype(np.float64)
    elif fmt == 0xFFFE:   # extensible (ffmpeg writes this for f32)
        sub = struct.unpack('<H', data[44:46])[0]
        assert sub == 3, 'expected float subformat'
        x = np.frombuffer(data[i + 8:i + 8 + n], '<f4').astype(np.float64)
    else:
        raise ValueError(f'unsupported wav format {fmt}')
    return x.reshape(-1, 2)


def write_f32(path, x):
    d = x.astype('<f4').tobytes()
    with open(path, 'wb') as f:
        f.write(b'RIFF' + struct.pack('<I', 36 + len(d)) + b'WAVE')
        f.write(b'fmt ' + struct.pack('<IHHIIHH', 16, 3, 2, SR, SR * 8, 8, 32))
        f.write(b'data' + struct.pack('<I', len(d)) + d)


def write_s16(path, x, seed=2026):
    rng = np.random.default_rng(seed)
    tpdf = (rng.random(x.shape) - rng.random(x.shape))          # +-1 LSB triangular
    q = np.clip(np.round(x * 32767.0 + tpdf), -32768, 32767).astype('<i2')
    d = q.tobytes()
    with open(path, 'wb') as f:
        f.write(b'RIFF' + struct.pack('<I', 36 + len(d)) + b'WAVE')
        f.write(b'fmt ' + struct.pack('<IHHIIHH', 16, 1, 2, SR, SR * 4, 4, 16))
        f.write(b'data' + struct.pack('<I', len(d)) + d)


def true_peak_per_sample(x, os_factor=4):
    up = signal.resample_poly(x, os_factor, 1, axis=0)
    pk = np.max(np.abs(up), axis=1)
    pk = pk[:len(x) * os_factor].reshape(len(x), os_factor).max(axis=1)
    return np.maximum(pk, np.max(np.abs(x), axis=1))


def limiter(x, ceiling_db, look_ms=2.0, rel_ms=80.0):
    ceil = 10 ** (ceiling_db / 20)
    pk = true_peak_per_sample(x)
    need = np.minimum(1.0, ceil / np.maximum(pk, 1e-12))
    L = int(look_ms * SR / 1000)
    # forward-looking min over [n, n+L]
    fwd = ndimage.minimum_filter1d(need, size=L + 1, origin=-(L // 2))
    # release smoothing (never above fwd)
    ar = np.exp(-1.0 / (rel_ms * SR / 1000))
    g = np.empty_like(fwd)
    s = 1.0
    for i in range(len(fwd)):
        s = 1.0 - (1.0 - s) * ar
        if fwd[i] < s:
            s = fwd[i]
        g[i] = s
    # attack smoothing: moving average over the past L samples (stays <= need at each peak)
    k = np.ones(L) / L
    g = np.convolve(np.concatenate([np.ones(L - 1), g]), k, mode='valid')
    return x * g[:, None], g


def run(cmd):
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        print(r.stderr[-3000:])
        raise SystemExit(f'command failed: {cmd[:4]}')
    return r.stderr


def loudnorm_measure(path):
    err = run([FFMPEG, '-hide_banner', '-nostats', '-i', path, '-af',
               f'loudnorm=I={TARGET_I}:TP={TARGET_TP}:LRA=20:print_format=json', '-f', 'null', '-'])
    js = json.loads(err[err.rfind('{'):err.rfind('}') + 1])
    return js


def ebur128(path):
    err = run([FFMPEG, '-hide_banner', '-nostats', '-i', path, '-af', 'ebur128=peak=true:framelog=quiet', '-f', 'null', '-'])
    summ = err[err.rfind('Summary:'):]
    I = float(re.search(r'I:\s+(-?[\d.]+) LUFS', summ).group(1))
    LRA = float(re.search(r'LRA:\s+(-?[\d.]+) LU', summ).group(1))
    TP = float(re.search(r'Peak:\s+(-?[\d.]+) dBFS', summ).group(1))
    return I, LRA, TP


def main():
    pre, mdir, wdir = sys.argv[1:4]
    x = read_f32(pre)[:N]

    # 1) measure, gain, true-peak limit so that loudnorm can stay in linear mode
    m0 = loudnorm_measure(pre)
    gain_db = TARGET_I - float(m0['input_i']) + 0.25           # small allowance for limiter loss
    y = x * 10 ** (gain_db / 20)
    y, g = limiter(y, TARGET_TP - 0.15)
    gr_db = -20 * np.log10(g.min())
    lim_path = os.path.join(wdir, 'limited.wav')
    write_f32(lim_path, y)
    print(f'premaster I {m0["input_i"]} LUFS, TP {m0["input_tp"]} -> gain {gain_db:+.2f} dB, limiter max GR {gr_db:.2f} dB, '
          f'GR>1dB for {np.mean(g < 10**(-1/20))*100:.2f}% of samples')

    # 2) ffmpeg loudnorm, two-pass, linear
    m1 = loudnorm_measure(lim_path)
    print('loudnorm pass 1:', {k: m1[k] for k in ('input_i', 'input_tp', 'input_lra', 'input_thresh', 'target_offset')})
    norm_path = os.path.join(wdir, 'loudnorm.wav')
    af = (f"loudnorm=I={TARGET_I}:TP={TARGET_TP}:LRA=20:measured_I={m1['input_i']}:measured_TP={m1['input_tp']}:"
          f"measured_LRA={m1['input_lra']}:measured_thresh={m1['input_thresh']}:offset={m1['target_offset']}:"
          f"linear=true:print_format=json,aresample={SR}")
    err = run([FFMPEG, '-hide_banner', '-nostats', '-y', '-i', lim_path, '-af', af, '-c:a', 'pcm_f32le', norm_path])
    m2 = json.loads(err[err.rfind('{'):err.rfind('}') + 1])
    print('loudnorm pass 2:', {k: m2[k] for k in ('output_i', 'output_tp', 'output_lra', 'normalization_type')})
    assert m2['normalization_type'] == 'linear', 'loudnorm fell back to dynamic mode'

    z = read_f32(norm_path)
    if len(z) < N:
        z = np.concatenate([z, np.zeros((N - len(z), 2))])
    z = z[:N]
    # final trim: loudnorm measures at 192 kHz internally; correct the small residual vs. ebur128 (<= 0.3 dB)
    write_f32(norm_path, z)
    I_chk, _, TP_chk = ebur128(norm_path)
    trim = float(np.clip(TARGET_I - I_chk, -0.3, 0.3))
    if TP_chk + trim > -1.2:
        trim = min(trim, -1.2 - TP_chk)
    z = z * 10 ** (trim / 20)
    print(f'post-loudnorm check: I {I_chk:.2f} LUFS, TP {TP_chk:.2f} dBTP -> trim {trim:+.2f} dB')
    wav = os.path.join(mdir, 'music.wav')
    write_s16(wav, z)
    m4a = os.path.join(mdir, 'music.m4a')
    run([FFMPEG, '-hide_banner', '-y', '-i', wav, '-c:a', 'aac', '-b:a', '256k', '-ar', str(SR),
         '-movflags', '+faststart', m4a])

    for path in (wav, m4a):
        I, LRA, TP = ebur128(path)
        dur = float(subprocess.run(['/usr/bin/ffprobe', '-v', 'error', '-show_entries', 'format=duration',
                                    '-of', 'csv=p=0', path], capture_output=True, text=True).stdout.strip())
        print(f'VERIFY {os.path.basename(path)}: duration {dur:.3f}s  I {I:.1f} LUFS  LRA {LRA:.1f} LU  true peak {TP:.1f} dBTP')


if __name__ == '__main__':
    main()
