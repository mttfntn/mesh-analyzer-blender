"""Viewport drawing: striped face shader, edge dashes, stacked vertex rings, face orientation.

build_batches() turns an Entry's masks into GPU batches; an element matching several categories
gets up to MAX_SLOTS colors. Faces cycle those colors in screen-space diagonal stripes (custom
shader), edges are split into dashes, vertices are drawn as shrinking concentric points.
draw_callback() is the SpaceView3D POST_VIEW handler. Shaders need a GPU context, so they and
the batches are created lazily inside the draw callback, never in the timer.
"""

import bpy
import gpu
import numpy as np
from gpu_extras.batch import batch_for_shader
from mathutils import Matrix

from . import cache, checks

FACE_BIAS = 0.00005
WIRE_BIAS = 0.0001
EDGE_PIECES = 6  # dashes per multi-category edge
MAX_SLOTS = 4

_shaders = {}
_handle = None


# ---------------------------------------------------------------- shaders

_STRIPE_VERT = """
void main()
{
    fA = cA; fB = cB; fC = cC; fD = cD; fN = n;
    gl_Position = mvp * vec4(pos, 1.0);
}
"""

_STRIPE_FRAG = """
void main()
{
    int count = max(int(fN + 0.5), 1);
    int i = int(floor((gl_FragCoord.x + gl_FragCoord.y) / stripe)) % count;
    vec4 c = (i == 0) ? fA : (i == 1) ? fB : (i == 2) ? fC : fD;
    FragColor = c;
}
"""

_ORIENT_VERT = """
void main()
{
    gl_Position = mvp * vec4(pos, 1.0);
}
"""

_ORIENT_FRAG = """
void main()
{
    bool front = gl_FrontFacing;
    if (flip > 0.5) {
        front = !front;
    }
    FragColor = front ? front_col : back_col;
}
"""


def _stripe_shader():
    sh = _shaders.get("stripe")
    if sh is None:
        iface = gpu.types.GPUStageInterfaceInfo("mesh_analyzer_stripe_iface")
        for name in ("fA", "fB", "fC", "fD"):
            iface.flat("VEC4", name)
        iface.flat("FLOAT", "fN")
        info = gpu.types.GPUShaderCreateInfo()
        info.push_constant("MAT4", "mvp")
        info.push_constant("FLOAT", "stripe")
        info.vertex_in(0, "VEC3", "pos")
        for i, name in enumerate(("cA", "cB", "cC", "cD"), 1):
            info.vertex_in(i, "VEC4", name)
        info.vertex_in(5, "FLOAT", "n")
        info.vertex_out(iface)
        info.fragment_out(0, "VEC4", "FragColor")
        info.vertex_source(_STRIPE_VERT)
        info.fragment_source(_STRIPE_FRAG)
        sh = _shaders["stripe"] = gpu.shader.create_from_info(info)
    return sh


def _orient_shader():
    sh = _shaders.get("orient")
    if sh is None:
        info = gpu.types.GPUShaderCreateInfo()
        info.push_constant("MAT4", "mvp")
        info.push_constant("VEC4", "front_col")
        info.push_constant("VEC4", "back_col")
        info.push_constant("FLOAT", "flip")
        info.vertex_in(0, "VEC3", "pos")
        info.fragment_out(0, "VEC4", "FragColor")
        info.vertex_source(_ORIENT_VERT)
        info.fragment_source(_ORIENT_FRAG)
        sh = _shaders["orient"] = gpu.shader.create_from_info(info)
    return sh


# ---------------------------------------------------------------- batch building

def _f32(a):
    return np.ascontiguousarray(a, dtype=np.float32)


