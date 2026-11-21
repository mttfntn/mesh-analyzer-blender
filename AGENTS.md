# AGENTS.md: Mesh Analyzer

Blender 5.3 extension: live topology overlay (tris/ngons/poles/non-manifold/overlaps) with
per-check toggle, color, select. Human-oriented details: HANDOVER.md.

## Commands

```bash
# tests (exit 0 + "FAILURES: none" = pass); isolate from the user profile
BLENDER_USER_RESOURCES=/tmp/ma-profile blender -b --factory-startup --python tests/run_tests.py
# same on each GPU backend
blender -b --factory-startup --gpu-backend vulkan --python tests/run_tests.py
# validate manifest / build package
blender --factory-startup --command extension validate mesh_analyzer
blender --factory-startup --command extension build --source-dir mesh_analyzer --output-dir dist
# behaviour comparison before/after a refactor (same out dir for both runs)
git worktree add ../ma-old <commit>
blender -b --factory-startup --python tests/compare_behaviour.py -- ../ma-old out/old.json
blender -b --factory-startup --python tests/compare_behaviour.py -- . out/new.json
python tests/diff_fingerprints.py out/old.json out/new.json   # must print no DIFF lines
```

Windows install of the user's Blender: `C:\Program Files\Blender Foundation\Blender 5.3\blender.exe`.

## Architecture / data flow

```
edit ─► depsgraph_update_post (cache.on_depsgraph_update) ─► entry.dirty=True ─► timers(30 ms) cache._tick
      ─► cache.compute ─► checks.read_mesh (Mesh→numpy) ─► checks.analyze (masks per check)
draw  ─► draw.draw_callback (POST_VIEW) ─► draw.build_batches (lazy, needs GPU ctx) ─► _draw_entry
select ─► operators.select_categories ─► cache.read_base + checks.analyze ─► BMesh select_set
```

- `checks.CATEGORIES` drives everything: props (`show_<id>`, `col_<id>`), UI rows, draw colors, selection domain.
- Settings live on `Scene.mesh_analyzer`. Update callbacks: analysis → `cache.invalidate_all`, colors/opacity/orientation → `cache.recolor_all` (rebuild batches only), sizes → redraw only.
- `MeshData` fields: `co` (float64), `co32` (float32 as read, used for GPU buffers), `ev`, `ls`, `lt`, `lv`, `le`, `tv`, `tp`.

## Rules

- No Python loops over mesh elements in analysis or batch building; use numpy. (Selection is the one exception: BMesh has no bulk API.)
- Create GPU shaders/batches only inside the draw callback, never in the timer or handlers.
- Selection must use the base mesh (`cache.read_base`), never the evaluated mesh.
- Operator/Panel classes: use `#` comments, not docstrings (Blender shows docstrings as tooltips).
- Keep `LICENSE` and `mesh_analyzer/LICENSE` identical (CI checks with `cmp`).
- Keep the CI matrix equal to the manifest's `blender_version_min`/`max` range.
- Any optimization must leave `compare_behaviour.py` output identical; GPU buffers are compared by dtype and bytes.

## Pitfalls found in this project

- `bpy.ops.mesh.primitive_uv_sphere_add` gives a different face order per call in 5.3 → never compare index-level results of primitives across runs; freeze meshes (the harness does).
- `gpu` needs `gpu.init()` in background mode; verified headless on Windows (OpenGL and Vulkan); CI runs it with Mesa under Xvfb on Linux.
- `Mesh.attributes["position"]` is missing for a mesh that is in edit mode → `read_mesh` falls back to `vertices.foreach_get`. Read edit meshes via `cache.read_base` (BMesh → tmp mesh).
- `loop_triangles` property is `polygon_index` (not `polygon`); faster: `Mesh.loop_triangle_polygons`.
- Int attributes `.corner_vert`, `.corner_edge`, `.edge_verts` are read via `attributes[...].data.foreach_get("value")`, 1.7–3.5× faster than `loops.foreach_get` (measured on 4M corners).
- `_inconsistent_winding` relies on in-order application of repeated fancy indices.
- pyflakes false positive: `undefined name 'Extend'` from `BoolProperty(name="Extend")` annotations.
- Background-mode `view_layer.objects` can hold a stale `None` right after `bpy.data.objects.remove`; call `view_layer.update()` first.

## How changes were verified (handover pass, 2026-11)

- Baseline: `tests/run_tests.py` on 5.3.0 → 44/44 checks. After: 49/49 (5 new live-update checks), OpenGL and Vulkan.
- `compare_behaviour.py`, original commit `9ddab96` vs final: 0 differences in 88 cases on both backends; OpenGL vs Vulkan also identical. Two runs of the same code: 0 differences (determinism check).
- Speed (1M-face grid, all faces flagged): `build_batches` 927 → 512 ms; other stages unchanged.

## Release checklist

1. Bump `version` in `mesh_analyzer/blender_manifest.toml`.
2. Update static badges in `README.md` (repo is private: version, release).
3. Push to `main`, wait for the `tests` workflow to pass.
4. `git tag -a vX.Y.Z -m "Title" -m "notes"` then `git push origin vX.Y.Z` (annotated tag required; must equal manifest version).
5. Check the release has `mesh_analyzer-X.Y.Z.zip`; install it in a scratch profile and run a smoke test.

## Git setup

- Remote `origin`: https://github.com/mttfntn/mesh-analyzer-blender.git (private). Default branch `main`.
- `.gitattributes` forces LF; `.gitignore` excludes `__pycache__/`, `*.pyc`, `dist/`.
- Commit trailer used: `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.
- Not a fork; no upstream remote.
