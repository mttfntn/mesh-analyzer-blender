"""Sidebar UI in the 3D Viewport, "Analyzer" tab: a main panel with global options and one
sub-panel per domain (faces, edges, vertices) generated from checks.CATEGORIES."""

import bpy

from . import cache, checks


def _totals(context, s):
    """Sum cached counts over the target objects; also report whether any used modifiers."""
    totals = {}
    evaluated = False
    for obj in cache.target_objects(context, s):
        e = cache.get(obj.name)
        if e is None:
            continue
        evaluated |= e.evaluated
        for k, v in e.counts.items():
            totals[k] = totals.get(k, 0) + v
    return totals, evaluated


class VIEW3D_PT_mesh_analyzer(bpy.types.Panel):
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "Analyzer"
    bl_label = "Mesh Analyzer"

    def draw_header(self, context):
        self.layout.prop(context.scene.mesh_analyzer, "enabled", text="")

    def draw(self, context):
        s = context.scene.mesh_analyzer
        layout = self.layout
        layout.use_property_split = True
        layout.use_property_decorate = False

        col = layout.column()
        col.active = s.enabled
        col.prop(s, "scope")
        col.prop(s, "use_modifiers")
        col.prop(s, "xray")
        col.prop(s, "opacity", slider=True)
        col.prop(s, "merge_distance")

        row = layout.row(align=True)
        row.prop(s, "show_faces", text="Faces", toggle=True, icon=checks.DOMAIN_ICONS[checks.FACE])
        row.prop(s, "show_edges", text="Edges", toggle=True, icon=checks.DOMAIN_ICONS[checks.EDGE])
        row.prop(s, "show_verts", text="Verts", toggle=True, icon=checks.DOMAIN_ICONS[checks.VERT])

        row = layout.row(align=True)
        row.scale_y = 1.3
        row.operator("mesh_analyzer.select_all_flagged", icon="RESTRICT_SELECT_OFF")
        row.operator("mesh_analyzer.deselect", text="", icon="X")
        row.operator("mesh_analyzer.refresh", text="", icon="FILE_REFRESH")


# Shared layout of the Faces / Edges / Vertices sub-panels: toggle, label, count, color, select.
class _DomainPanel:
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "Analyzer"
    bl_parent_id = "VIEW3D_PT_mesh_analyzer"
    domain = None

    def draw_header(self, context):
        self.layout.label(icon=checks.DOMAIN_ICONS[self.domain])

    def draw(self, context):
        s = context.scene.mesh_analyzer
        totals, evaluated = _totals(context, s)
        col = self.layout.column(align=True)
        col.active = s.enabled
        for cid, label, dom, *_ in checks.CATEGORIES:
            if dom != self.domain:
                continue
            on = getattr(s, "show_" + cid)
            row = col.row(align=True)
            row.prop(s, "show_" + cid, text="")
            sub = row.row(align=True)
            sub.active = on
            sub.label(text=label)
            count = totals.get(cid)
            sub.label(text="-" if count is None else str(count))
            sub.prop(s, "col_" + cid, text="")
            op = sub.operator("mesh_analyzer.select_category", text="", icon="RESTRICT_SELECT_OFF")
            op.category = cid
        if evaluated:
            self.layout.label(text="Counts include modifiers; selection uses the base mesh", icon="INFO")


class VIEW3D_PT_mesh_analyzer_faces(_DomainPanel, bpy.types.Panel):
    bl_label = "Faces"
    domain = checks.FACE


class VIEW3D_PT_mesh_analyzer_edges(_DomainPanel, bpy.types.Panel):
    bl_label = "Edges"
    domain = checks.EDGE


class VIEW3D_PT_mesh_analyzer_verts(_DomainPanel, bpy.types.Panel):
    bl_label = "Vertices"
    domain = checks.VERT


class VIEW3D_PT_mesh_analyzer_display(bpy.types.Panel):
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "Analyzer"
    bl_parent_id = "VIEW3D_PT_mesh_analyzer"
    bl_label = "Display"
    bl_options = {"DEFAULT_CLOSED"}

    def draw(self, context):
        s = context.scene.mesh_analyzer
        layout = self.layout
        layout.use_property_split = True
        layout.use_property_decorate = False
        layout.active = s.enabled
        layout.prop(s, "stripe_width")
        layout.prop(s, "edge_width")
        layout.prop(s, "vert_size")
        layout.separator()
        layout.prop(s, "show_orientation")
        col = layout.column()
        col.active = s.show_orientation
        col.prop(s, "orient_front", text="Front")
        col.prop(s, "orient_back", text="Back")


classes = (
    VIEW3D_PT_mesh_analyzer,
    VIEW3D_PT_mesh_analyzer_faces,
    VIEW3D_PT_mesh_analyzer_edges,
    VIEW3D_PT_mesh_analyzer_verts,
    VIEW3D_PT_mesh_analyzer_display,
)
