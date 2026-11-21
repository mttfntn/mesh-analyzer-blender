"""Behaviour fingerprint of a mesh_analyzer source tree, for before/after comparisons.

    blender -b --factory-startup --python tests/compare_behaviour.py -- <src_root> <out_dir>/<name>.json

<src_root> is a folder containing a mesh_analyzer/ package (e.g. a `git worktree` of the old
commit). Runs 88 mesh cases (11 primitives x damaged/clean x 4 modifier stacks) and records hashes
of: analysis masks at 4 merge distances, GPU buffer contents, offscreen renders, edit-mode
selections per category, timer/scope results, plus timings. Compare two outputs with
tests/diff_fingerprints.py. Use the same <out_dir> for both runs: the primitive meshes are frozen
into <out_dir>/fixtures.pkl on the first run, because Blender's UV sphere face order varies per call.
"""
import sys, json, hashlib, time
import bpy, bmesh, numpy as np
argv = sys.argv[sys.argv.index("--") + 1:]
sys.path.insert(0, argv[0])
import mesh_analyzer
from mesh_analyzer import cache, checks, draw, operators
import gpu
gpu.init()
ALL = {c[0] for c in checks.CATEGORIES}
H = lambda a: hashlib.sha1(np.ascontiguousarray(a).tobytes() + str(np.asarray(a).dtype).encode() + str(np.shape(a)).encode()).hexdigest()[:16]

recorded = []
_orig_bfs = draw.batch_for_shader
def spy(shader, typ, content, **kw):
    recorded.append((typ, {k: H(np.asarray(v)) for k, v in sorted(content.items())}))
    return _orig_bfs(shader, typ, content, **kw)
draw.batch_for_shader = spy

mesh_analyzer.register()
scene = bpy.context.scene
s = scene.mesh_analyzer
s.enabled = True
rng = np.random.default_rng(1234)

def clear_scene():
    if bpy.context.object and bpy.context.object.mode != "OBJECT":
        bpy.ops.object.mode_set(mode="OBJECT")
    for o in list(bpy.data.objects): bpy.data.objects.remove(o)

import os, pickle
FIX = os.path.join(os.path.dirname(argv[1]), "fixtures.pkl")
_fix = pickle.load(open(FIX, "rb")) if os.path.exists(FIX) else {}
_fix_dirty = False

def add(prim, location=(0, 0, 0), **kw):
    """Add a primitive from the frozen fixtures (created with bpy.ops on first use)."""
    global _fix_dirty
    key = prim + repr(sorted(kw.items()))
    if key not in _fix:
        getattr(bpy.ops.mesh, "primitive_%s_add" % prim)(**kw)
        tmp = bpy.context.active_object; me = tmp.data
        _fix[key] = ([tuple(v.co) for v in me.vertices], [tuple(e.vertices) for e in me.edges],
                     [tuple(p.vertices) for p in me.polygons])
        bpy.data.objects.remove(tmp); _fix_dirty = True
    v, e, f = _fix[key]
    me = bpy.data.meshes.new(prim)
    me.from_pydata(v, e, f); me.update()
    ob = bpy.data.objects.new(prim, me); ob.location = location
    bpy.context.scene.collection.objects.link(ob)
    bpy.context.view_layer.update()
    for o in bpy.context.view_layer.objects: o.select_set(False)
    bpy.context.view_layer.objects.active = ob; ob.select_set(True)
    return ob

def damage(ob, seed):
    """Add duplicate verts/faces, flipped faces and loose geometry with bmesh."""
    r = np.random.default_rng(seed)
    bm = bmesh.new(); bm.from_mesh(ob.data)
    bm.faces.ensure_lookup_table()
    faces = list(bm.faces)
    for f in r.choice(faces, size=min(3, len(faces)), replace=False):
        nv = [bm.verts.new(tuple(np.array(v.co) + r.normal(0, 1e-6, 3))) for v in f.verts]
        bm.faces.new(nv)
    for f in r.choice(faces, size=min(2, len(faces)), replace=False):
        f.normal_flip()
    a = bm.verts.new((5, 0, 0)); b = bm.verts.new((7, 0, 0)); c = bm.verts.new((6, 0, 0)); d = bm.verts.new((8, 0, 0))
    bm.edges.new((a, b)); bm.edges.new((c, d)); bm.verts.new((9, 9, 9))
    bm.to_mesh(ob.data); bm.free(); ob.data.update()

CASES = []
for prim, kw in [("cube", {}), ("uv_sphere", dict(segments=24, ring_count=12)), ("ico_sphere", dict(subdivisions=3)),
                 ("monkey", {}), ("torus", {}), ("cylinder", dict(vertices=12)), ("cone", dict(vertices=9)),
                 ("grid", dict(x_subdivisions=20, y_subdivisions=13)), ("circle", dict(vertices=16)),
                 ("circle", dict(vertices=10, fill_type="NGON")), ("plane", {})]:
    for dmg in (False, True):
        for mods in ((), ("SUBSURF",), ("MIRROR", "TRIANGULATE"), ("ARRAY", "SOLIDIFY")):
            CASES.append((prim, kw, dmg, mods))

