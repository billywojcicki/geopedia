import sys, mido, itertools
mid = mido.MidiFile(sys.argv[1]); tpb = mid.ticks_per_beat
notes = []
for tr in mid.tracks:
    t = 0; on = {}
    for m in tr:
        t += m.time
        if m.type == 'note_on' and m.velocity > 0: on.setdefault((m.channel, m.note), []).append(t)
        elif m.type in ('note_off', 'note_on'):
            k = (m.channel, m.note)
            if on.get(k): s = on[k].pop(0); notes.append((s/tpb, t/tpb, m.channel, m.note))
names = {0:'vln',1:'pad',2:'trem',3:'vc',4:'cb',5:'hn',6:'tbn',7:'tpt',8:'tba',10:'aah',11:'ooh',12:'hp',13:'cel',14:'timp',15:'vla'}
pitched = [n for n in notes if n[2] not in (9,)]
seen = set()
for a, b in itertools.combinations(pitched, 2):
    ov = min(a[1], b[1]) - max(a[0], b[0])
    if ov < 0.45: continue
    iv = abs(a[3] - b[3])
    if iv % 12 in (1, 11) and iv < 24:
        key = (round(max(a[0], b[0]), 2), min(a[3], b[3]), max(a[3], b[3]))
        if key in seen: continue
        seen.add(key)
        print(f"m2 clash beat {max(a[0],b[0]):6.2f} ov {ov:4.2f}: {names[a[2]]}:{a[3]} vs {names[b[2]]}:{b[3]}")
print('notes', len(notes))
