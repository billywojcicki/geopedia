"""Minimal float-output FluidSynth wrapper (pyfluidsynth + ctypes fluid_synth_write_float)."""
import ctypes
import numpy as np
import fluidsynth

_write_float = fluidsynth._fl.fluid_synth_write_float
_write_float.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_void_p, ctypes.c_int, ctypes.c_int,
                         ctypes.c_void_p, ctypes.c_int, ctypes.c_int]
_write_float.restype = ctypes.c_int


class FS:
    def __init__(self, sf_path, sr=48000, gain=0.5):
        self.s = fluidsynth.Synth(gain=gain, samplerate=float(sr), channels=16,
                                  **{'synth.reverb.active': 0, 'synth.chorus.active': 0,
                                     'synth.polyphony': 1024})
        self.sfid = self.s.sfload(sf_path)

    def program(self, ch, bank, prog):
        self.s.program_select(ch, self.sfid, bank, prog)

    def render(self, n):
        buf = np.zeros((n, 2), np.float32)
        done = 0
        while done < n:
            k = min(4096, n - done)
            l = np.zeros(k, np.float32); r = np.zeros(k, np.float32)
            _write_float(self.s.synth, k, l.ctypes.data, 0, 1, r.ctypes.data, 0, 1)
            buf[done:done + k, 0] = l; buf[done:done + k, 1] = r
            done += k
        return buf