def _slots(masks, ids, colors):
    """For elements flagged by any of `ids`: (indices, slot count, (m, 4, 4) slot colors)."""
    M = np.stack([masks[i] for i in ids], axis=1)
    cnt = M.sum(axis=1)
    sel = np.flatnonzero(cnt)
    if not len(sel):
        return sel, None, None
    Ms = M[sel]
    order = np.argsort(~Ms, axis=1, kind="stable")[:, :MAX_SLOTS]
    C = colors[order]
    if C.shape[1] < MAX_SLOTS:
        pad = np.repeat(C[:, :1], MAX_SLOTS - C.shape[1], axis=1)
        C = np.concatenate([C, pad], axis=1)
    return sel, np.minimum(cnt[sel], MAX_SLOTS), C


def _domain_ids(e, domain):
    return [cid for cid, _l, dom, *_ in checks.CATEGORIES if dom == domain and cid in e.masks]


def _colors(s, ids):
    a = np.array([tuple(getattr(s, "col_" + i)) for i in ids], np.float64)
    a[:, 3] *= s.opacity
    # Cast once here: the GPU buffers are float32 and casting before or after indexing gives equal values.
    return a.astype(np.float32)


def build_batches(e, s):
    """Build one Entry's GPU batches: {"faces", "edges", "verts" (list of rings), "orient"}."""
    d = e.data
    out = {}

    ids = _domain_ids(e, checks.FACE)
    if ids and len(d.tp):
        sel, cnt, C = _slots(e.masks, ids, _colors(s, ids))
        if len(sel):
            row = np.full(len(d.ls), -1, np.int64)
            row[sel] = np.arange(len(sel))
            r = row[d.tp]
            keep = r >= 0
            r = r[keep]
            pos = d.co32[d.tv[keep]].reshape(-1, 3)
            Cr = C[r]
            nv = np.repeat(cnt[r], 3)
            sh = _stripe_shader()
            out["faces"] = batch_for_shader(sh, "TRIS", {
                "pos": pos,
                "cA": np.repeat(Cr[:, 0], 3, axis=0), "cB": np.repeat(Cr[:, 1], 3, axis=0),
                "cC": np.repeat(Cr[:, 2], 3, axis=0), "cD": np.repeat(Cr[:, 3], 3, axis=0),
                "n": _f32(nv),
            })

    ids = _domain_ids(e, checks.EDGE)
    if ids and len(d.ev):
        sel, cnt, C = _slots(e.masks, ids, _colors(s, ids))
        if len(sel):
            ev = d.ev[sel]
            single = cnt == 1
            pos = [d.co32[ev[single]].reshape(-1, 3)]
            col = [np.repeat(C[single, 0], 2, axis=0)]
            multi = ~single
            if multi.any():
                a = d.co[ev[multi, 0]]
                b = d.co[ev[multi, 1]]
                t = np.linspace(0.0, 1.0, EDGE_PIECES + 1)
                pts = a[:, None] + (b - a)[:, None] * t[None, :, None]
                seg = np.stack([pts[:, :-1], pts[:, 1:]], axis=2)  # (m, P, 2, 3)
                slot = np.arange(EDGE_PIECES)[None, :] % cnt[multi][:, None]
                sc = np.take_along_axis(C[multi], slot[:, :, None], axis=1)  # (m, P, 4)
                pos.append(seg.reshape(-1, 3))
                col.append(np.repeat(sc.reshape(-1, 4), 2, axis=0))
            sh = gpu.shader.from_builtin("POLYLINE_FLAT_COLOR")
            out["edges"] = batch_for_shader(sh, "LINES", {
                "pos": _f32(np.concatenate(pos)),
                "color": _f32(np.concatenate(col)),
            })

    ids = _domain_ids(e, checks.VERT)
    if ids and len(d.co):
        sel, cnt, C = _slots(e.masks, ids, _colors(s, ids))
        if len(sel):
            sh = gpu.shader.from_builtin("POINT_FLAT_COLOR")
            rings = []
            for k in range(MAX_SLOTS):
                has = cnt > k
                if not has.any():
                    break
                rings.append(batch_for_shader(sh, "POINTS", {
                    "pos": d.co32[sel[has]],
                    "color": C[has, k],
                }))
            out["verts"] = rings

    if s.show_orientation and len(d.tv):
        out["orient"] = batch_for_shader(_orient_shader(), "TRIS", {
            "pos": d.co32[d.tv].reshape(-1, 3),
        })
    return out


