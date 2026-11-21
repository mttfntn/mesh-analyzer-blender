"""Duplicate / overlap detection using spatial hashing (pure numpy, no Python loops)."""

import numpy as np

_MASK21 = np.int64(0x1FFFFF)
_U64 = np.uint64


def _pack(q):
    """Pack an (n, 3) int64 grid coordinate into one int64 key (21 bits per axis)."""
    q = q & _MASK21
    return (q[:, 0] << 42) | (q[:, 1] << 21) | q[:, 2]


def _adjacent_equal(keys):
    """Return (i, j) index pairs of elements that are neighbours in sorted order with equal keys."""
    order = np.argsort(keys)
    k = keys[order]
    same = k[1:] == k[:-1]
    return order[:-1][same], order[1:][same]


def dup_mask(keys):
    """Boolean mask of elements whose key occurs more than once."""
    m = np.zeros(len(keys), bool)
    if len(keys) < 2:
        return m
    i, j = _adjacent_equal(keys)
    m[i] = True
    m[j] = True
    return m


def doubled_verts(co, tol):
    """Find vertices within ~tol of another vertex.

    Returns (mask, pid) where pid is a "position id": vertices that sit on the same
    spot share the same pid, so edges/faces can be compared by position instead of index.
    """
    n = len(co)
    mask = np.zeros(n, bool)
    if n == 0:
        return mask, np.zeros(0, np.int64)
    scaled = co / tol
    max_d2 = (tol * 1.7321) ** 2

    base = _pack(np.floor(scaled).astype(np.int64))
    pid = np.unique(base, return_inverse=True)[1].astype(np.int64).ravel()

    for off, merge in ((0.0, False), (0.5, True)):
        keys = base if off == 0.0 else _pack(np.floor(scaled + off).astype(np.int64))
        i, j = _adjacent_equal(keys)
        if not len(i):
            continue
        d = co[i] - co[j]
        close = np.einsum("ij,ij->i", d, d) <= max_d2
        i, j = i[close], j[close]
        mask[i] = True
        mask[j] = True
        if merge:
            # Pull pids of pairs straddling a grid cell together (a few rounds handles short chains).
            for _ in range(3):
                lo = np.minimum(pid[i], pid[j])
                np.minimum.at(pid, i, lo)
                np.minimum.at(pid, j, lo)
    return mask, pid


def dup_edges(ev, pid):
    """Edges whose endpoints sit at the same positions as another edge's endpoints."""
    if len(ev) < 2:
        return np.zeros(len(ev), bool)
    a = pid[ev[:, 0]]
    b = pid[ev[:, 1]]
    lo = np.minimum(a, b)
    hi = np.maximum(a, b)
    key = lo * (int(pid.max()) + 1) + hi
    return dup_mask(key) & (lo != hi)


def dup_faces(lv, ls, lt, pid):
    """Faces whose corner positions match another face (order independent)."""
    F = len(ls)
    if F < 2:
        return np.zeros(F, bool)
    h = pid.astype(_U64)
    with np.errstate(over="ignore"):
        h1 = (h + _U64(1)) * _U64(0x9E3779B97F4A7C15)
        h1 ^= h1 >> _U64(29)
        h2 = (h + _U64(7)) * _U64(0xC2B2AE3D27D4EB4F)
        h2 ^= h2 >> _U64(31)
        s1 = np.add.reduceat(h1[lv], ls)
        s2 = np.bitwise_xor.reduceat(h2[lv], ls)
        key = s1 ^ (s2 * _U64(31)) ^ lt.astype(_U64)
    return dup_mask(key)


def overlapping_edges(co, ev, tol):
    """Edges lying on the same line as another edge and overlapping it by more than tol.

    Edges that merely touch end-to-end (normal edge loops) are not flagged.
    """
    E = len(ev)
    out = np.zeros(E, bool)
    if E < 2:
        return out
    a = co[ev[:, 0]]
    b = co[ev[:, 1]]
    d = b - a
    length = np.sqrt(np.einsum("ij,ij->i", d, d))
    valid = np.flatnonzero(length > tol)
    if len(valid) < 2:
        return out
    a, b, d, length = a[valid], b[valid], d[valid], length[valid]
    u = d / length[:, None]
    # Canonical direction: largest component positive, so opposite edges group together.
    k = np.argmax(np.abs(u), axis=1)
    u *= np.sign(u[np.arange(len(u)), k])[:, None]
    ta = np.einsum("ij,ij->i", a, u)
    tb = np.einsum("ij,ij->i", b, u)
    p0 = a - ta[:, None] * u  # closest point of the line to the origin

    qu = _pack(np.floor(u / 1e-4).astype(np.int64)).astype(_U64)
    qp = _pack(np.floor(p0 / (tol * 4.0)).astype(np.int64)).astype(_U64)
    with np.errstate(over="ignore"):
        key = qu * _U64(0x100000001B3) ^ qp
    # Dense group ids without np.unique's extra passes.
    order = np.argsort(key)
    ks = key[order]
    g = np.empty(len(key), np.float64)
    g[order] = np.cumsum(np.concatenate(([False], ks[1:] != ks[:-1])))

    lo = np.minimum(ta, tb)
    hi = np.maximum(ta, tb)
    span = 2.0 * max(np.abs(lo).max(), np.abs(hi).max()) + 1.0
    goff = g * span

    def sweep(lo, hi):
        # Sort by (group, start) via one float key: the group offset keeps groups apart.
        # An interval overlaps a previous one in its group if it starts before the running max end.
        lo_g = lo + goff
        order = np.argsort(lo_g)
        lo_s = lo_g[order]
        hi_s = hi[order] + goff[order]
        prev = np.empty_like(hi_s)
        prev[0] = -np.inf
        prev[1:] = np.maximum.accumulate(hi_s)[:-1]
        return order[lo_s < prev - tol]

    hit = np.zeros(len(valid), bool)
    hit[sweep(lo, hi)] = True
    hit[sweep(-hi, -lo)] = True  # mirrored pass flags the earlier interval of each pair
    out[valid[hit]] = True
    return out
