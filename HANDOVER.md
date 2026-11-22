# Mesh Analyzer: handover

## What it is

A Blender extension (add-on) that colors problem topology live in the 3D Viewport:
triangles, quads, N-gons, inconsistent normals, zero-area faces, overlapping faces, boundary and
non-manifold edges, loose and zero-length edges, duplicate and overlapping collinear edges, N/E/high
poles, non-manifold, loose and doubled vertices. Each check has its own toggle, color, opacity and
a select button. Elements that match several checks are drawn with diagonal color stripes. It
updates while you edit, can analyze the mesh with or without modifiers, and has a face orientation
overlay.

Not a fork: written from scratch for this repository. (`mftk_mesh_analyzer`, an older add-on by the
same author that may be installed alongside, is a separate project and shares no code or identifiers.)

## What you need

| | |
|---|---|
| Blender | **5.3.x** (the manifest allows `5.3.0 <= version < 5.4.0`) |
| Python packages | none: only `bpy`, `bmesh`, `gpu`, `mathutils` and the `numpy` bundled with Blender |
| To run tests | a Blender 5.3 binary; a GPU or software OpenGL (CI uses Mesa under Xvfb) |
| To release | push access to the GitHub repo; `gh` CLI is handy but optional |

## Code layout

| File | Role |
|---|---|
| `mesh_analyzer/__init__.py` | `register()` / `unregister()`: settings, classes, app handlers, draw handler |
| `mesh_analyzer/checks.py` | `CATEGORIES` table (the single list of checks), `read_mesh()` (Mesh -> numpy), `analyze()` (numpy -> one bool mask per check) |
| `mesh_analyzer/overlap.py` | Spatial hashing for doubled verts, duplicate edges/faces, overlapping collinear edges |
| `mesh_analyzer/cache.py` | Per-object results, depsgraph handler that marks objects dirty, 30 ms debounced timer that recomputes |
| `mesh_analyzer/draw.py` | GPU shaders (striped faces, face orientation), batch building, the viewport draw callback |
| `mesh_analyzer/props.py` | `Scene.mesh_analyzer` settings, generated per check from `CATEGORIES` |
| `mesh_analyzer/operators.py` | Select category / select all flagged / deselect / refresh |
| `mesh_analyzer/ui.py` | Sidebar panels, tab "Analyzer" |
| `mesh_analyzer/blender_manifest.toml` | Extension id, version, supported Blender range, license |
| `mesh_analyzer/LICENSE`, `LICENSE` | GPL-3.0-or-later (same file twice: the package only contains `mesh_analyzer/`) |
| `tests/run_tests.py` | Headless test suite (counts per check, modifiers, edit mode, selection, live update, GPU draw, timing) |
| `tests/compare_behaviour.py`, `tests/diff_fingerprints.py` | Before/after behaviour comparison for refactors |
| `.github/workflows/ci.yml` | Tests on Blender 5.3, builds the package, publishes releases from tags |
| `.github/scripts/get_blender.sh` | Downloads Blender for CI with retries and mirror fallback |

## How it works

1. **Read.** `checks.read_mesh()` copies positions, edges, corners and loop triangles into numpy
   arrays (fast attribute API, no per-element Python). In edit mode the live BMesh is first written
   into a hidden temporary mesh (`.mesh_analyzer_tmp`); with "Use Modifiers" the evaluated mesh is read.
2. **Analyze.** `checks.analyze()` computes a boolean mask per enabled check, all vectorized.
   Overlap checks quantize positions by the merge distance and compare packed integer keys.
3. **Cache.** `cache.compute()` stores masks and counts per object name. `on_depsgraph_update` only
   marks changed objects dirty and schedules `_tick()` through `bpy.app.timers`, so a burst of edits
   becomes one recompute.
4. **Draw.** `draw.draw_callback()` (POST_VIEW) builds GPU batches lazily from the masks and draws
   them with a small depth bias. Elements matching several checks get up to 4 colors: stripes on
   faces (custom shader using `gl_FragCoord`), dashes on edges, concentric points on vertices.
   Color and opacity changes only rebuild batches; they do not re-analyze.