# ---------------------------------------------------------------- drawing

def _depth_bias(bias):
    """Clip-space matrix pulling geometry toward the camera so it wins against the mesh surface."""
    t = Matrix.Identity(4)
    t[2][3] = -bias
    return t


def _draw_entry(obj, e, s, region):
    """Draw one object's batches in its world space, with a small depth bias over the mesh surface."""
    b = e.batches
    mw = obj.matrix_world
    gpu.matrix.push()
    gpu.matrix.push_projection()
    gpu.matrix.multiply_matrix(mw)
    proj = gpu.matrix.get_projection_matrix()
    mv = gpu.matrix.get_model_view_matrix()

    if "orient" in b:
        sh = _orient_shader()
        sh.bind()
        sh.uniform_float("mvp", _depth_bias(FACE_BIAS) @ proj @ mv)
        sh.uniform_float("front_col", tuple(s.orient_front))
        sh.uniform_float("back_col", tuple(s.orient_back))
        sh.uniform_float("flip", 1.0 if mw.is_negative else 0.0)
        b["orient"].draw(sh)

    if s.show_faces and "faces" in b:
        sh = _stripe_shader()
        sh.bind()
        sh.uniform_float("mvp", _depth_bias(FACE_BIAS * 2.0) @ proj @ mv)
        sh.uniform_float("stripe", max(1.0, s.stripe_width * bpy.context.preferences.system.ui_scale))
        b["faces"].draw(sh)

    gpu.matrix.load_projection_matrix(_depth_bias(WIRE_BIAS) @ proj)

    if s.show_edges and "edges" in b:
        sh = gpu.shader.from_builtin("POLYLINE_FLAT_COLOR")
        sh.bind()
        sh.uniform_float("viewportSize", (region.width, region.height))
        sh.uniform_float("lineWidth", s.edge_width)
        b["edges"].draw(sh)

    if s.show_verts and "verts" in b:
        sh = gpu.shader.from_builtin("POINT_FLAT_COLOR")
        sh.bind()
        size = s.vert_size
        for ring in b["verts"]:
            gpu.state.point_size_set(max(1.0, size))
            ring.draw(sh)
            size *= 0.62

    gpu.matrix.pop_projection()
    gpu.matrix.pop()


def draw_callback():
    """POST_VIEW draw handler: draw cached results and schedule a recompute when any is stale."""
    context = bpy.context
    s = cache.settings(context)
    if s is None or not s.enabled:
        return
    space = context.space_data
    if space is not None and not space.overlay.show_overlays:
        return

    need_compute = False
    targets = cache.target_objects(context, s)
    gpu.state.blend_set("ALPHA")
    gpu.state.depth_mask_set(False)
    gpu.state.depth_test_set("NONE" if s.xray else "LESS_EQUAL")
    try:
        for obj in targets:
            e = cache.get(obj.name)
            if e is None or e.dirty:
                need_compute = True
            if e is None or e.data is None:
                continue
            if e.batches is None:
                e.batches = build_batches(e, s)
            _draw_entry(obj, e, s, context.region)
    finally:
        gpu.state.point_size_set(1.0)
        gpu.state.depth_test_set("NONE")
        gpu.state.blend_set("NONE")
    if need_compute:
        cache.schedule()


def register():
    global _handle
    if _handle is None:
        _handle = bpy.types.SpaceView3D.draw_handler_add(draw_callback, (), "WINDOW", "POST_VIEW")


def unregister():
    global _handle
    if _handle is not None:
        bpy.types.SpaceView3D.draw_handler_remove(_handle, "WINDOW")
        _handle = None
    _shaders.clear()
