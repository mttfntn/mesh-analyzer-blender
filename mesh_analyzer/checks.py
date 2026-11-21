"""Mesh reading and topology analysis. Everything is vectorized with numpy."""

import numpy as np

from . import overlap

FACE, EDGE, VERT = "FACE", "EDGE", "VERT"

DOMAIN_ICONS = {FACE: "FACESEL", EDGE: "EDGESEL", VERT: "VERTEXSEL"}

# id, label, domain, enabled by default, default color (sRGB + opacity)
CATEGORIES = (
    ("tris", "Triangles", FACE, True, (1.0, 0.85, 0.1, 0.55)),
    ("quads", "Quads", FACE, False, (0.3, 0.6, 1.0, 0.3)),
    ("ngons", "N-gons", FACE, True, (1.0, 0.15, 0.15, 0.6)),
    ("flipped", "Inconsistent Normals", FACE, True, (0.85, 0.2, 1.0, 0.6)),
    ("zero_area", "Zero-Area Faces", FACE, True, (1.0, 0.5, 0.0, 0.8)),
    ("dup_faces", "Overlapping Faces", FACE, True, (0.0, 1.0, 1.0, 0.7)),
    ("boundary", "Boundary Edges", EDGE, True, (0.2, 0.55, 1.0, 1.0)),
    ("multi_face", "Non-Manifold (3+ faces)", EDGE, True, (1.0, 0.0, 0.45, 1.0)),
    ("wire", "Loose Edges", EDGE, True, (1.0, 1.0, 0.0, 1.0)),
    ("zero_len", "Zero-Length Edges", EDGE, True, (1.0, 0.5, 0.0, 1.0)),
    ("dup_edges", "Duplicate Edges", EDGE, True, (0.0, 1.0, 1.0, 1.0)),
    ("overlap_edges", "Overlapping Collinear Edges", EDGE, True, (0.1, 1.0, 0.4, 1.0)),
    ("pole_n", "N-Poles (3 edges)", VERT, True, (0.25, 0.55, 1.0, 1.0)),
    ("pole_e", "E-Poles (5 edges)", VERT, True, (1.0, 0.55, 0.1, 1.0)),
    ("pole_high", "Poles (6+ edges)", VERT, True, (1.0, 0.1, 0.1, 1.0)),
    ("nonmanifold_v", "Non-Manifold Vertices", VERT, False, (1.0, 0.0, 0.6, 1.0)),
    ("loose_v", "Loose Vertices", VERT, True, (1.0, 1.0, 0.0, 1.0)),
    ("dup_verts", "Doubled Vertices", VERT, True, (0.0, 1.0, 1.0, 1.0)),
)

CAT_BY_ID = {c[0]: c for c in CATEGORIES}


class MeshData:
    """Flat numpy copy of the mesh arrays needed for analysis and drawing."""

    __slots__ = ("co", "co32", "ev", "ls", "lt", "lv", "le", "tv", "tp")

    @property
    def counts(self):
        return len(self.co), len(self.ev), len(self.ls)


def _int_attr(me, name, collection, prop, size, comps=1):
    """Read an int array through the fast attribute API, falling back to the RNA collection."""
    out = np.empty(size * comps, np.int32)
    attr = me.attributes.get(name)
    if attr is not None and len(attr.data) == size:
        attr.data.foreach_get("value", out)
    else:
        collection.foreach_get(prop, out)
    return out.reshape(-1, comps) if comps > 1 else out


def read_mesh(me):
    d = MeshData()
    V, E, F, L = len(me.vertices), len(me.edges), len(me.polygons), len(me.loops)

    co = np.empty(V * 3, np.float32)
    pos = me.attributes.get("position")
    if pos is not None and len(pos.data) == V:
        pos.data.foreach_get("vector", co)
    else:
        me.vertices.foreach_get("co", co)
    d.co32 = co.reshape(-1, 3)  # as read; reused for GPU buffers without another conversion
    d.co = d.co32.astype(np.float64)

    d.ev = _int_attr(me, ".edge_verts", me.edges, "vertices", E, 2)
    d.lv = _int_attr(me, ".corner_vert", me.loops, "vertex_index", L)
    d.le = _int_attr(me, ".corner_edge", me.loops, "edge_index", L)

    d.ls = np.empty(F, np.int32)
    me.polygons.foreach_get("loop_start", d.ls)
    d.lt = np.diff(d.ls, append=np.int32(L)).astype(np.int32)

    me.calc_loop_triangles()
    T = len(me.loop_triangles)
    tl = np.empty(T * 3, np.int32)
    me.loop_triangles.foreach_get("loops", tl)
    d.tv = d.lv[tl].reshape(-1, 3)
    d.tp = np.empty(T, np.int32)
    me.loop_triangle_polygons.foreach_get("value", d.tp)
    return d


