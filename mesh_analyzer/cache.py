"""Per-object analysis cache, dirty tracking and debounced recompute."""

import bmesh
import bpy
from bpy.app.handlers import persistent

from . import checks

_DEBOUNCE = 0.03
_TMP_MESH = ".mesh_analyzer_tmp"


class Entry:
    __slots__ = ("dirty", "data", "masks", "counts", "batches", "evaluated")

    def __init__(self):
        self.dirty = True
        self.data = None
        self.masks = {}
        self.counts = {}
        self.batches = None
        self.evaluated = False


_entries = {}


def get(name):
    return _entries.get(name)


def clear():
    _entries.clear()


def settings(context=None):
    scene = (context or bpy.context).scene
    return scene.mesh_analyzer if scene else None


def enabled_ids(s):
    return {cid for cid, *_ in checks.CATEGORIES if getattr(s, "show_" + cid)}


def target_objects(context, s):
    vl = context.view_layer
    if vl is None:
        return []
    if s.scope == "ACTIVE":
        obs = [vl.objects.active] if vl.objects.active else []
    elif s.scope == "SELECTED":
        obs = list(context.selected_objects)
        act = vl.objects.active
        if act is not None and act not in obs:
            obs.append(act)
    else:
        obs = vl.objects
    return [o for o in obs if o.type == "MESH" and o.visible_get()]


def tag_redraw():
    wm = bpy.context.window_manager
    if wm is None:
        return
    for win in wm.windows:
        for area in win.screen.areas:
            if area.type == "VIEW_3D":
                area.tag_redraw()


# ---------------------------------------------------------------- mesh sources

def _tmp_mesh():
    me = bpy.data.meshes.get(_TMP_MESH)
    if me is None:
        me = bpy.data.meshes.new(_TMP_MESH)
    return me


def free_tmp_mesh():
    me = bpy.data.meshes.get(_TMP_MESH)
    if me is not None:
        bpy.data.meshes.remove(me)


def _has_modifiers(obj):
    in_edit = obj.mode == "EDIT"
    return any(m.show_viewport and (not in_edit or m.show_in_editmode) for m in obj.modifiers)


def read_base(obj):
    """Original (unmodified) topology, live even in edit mode. Indices match bmesh/mesh."""
    if obj.mode == "EDIT":
        tmp = _tmp_mesh()
        bmesh.from_edit_mesh(obj.data).to_mesh(tmp)
        try:
            return checks.read_mesh(tmp)
        finally:
            tmp.clear_geometry()
    return checks.read_mesh(obj.data)


def read_source(obj, use_modifiers, depsgraph):
    if use_modifiers and _has_modifiers(obj):
        ob_eval = obj.evaluated_get(depsgraph)
        me = ob_eval.to_mesh()
        try:
            return checks.read_mesh(me), True
        finally:
            ob_eval.to_mesh_clear()
    return read_base(obj), False


# ---------------------------------------------------------------- recompute

def compute(obj, s, depsgraph):
    e = _entries.get(obj.name)
    if e is None:
        e = _entries[obj.name] = Entry()
    data, evaluated = read_source(obj, s.use_modifiers, depsgraph)
    e.data = data
    e.evaluated = evaluated
    e.masks = checks.analyze(data, enabled_ids(s), s.merge_distance)
    e.counts = {k: int(v.sum()) for k, v in e.masks.items()}
    e.batches = None
    e.dirty = False
    return e


def _tick():
    context = bpy.context
    s = settings(context)
    if s is None or not s.enabled:
        return None
    depsgraph = context.evaluated_depsgraph_get()
    targets = target_objects(context, s)
    keep = set()
    for obj in targets:
        keep.add(obj.name)
        e = _entries.get(obj.name)
        if e is None or e.dirty:
            try:
                compute(obj, s, depsgraph)
            except ReferenceError:
                pass
    for name in list(_entries):
        if name not in keep:
            del _entries[name]
    tag_redraw()
    return None


def schedule():
    if not bpy.app.timers.is_registered(_tick):
        bpy.app.timers.register(_tick, first_interval=_DEBOUNCE)


def invalidate_all():
    for e in _entries.values():
        e.dirty = True
    schedule()


def recolor_all():
    for e in _entries.values():
        e.batches = None
    tag_redraw()


# ---------------------------------------------------------------- handlers

@persistent
def on_depsgraph_update(scene, depsgraph):
    s = getattr(scene, "mesh_analyzer", None)
    if s is None or not s.enabled or not _entries:
        return
    meshes = set()
    hit = False
    for u in depsgraph.updates:
        idd = getattr(u.id, "original", u.id)
        if isinstance(idd, bpy.types.Object):
            e = _entries.get(idd.name)
            if e is not None and u.is_updated_geometry:
                e.dirty = hit = True
        elif isinstance(idd, bpy.types.Mesh):
            meshes.add(idd.name)
    if meshes:
        for name, e in _entries.items():
            ob = bpy.data.objects.get(name)
            if ob is not None and ob.data is not None and ob.data.name in meshes:
                e.dirty = hit = True
    if hit:
        schedule()


@persistent
def on_reset(*_args):
    clear()
    s = settings()
    if s is not None and s.enabled:
        schedule()


@persistent
def on_undo(*_args):
    invalidate_all()