out = {"cases": {}}
for idx, (prim, kw, dmg, mods) in enumerate(CASES):
    clear_scene(); cache.clear()
    ob = add(prim, **kw)
    if dmg: damage(ob, idx)
    for m in mods:
        md = ob.modifiers.new(m, m)
        if m == "SUBSURF": md.levels = 1
        if m == "MIRROR": md.use_clip = False; md.use_mirror_merge = False
    key = f"{idx}:{prim}:{dmg}:{'+'.join(mods)}"
    res = {}
    for tol in (1e-6, 1e-4, 1e-2, 0.15):
        d = checks.read_mesh(ob.data)
        m = checks.analyze(d, ALL, tol)
        res[f"base tol={tol}"] = {k: H(v) for k, v in sorted(m.items())} | {"n": {k: int(v.sum()) for k, v in m.items()}}
    dg = bpy.context.evaluated_depsgraph_get()
    for um in (False, True):
        for orient in (False, True):
            s.use_modifiers = um; s.show_orientation = orient; s.opacity = 0.7 if orient else 1.0
            e = cache.compute(ob, s, dg)
            recorded.clear()
            b = draw.build_batches(e, s)
            res[f"compute um={um} orient={orient}"] = {"counts": e.counts, "evaluated": e.evaluated,
                "batches": sorted(b), "buffers": list(recorded)}
            # Offscreen render fingerprint
            off = gpu.types.GPUOffScreen(128, 128)
            class R: width = 128; height = 128
            from mathutils import Matrix
            with off.bind():
                fb = gpu.state.active_framebuffer_get(); fb.clear(color=(0, 0, 0, 0), depth=1.0)
                gpu.matrix.load_matrix(Matrix.Rotation(0.4, 4, "X") @ Matrix.Rotation(0.3, 4, "Z") @ Matrix.Scale(0.25, 4))
                gpu.matrix.load_projection_matrix(Matrix.Identity(4))
                gpu.state.blend_set("ALPHA")
                e.batches = b
                draw._draw_entry(ob, e, s, R)
                gpu.state.blend_set("NONE")
                px = np.array(fb.read_color(0, 0, 128, 128, 4, 0, "FLOAT").to_list(), np.float32)
            off.free()
            res[f"render um={um} orient={orient}"] = H(np.round(px, 4))
    s.use_modifiers = False; s.show_orientation = False; s.opacity = 1.0
    # edit-mode live read + selection of each category
    for o in bpy.context.view_layer.objects: o.select_set(o == ob)
    bpy.context.view_layer.objects.active = ob
    bpy.ops.object.mode_set(mode="EDIT")
    sel = {}
    for cid in sorted(ALL):
        n = operators.select_categories(bpy.context, [cid], False)
        bm = bmesh.from_edit_mesh(ob.data)
        sel[cid] = [n, H(np.array([v.select for v in bm.verts])), H(np.array([e_.select for e_ in bm.edges])), H(np.array([f.select for f in bm.faces]))]
    n = operators.select_categories(bpy.context, sorted(cache.enabled_ids(s)), False)
    sel["ALL_ENABLED"] = n
    res["select"] = sel
    res["edit compute"] = cache.compute(ob, s, dg).counts
    bpy.ops.object.mode_set(mode="OBJECT")
    out["cases"][key] = res

# timer/scope path
clear_scene(); cache.clear()
a = add("cube"); b = add("monkey", location=(3, 0, 0)); c = add("torus", location=(-3, 0, 0))
for scope in ("ACTIVE", "SELECTED", "VISIBLE"):
    s.scope = scope
    for o in bpy.context.view_layer.objects: o.select_set(o in (a, b))
    bpy.context.view_layer.objects.active = b
    cache.clear(); cache._tick()
    out[f"tick {scope}"] = {k: cache.get(k).counts for k in sorted(cache._entries)}
s.scope = "SELECTED"

# timing on large mesh
clear_scene(); cache.clear()
g = add("grid", x_subdivisions=700, y_subdivisions=700)
s.show_quads = True
t = {}
def tm(label, f, n=3):
    best = 1e9
    for _ in range(n):
        t0 = time.perf_counter(); f(); best = min(best, time.perf_counter() - t0)
    t[label] = round(best * 1000, 1)
d = checks.read_mesh(g.data)
tm("read_mesh", lambda: checks.read_mesh(g.data))
tm("analyze_all", lambda: checks.analyze(d, ALL, 1e-4))
dg = bpy.context.evaluated_depsgraph_get()
e = cache.compute(g, s, dg)
tm("build_batches", lambda: draw.build_batches(e, s))
for o in bpy.context.view_layer.objects: o.select_set(o == g)
bpy.context.view_layer.objects.active = g
cache.clear(); cache._tick()
tm("tick_idle", cache._tick, n=20)
out["timing_ms"] = t
mesh_analyzer.unregister()
json.dump(out, open(argv[1], "w"), indent=1, sort_keys=True)
if _fix_dirty: pickle.dump(_fix, open(FIX, "wb"))
print("WROTE", argv[1], "cases:", len(out["cases"]), "timing:", t)
