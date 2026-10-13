"""Small numpy synth: band-limited oscillators, envelopes, filters, drums,
reverb, delay and chorus. Everything renders to float64 arrays at SR."""
import numpy as np
from scipy import signal

SR = 48000
rng = np.random.default_rng(1986)


def midi_hz(m):
    return 440.0 * 2 ** ((np.asarray(m, float) - 69) / 12)


def secs(n):
    return np.arange(n) / SR


# ---- oscillators -----------------------------------------------------------

def _blep(ph, dt):
    """PolyBLEP residual for a unit step at phase 0 (ph in [0,1), dt = f/SR)."""
    y = np.zeros_like(ph)
    a = ph < dt
    x = ph[a] / dt[a]
    y[a] = x + x - x * x - 1
    b = ph > 1 - dt
    x = (ph[b] - 1) / dt[b]
    y[b] = x * x + x + x + 1
    return y


def osc(kind, freq, n, phase=0.0, pw=0.5):
    """kind: saw, square, pulse, tri, sine. freq: scalar or per-sample array."""
    f = np.broadcast_to(np.asarray(freq, float), (n,)).astype(float)
    dt = f / SR
    ph = (phase + np.cumsum(dt) - dt[0]) % 1.0
    if kind == 'sine':
        return np.sin(2 * np.pi * ph)
    if kind == 'saw':
        return 2 * ph - 1 - _blep(ph, dt)
    if kind in ('square', 'pulse'):
        w = 0.5 if kind == 'square' else pw
        y = np.where(ph < w, 1.0, -1.0)
        return y + _blep(ph, dt) - _blep((ph + 1 - w) % 1.0, dt)
    if kind == 'tri':
        return 2 * np.abs(2 * ph - 1) - 1
    raise ValueError(kind)


def supersaw(freq, n, voices=7, spread=0.22, seed=0):
    r = np.random.default_rng(seed)
    out = np.zeros(n)
    offs = np.linspace(-1, 1, voices)
    for o in offs:
        cents = o * spread * 50
        out += osc('saw', freq * 2 ** (cents / 1200), n, phase=r.random()) * (1.0 if o == 0 else 0.8)
    return out / (1 + 0.8 * (voices - 1)) * 2.2


# ---- envelopes --------------------------------------------------------------

def adsr(n, hold, a=0.005, d=0.1, s=0.7, r=0.1):
    """n samples total; the note is held for `hold` seconds, then released."""
    t = secs(n)
    env = np.where(t < a, t / max(a, 1e-6), s + (1 - s) * np.exp(-(t - a) / max(d, 1e-6)))
    rel = t > hold
    if rel.any():
        lvl = env[min(int(hold * SR), n - 1)]
        env[rel] = lvl * np.exp(-(t[rel] - hold) / max(r, 1e-6))
    return env


def expdecay(n, tau, a=0.002):
    t = secs(n)
    return np.minimum(1, t / a) * np.exp(-t / tau)


# ---- filters ----------------------------------------------------------------

def _rbj(kind, fc, q):
    fc = float(np.clip(fc, 20, SR * 0.45))
    w = 2 * np.pi * fc / SR
    al = np.sin(w) / (2 * q)
    c = np.cos(w)
    if kind == 'lp':
        b = [(1 - c) / 2, 1 - c, (1 - c) / 2]
    elif kind == 'hp':
        b = [(1 + c) / 2, -(1 + c), (1 + c) / 2]
    elif kind == 'bp':
        b = [al, 0, -al]
    a = [1 + al, -2 * c, 1 - al]
    return np.array(b) / a[0], np.array(a) / a[0]


def filt(x, kind, fc, q=0.707):
    b, a = _rbj(kind, fc, q)
    return signal.lfilter(b, a, x, axis=0)


def tvfilt(x, kind, fc, q=0.707, block=128):
    """Time-varying biquad: fc is a per-sample array (sampled per block)."""
    fc = np.broadcast_to(np.asarray(fc, float), (len(x),))
    y = np.empty_like(x)
    zi = np.zeros(2)
    for i in range(0, len(x), block):
        b, a = _rbj(kind, fc[i], q)
        y[i:i + block], zi = signal.lfilter(b, a, x[i:i + block], zi=zi)
    return y