def analyze(d, enabled, tol):
    """Return {category_id: bool mask} for every id in `enabled`."""
    V, E, F = d.counts
    want = enabled.__contains__
    m = {}

    lt = d.lt
    if want("tris"):
        m["tris"] = lt == 3
    if want("quads"):
        m["quads"] = lt == 4
    if want("ngons"):
        m["ngons"] = lt > 4

    efc = np.bincount(d.le, minlength=E) if E else np.zeros(0, np.int64)
    if want("boundary"):
        m["boundary"] = efc == 1
    if want("multi_face"):
        m["multi_face"] = efc > 2
    if want("wire"):
        m["wire"] = efc == 0

    if want("zero_len"):
        dv = d.co[d.ev[:, 1]] - d.co[d.ev[:, 0]]
        m["zero_len"] = np.einsum("ij,ij->i", dv, dv) <= tol * tol

    if want("zero_area"):
        p = d.co[d.tv]
        cr = np.cross(p[:, 1] - p[:, 0], p[:, 2] - p[:, 0])
        tri_area = 0.5 * np.sqrt(np.einsum("ij,ij->i", cr, cr))
        m["zero_area"] = np.bincount(d.tp, weights=tri_area, minlength=F) <= tol * tol

    if want("flipped"):
        m["flipped"] = _inconsistent_winding(d, efc, F)

    if any(map(want, ("pole_n", "pole_e", "pole_high", "nonmanifold_v", "loose_v"))):
        valence = np.bincount(d.ev.ravel(), minlength=V) if E else np.zeros(V, np.int64)
        on_nm = np.zeros(V, bool)
        on_nm[d.ev[efc != 2].ravel()] = True
        interior = ~on_nm
        if want("pole_n"):
            m["pole_n"] = (valence == 3) & interior
        if want("pole_e"):
            m["pole_e"] = (valence == 5) & interior
        if want("pole_high"):
            m["pole_high"] = (valence >= 6) & interior
        if want("nonmanifold_v"):
            m["nonmanifold_v"] = on_nm
        if want("loose_v"):
            m["loose_v"] = valence == 0

    if any(map(want, ("dup_verts", "dup_edges", "dup_faces"))):
        dv_mask, pid = overlap.doubled_verts(d.co, tol)
        if want("dup_verts"):
            m["dup_verts"] = dv_mask
        if want("dup_edges"):
            m["dup_edges"] = overlap.dup_edges(d.ev, pid)
        if want("dup_faces"):
            m["dup_faces"] = overlap.dup_faces(d.lv, d.ls, d.lt, pid)

    if want("overlap_edges"):
        m["overlap_edges"] = overlap.overlapping_edges(d.co, d.ev, tol)

    return m


def _inconsistent_winding(d, efc, F):
    """Faces next to a manifold edge that both faces traverse in the same direction."""
    out = np.zeros(F, bool)
    if F < 2:
        return out
    # First and last corner on each edge, without sorting: later writes win on duplicate indices.
    L = len(d.le)
    idx = np.arange(L)
    first = np.empty(len(efc), np.int64)
    last = np.empty(len(efc), np.int64)
    first[d.le[::-1]] = idx[::-1]
    last[d.le] = idx
    manifold = np.flatnonzero(efc == 2)
    a = first[manifold]
    b = last[manifold]
    # Consistently wound neighbours walk a shared edge in opposite directions, so their
    # loops on that edge start at different vertices. Same start vertex = flipped pair.
    bad = d.lv[a] == d.lv[b]
    if bad.any():
        face_of_loop = np.repeat(np.arange(F), d.lt)
        out[face_of_loop[a[bad]]] = True
        out[face_of_loop[b[bad]]] = True
    return out
