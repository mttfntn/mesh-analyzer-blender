"""Selection operators. They always analyze the base (unmodified) mesh, live in edit mode,
because the indices of a modifier-evaluated mesh do not map back to editable elements."""

import bmesh
import bpy
import numpy as np
from bpy.props import BoolProperty, StringProperty

from . import cache, checks


def _edit_objects(context):
    return [o for o in context.objects_in_mode_unique_data if o.type == "MESH"]


def select_categories(context, ids, extend):
    """Select every element flagged by `ids` on the base mesh of all edit-mode objects."""
    s = cache.settings(context)
    if context.mode != "EDIT_MESH":
        if context.active_object is None or context.active_object.type != "MESH":
            return 0
        bpy.ops.object.mode_set(mode="EDIT")

    domains = {checks.CAT_BY_ID[i][2] for i in ids}
    context.tool_settings.mesh_select_mode = (
        checks.VERT in domains, checks.EDGE in domains, checks.FACE in domains,
    )
    if not extend:
        bpy.ops.mesh.select_all(action="DESELECT")

    total = 0
    for obj in _edit_objects(context):
        masks = checks.analyze(cache.read_base(obj), set(ids), s.merge_distance)
        bm = bmesh.from_edit_mesh(obj.data)
        seqs = {checks.VERT: bm.verts, checks.EDGE: bm.edges, checks.FACE: bm.faces}
        for seq in seqs.values():
            seq.ensure_lookup_table()
        for cid in ids:
            seq = seqs[checks.CAT_BY_ID[cid][2]]
            for i in np.flatnonzero(masks[cid]).tolist():
                el = seq[i]
                if not el.hide:
                    el.select_set(True)
                    total += 1
        bm.select_mode = set(domains)
        bm.select_flush_mode()
        bmesh.update_edit_mesh(obj.data, loop_triangles=False, destructive=False)
    return total


# Select one category; Shift-click (invoke) extends the selection.
class MESH_ANALYZER_OT_select_category(bpy.types.Operator):
    bl_idname = "mesh_analyzer.select_category"
    bl_label = "Select Category"
    bl_options = {"REGISTER", "UNDO"}

    category: StringProperty()
    extend: BoolProperty(name="Extend", description="Add to the current selection")

    @classmethod
    def description(cls, context, props):
        label = checks.CAT_BY_ID.get(props.category, ("", "elements"))[1]
        return f"Select {label} (Shift-click to add to the selection)"

    @classmethod
    def poll(cls, context):
        return context.active_object is not None and context.active_object.type == "MESH"

    def invoke(self, context, event):
        self.extend = event.shift
        return self.execute(context)

    def execute(self, context):
        if self.category not in checks.CAT_BY_ID:
            return {"CANCELLED"}
        n = select_categories(context, [self.category], self.extend)
        self.report({"INFO"}, f"Selected {n} {checks.CAT_BY_ID[self.category][1].lower()}")
        return {"FINISHED"}


# Select the union of all enabled categories.
class MESH_ANALYZER_OT_select_all_flagged(bpy.types.Operator):
    bl_idname = "mesh_analyzer.select_all_flagged"
    bl_label = "Select All Flagged"
    bl_description = "Select every element flagged by an enabled check (Shift-click to extend)"
    bl_options = {"REGISTER", "UNDO"}

    extend: BoolProperty(name="Extend")

    @classmethod
    def poll(cls, context):
        return context.active_object is not None and context.active_object.type == "MESH"

    def invoke(self, context, event):
        self.extend = event.shift
        return self.execute(context)

    def execute(self, context):
        ids = sorted(cache.enabled_ids(cache.settings(context)))
        if not ids:
            self.report({"WARNING"}, "No checks enabled")
            return {"CANCELLED"}
        n = select_categories(context, ids, self.extend)
        self.report({"INFO"}, f"Selected {n} flagged elements")
        return {"FINISHED"}


class MESH_ANALYZER_OT_deselect(bpy.types.Operator):
    bl_idname = "mesh_analyzer.deselect"
    bl_label = "Deselect All"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        return context.mode == "EDIT_MESH"

    def execute(self, context):
        bpy.ops.mesh.select_all(action="DESELECT")
        return {"FINISHED"}


# Drop the cache and recompute everything, e.g. after changes the handlers did not see.
class MESH_ANALYZER_OT_refresh(bpy.types.Operator):
    bl_idname = "mesh_analyzer.refresh"
    bl_label = "Refresh"
    bl_description = "Recompute the analysis"

    def execute(self, context):
        cache.clear()
        cache.schedule()
        cache.tag_redraw()
        return {"FINISHED"}


classes = (
    MESH_ANALYZER_OT_select_category,
    MESH_ANALYZER_OT_select_all_flagged,
    MESH_ANALYZER_OT_deselect,
    MESH_ANALYZER_OT_refresh,
)
