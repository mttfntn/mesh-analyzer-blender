import bpy
from bpy.props import BoolProperty, EnumProperty, FloatProperty, FloatVectorProperty, PointerProperty

from . import cache, checks


def _upd_analysis(self, context):
    cache.invalidate_all()
    cache.tag_redraw()


def _upd_batches(self, context):
    cache.recolor_all()


def _upd_redraw(self, context):
    cache.tag_redraw()


def _upd_enabled(self, context):
    if self.enabled:
        cache.invalidate_all()
    else:
        cache.clear()
    cache.tag_redraw()


def _color(default, update):
    return FloatVectorProperty(
        subtype="COLOR_GAMMA", size=4, min=0.0, max=1.0, default=default, update=update,
    )


_annotations = {
    "enabled": BoolProperty(
        name="Mesh Analyzer", description="Show the mesh analysis overlay", default=False,
        update=_upd_enabled,
    ),
    "use_modifiers": BoolProperty(
        name="Use Modifiers",
        description="Analyze the mesh with modifiers applied. Selection always uses the base mesh",
        default=False, update=_upd_analysis,
    ),
    "scope": EnumProperty(
        name="Objects",
        items=(
            ("ACTIVE", "Active", "Analyze only the active object"),
            ("SELECTED", "Selected", "Analyze selected mesh objects"),
            ("VISIBLE", "Visible", "Analyze every visible mesh object"),
        ),
        default="SELECTED", update=_upd_analysis,
    ),
    "xray": BoolProperty(
        name="X-Ray", description="Draw the overlay through geometry", default=False,
        update=_upd_redraw,
    ),
    "opacity": FloatProperty(
        name="Opacity", description="Global opacity multiplier", default=1.0, min=0.0, max=1.0,
        subtype="FACTOR", update=_upd_batches,
    ),
    "stripe_width": FloatProperty(
        name="Stripe Width", description="Width in pixels of the bands on multi-category faces",
        default=8.0, min=1.0, max=64.0, update=_upd_redraw,
    ),
    "edge_width": FloatProperty(
        name="Edge Width", default=3.0, min=1.0, max=12.0, update=_upd_redraw,
    ),
    "vert_size": FloatProperty(
        name="Vertex Size", default=9.0, min=2.0, max=30.0, update=_upd_redraw,
    ),
    "merge_distance": FloatProperty(
        name="Merge Distance",
        description="Distance under which vertices, edges and faces count as overlapping",
        default=0.0001, min=1e-7, max=1.0, precision=6, step=0.001, subtype="DISTANCE",
        update=_upd_analysis,
    ),
    "show_faces": BoolProperty(name="Faces", default=True, update=_upd_redraw),
    "show_edges": BoolProperty(name="Edges", default=True, update=_upd_redraw),
    "show_verts": BoolProperty(name="Vertices", default=True, update=_upd_redraw),
    "show_orientation": BoolProperty(
        name="Face Orientation", description="Color front and back faces", default=False,
        update=_upd_batches,
    ),
    "orient_front": _color((0.1, 0.35, 1.0, 0.3), _upd_redraw),
    "orient_back": _color((1.0, 0.1, 0.1, 0.45), _upd_redraw),
}

for _cid, _label, _dom, _on, _col in checks.CATEGORIES:
    _annotations["show_" + _cid] = BoolProperty(name=_label, default=_on, update=_upd_analysis)
    _annotations["col_" + _cid] = _color(_col, _upd_batches)

MeshAnalyzerSettings = type(
    "MeshAnalyzerSettings", (bpy.types.PropertyGroup,), {"__annotations__": _annotations},
)


def register():
    bpy.utils.register_class(MeshAnalyzerSettings)
    bpy.types.Scene.mesh_analyzer = PointerProperty(type=MeshAnalyzerSettings)


def unregister():
    del bpy.types.Scene.mesh_analyzer
    bpy.utils.unregister_class(MeshAnalyzerSettings)