def butter(x, kind, fc, order=2):
    sos = signal.butter(order, np.asarray(fc) / (SR / 2), btype={'lp': 'low', 'hp': 'high', 'bp': 'band'}[kind], output='sos')
    return signal.sosfilt(sos, x, axis=0)


# ---- stereo helpers ----------------------------------------------------------

def pan(x, p):
    """p in [-1, 1], equal power."""
    a = (p + 1) * np.pi / 4
    return np.stack([x * np.cos(a), x * np.sin(a)], axis=1)


def place(buf, x, t0):
    i = int(round(t0 * SR))
    if i < 0:
        x = x[-i:]
        i = 0
    j = min(len(buf), i + len(x))
    if j > i:
        buf[i:j] += x[:j - i]


# ---- drums ------------------------------------------------------------------

def kick(vel=1.0):
    n = int(0.5 * SR)
    t = secs(n)
    f = 46 + 110 * np.exp(-t / 0.035)
    body = np.sin(2 * np.pi * np.cumsum(f) / SR) * expdecay(n, 0.28, 0.001)
    click = butter(rng.standard_normal(n), 'hp', 2500) * expdecay(n, 0.004, 0.0002) * 0.5
    return np.tanh(1.6 * (body + click)) * vel


def snare_dry(vel=1.0):
    n = int(0.35 * SR)
    t = secs(n)
    tone = np.sin(2 * np.pi * np.cumsum(185 + 60 * np.exp(-t / 0.02)) / SR) * expdecay(n, 0.06, 0.001)
    noise = butter(rng.standard_normal(n), 'bp', [900, 9000]) * expdecay(n, 0.11, 0.001)
    return (0.55 * tone + 0.9 * noise) * vel


def clap(vel=1.0):
    n = int(0.3 * SR)
    t = secs(n)
    env = np.zeros(n)
    for k, d in enumerate([0, 0.011, 0.022]):
        env += np.where(t >= d, np.exp(-(t - d) / 0.008), 0) * (0.8 if k < 2 else 1)
    env += np.where(t >= 0.03, np.exp(-(t - 0.03) / 0.09), 0) * 0.7
    return butter(rng.standard_normal(n), 'bp', [1000, 4500]) * env * vel * 0.8


def gated_verb(x, hold=0.24, decay=0.9, release=0.025, seed=3):
    """The 80s snare: a big room, cut off hard."""
    n = int(decay * 1.6 * SR)
    r = np.random.default_rng(seed)
    ir = r.standard_normal((n, 2)) * np.exp(-secs(n) / (decay / 4))[:, None]
    ir = butter(ir, 'lp', 7000)
    wet = np.stack([signal.fftconvolve(x, ir[:, 0]), signal.fftconvolve(x, ir[:, 1])], axis=1)
    t = secs(len(wet))
    gate = np.where(t < hold, 1.0, np.exp(-(t - hold) / release))
    return wet * gate[:, None] * 0.09


def hat(open_=False, vel=1.0):
    n = int((0.32 if open_ else 0.06) * SR)
    noise = rng.standard_normal(n)
    metal = sum(osc('square', f, n, phase=rng.random()) for f in (205, 297, 365, 535, 540, 800)) / 6
    x = butter(0.6 * noise + 0.8 * metal, 'hp', 7500)
    return x * expdecay(n, 0.11 if open_ else 0.018, 0.0005) * vel * 0.5


def crash(vel=1.0, length=2.4):
    n = int(length * SR)
    noise = rng.standard_normal(n)
    metal = sum(osc('square', f, n, phase=rng.random()) for f in (311, 427, 571, 733, 1011, 1307)) / 6
    x = butter(0.8 * noise + 0.5 * metal, 'hp', 3200)
    return x * expdecay(n, length / 3.2, 0.002) * vel * 0.45


