import sys, mido, matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
mid = mido.MidiFile(sys.argv[1]); out = sys.argv[2]
tpb = mid.ticks_per_beat
fig, axes = plt.subplots(4, 1, figsize=(18, 16), sharex=True)
groups = [('melody: violins/horns/trombones/trumpets', {0: 'tab:blue', 5: 'tab:orange', 6: 'tab:brown', 7: 'tab:red'}),
          ('pads: strings slow/tremolo/aahs/oohs', {1: 'tab:green', 2: 'tab:olive', 10: 'tab:purple', 11: 'tab:pink'}),
          ('rhythm/bass: cellos/violas/basses/tuba/timpani', {3: 'tab:cyan', 15: 'tab:blue', 4: 'black', 8: 'tab:brown', 14: 'tab:red'}),
          ('harp/celesta/percussion', {12: 'tab:green', 13: 'tab:purple', 9: 'tab:gray'})]
notes = []
for tr in mid.tracks:
    t = 0; on = {}
    for m in tr:
        t += m.time
        if m.type == 'note_on' and m.velocity > 0: on.setdefault((m.channel, m.note), []).append((t, m.velocity))
        elif m.type in ('note_off', 'note_on'):
            k = (m.channel, m.note)
            if on.get(k): s, v = on[k].pop(0); notes.append((s / tpb, t / tpb, m.channel, m.note, v))
for ax, (title, cmap) in zip(axes, groups):
    for s, e, ch, n, v in notes:
        if ch in cmap:
            ax.add_patch(plt.Rectangle((s * 0.6, n - 0.4), (e - s) * 0.6, 0.8, color=cmap[ch], alpha=0.35 + 0.65 * v / 127))
    ns = [n for s, e, ch, n, v in notes if ch in cmap]
    ax.set_ylim(min(ns) - 2, max(ns) + 2); ax.set_title(title, loc='left')
    for b in range(13): ax.axvline(b * 2.4, color='#999', lw=0.6)
    ax.grid(axis='y', alpha=0.2)
axes[-1].set_xlim(0, 29.6); axes[-1].set_xlabel('seconds')
plt.tight_layout(); plt.savefig(out, dpi=70)
