"""Mesh Analyzer: live, color-coded topology overlay for the 3D Viewport.

Module map:
    checks    category table, mesh -> numpy read, per-category boolean masks
    overlap   spatial-hash detection of doubled verts and duplicate/overlapping edges and faces
    cache     per-object results, dirty tracking from depsgraph handlers, debounced timer recompute
    draw      GPU shaders and batches, the POST_VIEW draw handler
    props     Scene.mesh_analyzer settings (one toggle + color per category)
    operators select-by-category, select all flagged, deselect, refresh
    ui        sidebar panels in the "Analyzer" tab

Flow: edit -> depsgraph_update_post marks the object dirty -> timer recomputes masks
-> draw callback rebuilds GPU batches if needed and draws them.
"""

import bpy

from . import cache, draw, operators, props, ui

_handlers = (
    (bpy.app.handlers.depsgraph_update_post, cache.on_depsgraph_update),
    (bpy.app.handlers.load_post, cache.on_reset),
    (bpy.app.handlers.undo_post, cache.on_undo),
    (bpy.app.handlers.redo_post, cache.on_undo),
)


def register():
    """Register settings, operators, panels, app handlers and the viewport draw handler."""
    props.register()
    for cls in operators.classes + ui.classes:
        bpy.utils.register_class(cls)
    for lst, fn in _handlers:
        if fn not in lst:
            lst.append(fn)
    draw.register()


def unregister():
    """Undo register() in reverse order and free the temporary mesh used for edit-mode reads."""
    draw.unregister()
    for lst, fn in _handlers:
        if fn in lst:
            lst.remove(fn)
    if bpy.app.timers.is_registered(cache._tick):
        bpy.app.timers.unregister(cache._tick)
    for cls in reversed(operators.classes + ui.classes):
        bpy.utils.unregister_class(cls)
    props.unregister()
    cache.clear()
    cache.free_tmp_mesh()