def tom(midi, vel=1.0):
    n = int(0.45 * SR)
    t = secs(n)
    f = midi_hz(midi) * (1 + 0.6 * np.exp(-t / 0.03))
    body = np.sin(2 * np.pi * np.cumsum(f) / SR) * expdecay(n, 0.18, 0.001)
    return np.tanh(1.3 * (body + 0.15 * butter(rng.standard_normal(n), 'bp', [300, 3000]) * expdecay(n, 0.04))) * vel


def sub_boom(length=2.2, f0=58, f1=28):
    n = int(length * SR)
    t = secs(n)
    f = f1 + (f0 - f1) * np.exp(-t / 0.4)
    body = np.sin(2 * np.pi * np.cumsum(f) / SR) * expdecay(n, length / 3.5, 0.004)
    thud = butter(rng.standard_normal(n), 'lp', 400) * expdecay(n, 0.08, 0.002) * 0.6
    return np.tanh(1.4 * (body + thud))


def riser(length, f0=300, f1=9000, seed=5):
    n = int(length * SR)
    k = secs(n) / length
    fc = f0 * (f1 / f0) ** (k ** 1.5)
    r = np.random.default_rng(seed)
    x = tvfilt(r.standard_normal(n), 'bp', fc, q=2.5)
    return x * (k ** 2.2) * 0.9


def fm_bell(midi, length=1.6, index=5.0, ratio=3.5):
    n = int(length * SR)
    f = midi_hz(midi)
    t = secs(n)
    idx = index * np.exp(-t / 0.35)
    mod = np.sin(2 * np.pi * f * ratio * t) * idx
    car = np.sin(2 * np.pi * f * t + mod)
    return car * expdecay(n, length / 4, 0.001)


# ---- effects ----------------------------------------------------------------

def reverb_ir(length=2.4, seed=11, bright=6000, dark=1800):
    n = int(length * SR)
    r = np.random.default_rng(seed)
    t = secs(n)
    env = np.exp(-t / (length / 6.5))
    ir = r.standard_normal((n, 2)) * env[:, None]
    hi, lo = butter(ir, 'lp', bright), butter(ir, 'lp', dark)
    mix = np.clip(t / length * 2.2, 0, 1)[:, None]  # darker as it decays
    ir = hi * (1 - mix) + lo * mix
    ir[:int(0.012 * SR)] *= np.linspace(0, 1, int(0.012 * SR))[:, None]  # predelay-ish fade in
    return ir / np.sqrt(np.sum(ir ** 2) / 2)


def convolve(x, ir):
    """x: (n, 2); ir: (m, 2) -> (n + m - 1, 2), true stereo-ish (L->L, R->R)."""
    return np.stack([signal.fftconvolve(x[:, 0], ir[:, 0]), signal.fftconvolve(x[:, 1], ir[:, 1])], axis=1)


def pingpong(x, delay, fb=0.45, taps=6, lp=5000):
    """x: (n, 2) -> echoes only, alternating sides."""
    d = int(delay * SR)
    out = np.zeros((len(x) + d * taps, 2))
    mono = (x[:, 0] + x[:, 1]) / 2
    src = mono
    for k in range(1, taps + 1):
        src = butter(src, 'lp', lp) * fb
        side = 0 if k % 2 else 1
        out[k * d:k * d + len(src), side] += src
    return out


def chorus(x, depth=0.004, rate=0.7, base=0.012):
    """x: mono -> stereo with two modulated delay lines."""
    n = len(x)
    t = secs(n)
    idx = np.arange(n)
    out = []
    for ph in (0, np.pi):
        dl = (base + depth * np.sin(2 * np.pi * rate * t + ph)) * SR
        out.append(0.6 * x + 0.6 * np.interp(idx - dl, idx, x, left=0))
    return np.stack(out, axis=1)


def sidechain(n, hits, depth=0.55, rel=0.16):
    """Gain curve that ducks after every kick time in `hits`."""
    g = np.ones(n)
    t = secs(n)
    for h in hits:
        i = int(h * SR)
        j = min(n, i + int(rel * 6 * SR))
        if i >= n:
            continue
        tt = t[i:j] - h
        g[i:j] = np.minimum(g[i:j], 1 - depth * np.exp(-tt / rel))
    return g