5. **Select.** Operators re-analyze the *base* mesh (modifier results do not map back to editable
   elements) and select through BMesh in edit mode.

## Making a change

- **Add a check:** add a row to `CATEGORIES` in `checks.py` (id, label, domain, default on, color),
  compute `m["<id>"]` in `analyze()` guarded by `want("<id>")`, add a case to `tests/run_tests.py`.
  Properties, UI rows, drawing and selection pick it up automatically.
- **Change drawing:** `draw.py`. Shaders and batches may only be created inside the draw callback
  (they need a GPU context).
- **Refactor or optimize:** run the comparison (below) before and after; it must report no `DIFF` lines.

## Running the tests

```bash
blender -b --factory-startup --python tests/run_tests.py
```

Exit code 0 and `FAILURES: none` means pass. To keep your own Blender profile out of it, point
`BLENDER_USER_RESOURCES` at an empty folder. To try both GPU backends, add
`--gpu-backend opengl` or `--gpu-backend vulkan`.

Before/after comparison (e.g. old = a commit, new = the working tree):

```bash
git worktree add ../ma-old <old-commit>
blender -b --factory-startup --python tests/compare_behaviour.py -- ../ma-old out/old.json
blender -b --factory-startup --python tests/compare_behaviour.py -- . out/new.json
python tests/diff_fingerprints.py out/old.json out/new.json
git worktree remove ../ma-old
```

Use the same `out/` folder for both runs (it holds the frozen test meshes).

## Making a release

1. Set `version` in `mesh_analyzer/blender_manifest.toml` (e.g. `1.0.1`).
2. Nothing to change in `README.md`: its release, license and language badges read GitHub, and the Blender badge reads the manifest.
3. Commit and push to `main`; wait for the `tests` workflow to pass.
4. Create an **annotated** tag whose message is the release notes, and push it:
   ```bash
   git tag -a v1.0.1 -m "Mesh Analyzer 1.0.1" -m "- what changed"
   git push origin v1.0.1
   ```
5. The workflow tests, builds `mesh_analyzer-<version>.zip` and publishes the GitHub release. It
   fails on purpose if the tag is lightweight or does not match the manifest version.

To build the package locally: `blender --command extension build --source-dir mesh_analyzer --output-dir dist`.
Install it with Edit > Preferences > Get Extensions > Install from Disk.

## Bringing in updates from an original project

Not applicable: this project is not a fork and has no upstream.

## Things to know

- Blender 5.3's `primitive_uv_sphere_add` creates faces in a different order on each call. Tests
  only compare counts on primitives; the comparison harness freezes meshes into `fixtures.pkl` for
  that reason.
- `_inconsistent_winding` finds each edge's two corners with fancy-index assignment and relies on
  NumPy applying repeated indices in order (true for current NumPy, not formally guaranteed).
  The flipped-face test would catch a change.
- In edit mode the add-on writes the BMesh into a hidden mesh `.mesh_analyzer_tmp` on each update;
  it is removed on unregister.
- `pyflakes` reports `undefined name 'Extend'` in `operators.py`: a false positive caused by Blender's
  property annotations (`extend: BoolProperty(name="Extend")`).
- CI stores no artifacts on purpose: the account-wide artifact quota was full because of another
  repository. The release job builds the zip itself and attaches it to the release.
- Cache entries are keyed by object name; renaming an object simply creates a new entry.

## Known limits

- On a 1M-face mesh one full recompute with every check on takes about 1.2 s (read ~0.45 s +
  analysis ~0.75 s), and building batches when every face is flagged ~0.5 s; under ~100k faces it
  feels instant.
- Duplicate faces are found only when their corners coincide; coplanar faces that partly overlap are
  not detected.
- "Inconsistent Normals" marks the faces on both sides of a winding flip, not which side is wrong;
  use the Face Orientation overlay to see that.
- Doubled vertices use two hash grids, so a pair straddling cells in an unlucky way can be missed
  at the exact tolerance boundary.
- Selection loops over flagged elements in Python and is slow for hundreds of thousands of elements.
- With "Use Modifiers", counts describe the modified mesh but selection always uses the base mesh.
