"""Headless tests. Run with:
blender -b --factory-startup --python tests/run_tests.py
"""

import os
import sys
import time
import traceback

import bpy

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import mesh_analyzer  # noqa: E402
from mesh_analyzer import cache, checks, draw, operators  # noqa: E402

ALL = {c[0] for c in checks.CATEGORIES}
TOL = 1e-4
failures = []


def check(name, got, want):
    ok = got == want
    print(f"  {'ok  ' if ok else 'FAIL'} {name}: {got} (want {want})")
    if not ok:
        failures.append(name)


def counts(me):
    m = checks.analyze(checks.read_mesh(me), ALL, TOL)
    return {k: int(v.sum()) for k, v in m.items()}


def mesh_obj(name, verts, edges=(), faces=()):
    me = bpy.data.meshes.new(name)
    me.from_pydata(verts, edges, faces)
    me.update(calc_edges=True)
    ob = bpy.data.objects.new(name, me)
    bpy.context.scene.collection.objects.link(ob)
    return ob


CUBE_V = [(-1, -1, -1), (1, -1, -1), (1, 1, -1), (-1, 1, -1), (-1, -1, 1), (1, -1, 1), (1, 1, 1), (-1, 1, 1)]
CUBE_F = [(0, 3, 2, 1), (4, 5, 6, 7), (0, 1, 5, 4), (1, 2, 6, 5), (2, 3, 7, 6), (3, 0, 4, 7)]


def test_cube():
    print("cube")
    c = counts(mesh_obj("cube", CUBE_V, faces=CUBE_F).data)
    check("quads", c["quads"], 6)
    check("pole_n", c["pole_n"], 8)
    for k in ALL - {"quads", "pole_n"}:
        check(k, c[k], 0)


def test_tri_ngon():
    print("tri + ngon plane")
    v = [(0, 0, 0), (1, 0, 0), (2, 0, 0), (2, 1, 0), (1, 1, 0), (0, 1, 0), (1.5, 1.5, 0)]
    c = counts(mesh_obj("tn", v, faces=[(0, 1, 4, 5), (1, 2, 3, 6, 4), (4, 6, 5)]).data)
    check("tris", c["tris"], 1)
    check("ngons", c["ngons"], 1)
    check("quads", c["quads"], 1)
    check("boundary", c["boundary"], 6)
    check("flipped", c["flipped"], 0)


def test_flipped():
    print("flipped face")
    f = list(CUBE_F)
    f[1] = tuple(reversed(f[1]))
    c = counts(mesh_obj("flip", CUBE_V, faces=f).data)
    check("flipped", c["flipped"], 5)


def test_duplicates():
    print("duplicate face on its own verts")
    v = CUBE_V + [CUBE_V[i] for i in (4, 5, 6, 7)]
    c = counts(mesh_obj("dup", v, faces=CUBE_F + [(8, 9, 10, 11)]).data)
    check("dup_verts", c["dup_verts"], 8)
    check("dup_faces", c["dup_faces"], 2)
    check("dup_edges", c["dup_edges"], 8)
    check("boundary", c["boundary"], 4)


def test_overlapping_edges():
    print("collinear edges")
    v = [(0, 0, 0), (2, 0, 0), (1, 0, 0), (3, 0, 0), (4, 0, 0), (5, 0, 0), (5, 0, 0), (6, 0, 0)]
    # 0-1 and 2-3 overlap; 4-5 and 6-7 only touch end to end (through doubled verts 5/6)
    c = counts(mesh_obj("col", v, edges=[(0, 1), (3, 2), (4, 5), (6, 7)]).data)
    check("overlap_edges", c["overlap_edges"], 2)
    check("wire", c["wire"], 4)
    check("dup_verts", c["dup_verts"], 2)
    check("loose_v", c["loose_v"], 0)


def test_poles():
    print("uv sphere poles")
    bpy.ops.mesh.primitive_uv_sphere_add(segments=16, ring_count=8)
    c = counts(bpy.context.active_object.data)
    check("pole_high", c["pole_high"], 2)  # 16-valence caps
    check("tris", c["tris"], 32)
    check("boundary", c["boundary"], 0)


