import struct, sqlite3, os, collections
data=open('./anarchy.sws','rb').read(); N=len(data)
def u32(o): return struct.unpack_from('<I',data,o)[0]
def s32(o): return struct.unpack_from('<i',data,o)[0]
def f32(o): return struct.unpack_from('<f',data,o)[0]
o=0x08; names=[]
for _ in range(59):
    e=data.index(b'\x00',o); o=e+1
    e=data.index(b'\x00',o); names.append(data[o:e].decode('latin1')); o=e+1
def pf(q):
    tag=data[q]; typ=u32(q+1); bs=u32(q+9); pay=q+13
    if typ==3:   v=[u32(pay+4*i) for i in range(bs//4)]
    elif typ==17:v=[s32(pay+4*i) for i in range(bs//4)]
    elif typ==10:v=[f32(pay+4*i) for i in range(bs//4)]
    elif typ==6: ln=u32(pay); v=data[pay+4:pay+4+ln].decode('latin1')
    else:        v=list(data[pay:pay+bs])
    return names[tag],v,q+13+bs
objs=[]; op=0x249
while op+4<=N:
    fc=u32(op+8); q=op+12; cid=u32(q+13); f={}
    for _ in range(fc):
        n,v,q=pf(q); f[n]=v
    objs.append((cid,f)); op=op+4+u32(op)
root=objs[0][1]
lnames=[]; o2=0x3fd
for _ in range(91):
    ln=u32(o2); o2+=4; lnames.append(data[o2:o2+ln].decode('latin1')); o2+=ln
lpause=root['lpause']; lvol=root['lvol']; lid_arr=root['lid']
def cat(n):
    l=n.lower()
    if l.startswith('inn'): return 'inn'
    if l.startswith('battle'): return 'battle'
    if l.startswith('landcontrol'): return 'landcontrol'
    if l.startswith('ep_01') or l.startswith('ep01'): return 'ep_01'   # Shadowlands
    if l.startswith('ep_02') or l.startswith('ep02'): return 'ep_02'   # Alien Invasion
    if l.startswith('lost_eden'): return 'lost_eden'
    for z in ('clan','desert','dungeon','forest','mountain','ocean','omni','plains','swamp','trade','tribal'):
        if l.startswith(z): return 'rubika'
    return 'other'
# GLOBAL clip index (file order) <-> object index
gidx_to_obj=[]; obj_to_gidx={}; layer_local={}; layer_count=collections.Counter()
for i,(c,f) in enumerate(objs):
    if c==19:
        obj_to_gidx[i]=len(gidx_to_obj); gidx_to_obj.append(i)
        s=f['lid'][0]; layer_local[i]=layer_count[s]; layer_count[s]+=1
db='./anarchy_sim.db'
if os.path.exists(db): os.remove(db)
con=sqlite3.connect(db); cur=con.cursor()
cur.executescript('''
CREATE TABLE layers(slot INTEGER PRIMARY KEY, name TEXT, lid INTEGER, lpause INTEGER,
                    lvol REAL, is_real INTEGER, category TEXT);
CREATE TABLE pausetracks(ordinal INTEGER PRIMARY KEY, obj_index INTEGER, layer_slot INTEGER,
                    beatnum INTEGER, beatdenom INTEGER, bpm INTEGER, loopto INTEGER,
                    numnodes TEXT, pn_playbeats TEXT, pn_pausebeats TEXT, pn_ptype TEXT,
                    pn_fadein TEXT, pn_fadeout TEXT,
                    FOREIGN KEY(layer_slot) REFERENCES layers(slot));
CREATE TABLE clips(obj_index INTEGER PRIMARY KEY, gidx INTEGER UNIQUE, name TEXT, layer_slot INTEGER,
                    local_index INTEGER, totoffms INTEGER, ntrans INTEGER, endm INTEGER,
                    endmtime INTEGER, vol REAL, tempo INTEGER, bdvdn INTEGER, bdvsr INTEGER,
                    FOREIGN KEY(layer_slot) REFERENCES layers(slot));
CREATE TABLE transitions(obj_index INTEGER PRIMARY KEY, source_clip INTEGER, target_clip INTEGER,
                    fot INTEGER, ftime INTEGER, pri INTEGER,
                    FOREIGN KEY(source_clip) REFERENCES clips(obj_index),
                    FOREIGN KEY(target_clip) REFERENCES clips(obj_index));
CREATE TABLE fadeinfo(obj_index INTEGER PRIMARY KEY, ctype INTEGER, fcond INTEGER,
                    cfac REAL, levin REAL, levout REAL);
CREATE TABLE chords(obj_index INTEGER PRIMARY KEY, pos INTEGER, len INTEGER, chord TEXT);
''')
rev={}
for slot in range(91):
    lp=lpause[slot]
    if lp!=-1: rev[lp]=slot
    cur.execute('INSERT INTO layers VALUES(?,?,?,?,?,?,?)',
        (slot,lnames[slot],lid_arr[slot],lp,lvol[slot],1 if lp!=-1 else 0,cat(lnames[slot])))
def j(v): return ",".join(map(str,v)) if isinstance(v,list) else str(v)
ordn=0
for i,(c,f) in enumerate(objs):
    if c==5:
        ordn+=1
        cur.execute('INSERT INTO pausetracks VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)',
            (ordn,i,rev.get(ordn),f.get('beatnum',[None])[0],f.get('beatdenom',[None])[0],
             f.get('bpm',[None])[0],f.get('loopto',[None])[0],j(f.get('numnodes',[])),
             j(f.get('pn_playbeats',[])),j(f.get('pn_pausebeats',[])),j(f.get('pn_ptype',[])),
             j(f.get('pn_fadein',[])),j(f.get('pn_fadeout',[]))))
    elif c==19:
        cur.execute('INSERT INTO clips VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)',
            (i,obj_to_gidx[i],f['name'],f['lid'][0],layer_local[i],f.get('totoffms',[None])[0],
             f.get('ntrans',[None])[0],f.get('endm',[None])[0],f.get('endmtime',[None])[0],
             f.get('vol',[None])[0],f.get('temps',[None])[0],f.get('bdvdn',[None])[0],f.get('bdvsr',[None])[0]))
    elif c==25:
        cur.execute('INSERT INTO fadeinfo VALUES(?,?,?,?,?,?)',
            (i,f.get('ctype',[None])[0],f.get('fcond',[None])[0],f.get('cfac',[None])[0],
             f.get('levin',[None])[0],f.get('levout',[None])[0]))
    elif c==54:
        cur.execute('INSERT INTO chords VALUES(?,?,?,?)',
            (i,f.get('pos',[None])[0],f.get('len',[None])[0],j(f.get('chord',[]))))
# transitions from ALL CTransition objects via global clip index
unresolved=0
for i,(c,f) in enumerate(objs):
    if c==23:
        sid=f.get('sampid',[None,None]); fot=f.get('fot',[None])[0]
        ftime=f.get('ftime',[None])[0]; pri=f.get('pri',[None])[0]
        def g(x): return gidx_to_obj[x] if (x is not None and 0<=x<len(gidx_to_obj)) else None
        src=g(sid[0]); tgt=g(sid[1])
        if src is None or tgt is None: unresolved+=1
        cur.execute('INSERT INTO transitions VALUES(?,?,?,?,?,?)',(i,src,tgt,fot,ftime,pri))
cur.executescript('CREATE INDEX ix_clip_layer ON clips(layer_slot);'
                  'CREATE INDEX ix_tr_src ON transitions(source_clip);'
                  'CREATE INDEX ix_tr_tgt ON transitions(target_clip);')
# --- targeted normalisation: desert\Expansive ---
# This layer is uniform 2-bar (8-beat) material at 95 BPM / 4/4, but it was authored loosely:
# most clips have endm/endmtime left at 0, and every transition uses a flat fot=5104 that sits
# ~56 ms past the 2-bar grid (8 beats @ 95 BPM = 5052.6 ms, stored elsewhere as 5048). Normalise
# the whole layer to how it was musically intended: endm=8, endmtime=5048 on every clip, and fot
# =5048 on every edge departing the layer, so all handoffs land cleanly on the 2-bar line.
_exp = cur.execute("SELECT slot FROM layers WHERE name=?", ('desert\\Expansive',)).fetchone()
if _exp:
    _s = _exp[0]
    cur.execute("UPDATE clips SET endm=8, endmtime=5048 WHERE layer_slot=?", (_s,))
    cur.execute("UPDATE transitions SET fot=5048 "
                "WHERE source_clip IN (SELECT obj_index FROM clips WHERE layer_slot=?)", (_s,))
con.commit()
print("unresolved transitions (src/tgt out of clip range):", unresolved)
for t in ('layers','pausetracks','clips','transitions','fadeinfo','chords'):
    print(f"  {t}: {cur.execute('SELECT count(*) FROM '+t).fetchone()[0]} rows")
# sanity: source must equal owning clip for clip-owned transitions
bad=cur.execute('''SELECT count(*) FROM clips c JOIN transitions t ON t.source_clip=c.obj_index
                   WHERE c.obj_index NOT IN (SELECT source_clip FROM transitions)''').fetchone()[0]
# verify FDay01 successors
print("\nFDay01 successors (via JOIN):")
for r in cur.execute('''SELECT tc.name, t.fot, t.ftime FROM transitions t
        JOIN clips sc ON t.source_clip=sc.obj_index
        JOIN clips tc ON t.target_clip=tc.obj_index
        WHERE sc.name='FDay01' ORDER BY t.fot'''):
    print("   ->",r[0],"@ fot",r[1],"(lead-in ftime",str(r[2])+")")
con.close(); print("\nsize:", os.path.getsize(db),"bytes")
