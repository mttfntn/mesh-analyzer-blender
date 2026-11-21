"""Mesh Analyzer: live, color-coded topology overlay for the 3D Viewport."""

import bpy

from . import cache, draw, operators, props, ui

_handlers = (
    (bpy.app.handlers.depsgraph_update_post, cache.on_depsgraph_update),
    (bpy.app.handlers.load_post, cache.on_reset),
    (bpy.app.handlers.undo_post, cache.on_undo),
    (bpy.app.handlers.redo_post, cache.on_undo),
)


def register():
    props.register()
    for cls in operators.classes + ui.classes:
        bpy.utils.register_class(cls)
    for lst, fn in _handlers:
        if fn not in lst:
            lst.append(fn)
    draw.register()


def unregister():
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