def test_modifiers_and_edit_mode():
    print("modifiers + edit mode + select")
    s = bpy.context.scene.mesh_analyzer
    ob = mesh_obj("subd", CUBE_V, faces=CUBE_F)
    ob.modifiers.new("s", "SUBSURF").levels = 1
    for o in bpy.context.view_layer.objects:
        o.select_set(False)
    bpy.context.view_layer.objects.active = ob
    ob.select_set(True)
    dg = bpy.context.evaluated_depsgraph_get()
    s.use_modifiers = True
    e = cache.compute(ob, s, dg)
    check("evaluated", e.evaluated, True)
    check("eval tris", e.counts["tris"], 0)
    check("eval pole_n", e.counts["pole_n"], 8)
    s.use_modifiers = False
    e = cache.compute(ob, s, dg)
    check("base evaluated", e.evaluated, False)

    bpy.ops.object.mode_set(mode="EDIT")
    import bmesh
    bm = bmesh.from_edit_mesh(ob.data)
    bm.faces.ensure_lookup_table()
    bmesh.ops.poke(bm, faces=[bm.faces[0]])  # 1 quad -> 4 tris, centre vert valence 4
    bmesh.update_edit_mesh(ob.data)
    e = cache.compute(ob, s, dg)
    check("edit tris (live)", e.counts["tris"], 4)
    n = operators.select_categories(bpy.context, ["tris"], False)
    check("selected tris", n, 4)
    check("bm selected faces", sum(f.select for f in bm.faces), 4)
    bpy.ops.object.mode_set(mode="OBJECT")


def test_live_update():
    print("live update: depsgraph handler -> dirty -> timer tick")
    s = bpy.context.scene.mesh_analyzer
    ob = mesh_obj("live", CUBE_V, faces=CUBE_F)
    for o in bpy.context.view_layer.objects:
        o.select_set(o == ob)
    bpy.context.view_layer.objects.active = ob
    s.scope = "SELECTED"
    cache._tick()
    check("tracked", cache.get(ob.name) is not None, True)
    bpy.ops.object.mode_set(mode="EDIT")
    import bmesh
    bm = bmesh.from_edit_mesh(ob.data)
    bm.faces.ensure_lookup_table()
    bmesh.ops.poke(bm, faces=[bm.faces[0]])
    bmesh.update_edit_mesh(ob.data)
    bpy.context.view_layer.update()  # fires depsgraph_update_post
    check("dirty after edit", cache.get(ob.name).dirty, True)
    check("timer scheduled", bpy.app.timers.is_registered(cache._tick), True)
    cache._tick()
    check("tris after tick", cache.get(ob.name).counts["tris"], 4)
    bpy.context.view_layer.update()
    check("no self-triggered recompute", cache.get(ob.name).dirty, False)
    bpy.ops.object.mode_set(mode="OBJECT")


def test_gpu():
    print("gpu shaders + batches + offscreen draw")
    import gpu
    gpu.init()
    s = bpy.context.scene.mesh_analyzer
    s.show_orientation = True
    v = CUBE_V + [CUBE_V[i] for i in (4, 5, 6, 7)]
    ob = mesh_obj("gpu", v, faces=CUBE_F + [(8, 9, 10, 11)])
    e = cache.compute(ob, s, bpy.context.evaluated_depsgraph_get())
    b = draw.build_batches(e, s)
    check("batches", sorted(b), ["edges", "faces", "orient", "verts"])
    off = gpu.types.GPUOffScreen(256, 256)

    class R:
        width = 256
        height = 256

    from mathutils import Matrix
    with off.bind():
        fb = gpu.state.active_framebuffer_get()
        fb.clear(color=(0, 0, 0, 0))
        gpu.matrix.load_matrix(Matrix.Rotation(0.5, 4, "X") @ Matrix.Scale(0.3, 4))
        gpu.matrix.load_projection_matrix(Matrix.Identity(4))
        gpu.state.blend_set("ALPHA")
        e.batches = b
        draw._draw_entry(ob, e, s, R)
        px = fb.read_color(0, 0, 256, 256, 4, 0, "FLOAT")
    off.free()
    import numpy as np
    arr = np.array(px.to_list())
    check("pixels drawn", bool((arr[..., 3] > 0).sum() > 100), True)


def test_timing():
    print("timing (1M-face grid)")
    bpy.ops.mesh.primitive_grid_add(x_subdivisions=1001, y_subdivisions=1001)
    me = bpy.context.active_object.data
    s = bpy.context.scene.mesh_analyzer
    t = time.perf_counter()
    d = checks.read_mesh(me)
    t_read = time.perf_counter() - t
    t = time.perf_counter()
    checks.analyze(d, ALL, TOL)
    t_all = time.perf_counter() - t
    t = time.perf_counter()
    checks.analyze(d, cache.enabled_ids(s) - {"dup_verts", "dup_edges", "dup_faces", "overlap_edges"}, TOL)
    t_fast = time.perf_counter() - t
    print(f"  faces={len(d.ls)} read={t_read*1000:.0f}ms all-checks={t_all*1000:.0f}ms "
          f"topology-only={t_fast*1000:.0f}ms")


mesh_analyzer.register()
bpy.context.scene.mesh_analyzer.enabled = True
for name, fn in list(globals().items()):
    if name.startswith("test_"):
        try:
            fn()
        except Exception:
            traceback.print_exc()
            failures.append(name)
mesh_analyzer.unregister()
print("FAILURES:", failures if failures else "none")
sys.exit(1 if failures else 0)
