# Mesh Analyzer for Blender

[![Blender](https://img.shields.io/badge/dynamic/toml?url=https%3A%2F%2Fraw.githubusercontent.com%2Fmttfntn%2Fmesh-analyzer-blender%2Fmain%2Fmesh_analyzer%2Fblender_manifest.toml&query=%24.blender_version_min&label=Blender&color=E87D0D&logo=blender&logoColor=white)](https://www.blender.org/download/)
[![Release](https://img.shields.io/github/v/release/mttfntn/mesh-analyzer-blender)](https://github.com/mttfntn/mesh-analyzer-blender/releases/latest)
[![tests](https://github.com/mttfntn/mesh-analyzer-blender/actions/workflows/ci.yml/badge.svg)](https://github.com/mttfntn/mesh-analyzer-blender/actions/workflows/ci.yml)
[![License](https://img.shields.io/github/license/mttfntn/mesh-analyzer-blender)](LICENSE)
[![Language](https://img.shields.io/github/languages/top/mttfntn/mesh-analyzer-blender)](https://github.com/mttfntn/mesh-analyzer-blender)

Live, color-coded topology overlay for the 3D Viewport.

- **Faces:** triangles, quads, N-gons, inconsistent normals, zero-area, overlapping (duplicate) faces
- **Edges:** boundary, non-manifold (3+ faces), loose, zero-length, duplicate, overlapping collinear
- **Vertices:** N-poles (3), E-poles (5), poles with 6+ edges, non-manifold, loose, doubled

Each check has its own toggle, color, opacity, element-type icon, live count and a **select**
button (Shift-click to extend). Elements matching several checks are drawn with diagonal color
stripes. The overlay updates while you edit, can analyze the mesh with or without modifiers, and
has a face orientation view, X-ray, and **Select All Flagged**.

## Install

Requires **Blender 5.3**.

1. Download `mesh_analyzer-<version>.zip` from the [releases](https://github.com/mttfntn/mesh-analyzer-blender/releases).
2. In Blender: **Edit > Preferences > Get Extensions > (dropdown) > Install from Disk**, pick the zip.
3. Open the sidebar (**N**) in the 3D Viewport, tab **Analyzer**, and tick the panel header.

## Development

- [HANDOVER.md](HANDOVER.md): how the project is organized, how to test, change and release it.
- [AGENTS.md](AGENTS.md): the same, compactly, for AI coding assistants.

Run the tests:

```bash
blender -b --factory-startup --python tests/run_tests.py
```

## License

GPL-3.0-or-later. See [LICENSE](LICENSE). Copyright 2026 Matteo Fontana.
