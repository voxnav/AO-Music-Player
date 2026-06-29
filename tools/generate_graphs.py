#!/usr/bin/env python3
"""
generate_graphs.py — build the human-legible, name-keyed GRAPHS from anarchy_sim.db.

Output (a pastable JS literal, `const GRAPHS = { ... };`):

  const GRAPHS = {
    "ocean\\Night": {
      "slot": 20, "category": "rubika",
      "nodes": [
        {"clip":"a06","endmtime":7792,"next":[["a07",7792],["a08",7792]]},
        ...
      ]
    },
    ...
  };

Per graph:
  - keyed by layers.name (unique across all 91 layers; same namespace as the
    player's folder groups), so duplicate identifiers are structurally impossible.
  - slot      : layers.slot (stable integer id / DB join key)
  - category  : layers.category
  - nodes     : ARRAY, index = clips.local_index (start node = nodes[0]).
                An array (not an object keyed by name) because some clips are
                named "01".."20" — integer-like object keys would silently reorder.

Per node:
  - clip      : clip name, lowercased (matches how the player matches audio files)
  - endmtime  : musical handoff point in ms. 0 is preserved as the "unset" sentinel.
  - next      : intra-track edges, [[targetClip, fot], ...]; terminal node = [].
                fot is the absolute entry point the player schedules against
                (= source.endmtime - lead-in). Sorted by fot then name for stable
                output. NOTE: this uses the DB `fot` column, not the DB `ftime`
                column (which is the derivable lead-in, kept for fidelity only).
  - exits     : (optional) cross-track authored transitions,
                [[targetLayerName, targetClip, fot], ...]. These are the game's
                authored track-to-track moves (e.g. the battle state machine,
                day/night links). Omitted when a node has none. Use --no-exits to
                drop them entirely (matches the old format, which discarded them).

Usage:
    python3 generate_graphs.py [DB] [--out graphs.js] [--no-exits] [--var GRAPHS]
"""
import argparse, json, sqlite3, sys
from collections import defaultdict


def build(db_path, keep_exits=True):
    con = sqlite3.connect(db_path); con.row_factory = sqlite3.Row; cur = con.cursor()

    layers = {r["slot"]: r for r in cur.execute(
        "SELECT slot, name, category FROM layers")}
    clips = list(cur.execute(
        "SELECT obj_index, name, layer_slot, local_index, endmtime "
        "FROM clips ORDER BY layer_slot, local_index"))
    clip_by_obj = {c["obj_index"]: c for c in clips}

    by_layer = defaultdict(list)
    for c in clips:
        by_layer[c["layer_slot"]].append(c)

    out_edges = defaultdict(list)
    for t in cur.execute("SELECT source_clip, target_clip, fot FROM transitions"):
        out_edges[t["source_clip"]].append(t)

    stats = dict(graphs=0, nodes=0, intra=0, exits=0, terminal=0,
                 unresolved=0, endmtime0=0)

    graphs = {}
    for slot in sorted(by_layer):                       # natural layer order
        node_rows = by_layer[slot]                      # already in local_index order
        nodes = []
        for c in node_rows:
            within, exits = [], []
            for t in out_edges.get(c["obj_index"], []):
                tgt = clip_by_obj.get(t["target_clip"])
                if tgt is None:
                    stats["unresolved"] += 1
                    continue
                if tgt["layer_slot"] == slot:
                    within.append([tgt["name"].lower(), t["fot"]])
                else:
                    exits.append([layers[tgt["layer_slot"]]["name"],
                                  tgt["name"].lower(), t["fot"]])
            # stable, legible ordering
            within.sort(key=lambda e: (e[1], e[0]))
            exits.sort(key=lambda e: (e[0], e[2], e[1]))

            node = {"clip": c["name"].lower(),
                    "endmtime": c["endmtime"],
                    "next": within}
            if keep_exits and exits:
                node["exits"] = exits
            nodes.append(node)

            stats["nodes"] += 1
            stats["intra"] += len(within)
            stats["exits"] += len(exits)
            if not within:
                stats["terminal"] += 1
            if c["endmtime"] == 0:
                stats["endmtime0"] += 1

        graphs[layers[slot]["name"]] = {
            "slot": slot,
            "category": layers[slot]["category"],
            "nodes": nodes,
        }
        stats["graphs"] += 1

    con.close()
    return graphs, stats


def serialize(graphs, var="GRAPHS"):
    """Emit a JS literal with one node per line for readability."""
    lines = [f"const {var} = {{"]
    names = list(graphs)
    for gi, name in enumerate(names):
        g = graphs[name]
        gcomma = "," if gi < len(names) - 1 else ""
        lines.append(f"  {json.dumps(name)}: {{")
        lines.append(f'    "slot": {g["slot"]}, "category": {json.dumps(g["category"])},')
        lines.append('    "nodes": [')
        nd = g["nodes"]
        for ni, node in enumerate(nd):
            ncomma = "," if ni < len(nd) - 1 else ""
            lines.append("      " + json.dumps(node, separators=(",", ":")) + ncomma)
        lines.append("    ]")
        lines.append("  }" + gcomma)
    lines.append("};")
    return "\n".join(lines) + "\n"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("db", nargs="?", default="anarchy_sim.db")
    ap.add_argument("--out", default=None, help="write the JS literal here")
    ap.add_argument("--no-exits", action="store_true",
                    help="drop cross-track 'exits' (lean, old-style format)")
    ap.add_argument("--var", default="GRAPHS", help="JS variable name")
    args = ap.parse_args()

    graphs, stats = build(args.db, keep_exits=not args.no_exits)
    js = serialize(graphs, var=args.var)

    if args.out:
        with open(args.out, "w") as f:
            f.write(js)

    print("=== generated GRAPHS ===", file=sys.stderr)
    print(f"  graphs (layers)     : {stats['graphs']}", file=sys.stderr)
    print(f"  nodes (clips)       : {stats['nodes']}", file=sys.stderr)
    print(f"  intra-track edges   : {stats['intra']}", file=sys.stderr)
    print(f"  cross-track exits   : {stats['exits']}"
          + (" (dropped)" if args.no_exits else " (kept)"), file=sys.stderr)
    print(f"  terminal nodes      : {stats['terminal']}", file=sys.stderr)
    print(f"  endmtime==0 (unset) : {stats['endmtime0']}", file=sys.stderr)
    print(f"  unresolved targets  : {stats['unresolved']}", file=sys.stderr)
    if not args.out:
        print(js)


if __name__ == "__main__":
    main()
