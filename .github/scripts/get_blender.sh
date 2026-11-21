#!/usr/bin/env bash
# Download and unpack the newest Linux x64 build of one Blender series (e.g. "5.3").
#
#   get_blender.sh <series> <dest_dir>
#
# Tries download.blender.org first, then official mirrors (the main server sometimes refuses
# CI machines). Each request is retried. Prints the path of the blender binary on the last line
# and, on GitHub Actions, exports BLENDER and BLENDER_VERSION through $GITHUB_ENV.
set -euo pipefail

SERIES="$1"
DEST="$2"
MIRRORS=(
  "https://download.blender.org/release"
  "https://mirrors.ocf.berkeley.edu/blender/release"
  "https://ftp.nluug.nl/pub/graphics/blender/release"
  "https://mirror.clarkson.edu/blender/release"
)
CURL=(curl -fsSL --retry 4 --retry-delay 5 --retry-all-errors --connect-timeout 20)

file=""
for base in "${MIRRORS[@]}"; do
  listing="$("${CURL[@]}" --max-time 60 "$base/Blender$SERIES/" || true)"
  file="$(grep -oE "blender-${SERIES//./\\.}\.[0-9]+-linux-x64\.tar\.xz" <<<"$listing" | sort -uV | tail -n1 || true)"
  if [[ -n "$file" ]]; then
    url="$base/Blender$SERIES/$file"
    break
  fi
  echo "No Blender $SERIES listing from $base, trying next mirror" >&2
done
[[ -n "$file" ]] || { echo "Could not find a Blender $SERIES Linux build on any mirror" >&2; exit 1; }

version="${file#blender-}"
version="${version%-linux-x64.tar.xz}"
dir="$DEST/blender-$version-linux-x64"

if [[ ! -x "$dir/blender" ]]; then
  mkdir -p "$DEST"
  ok=""
  for base in "${MIRRORS[@]}"; do
    echo "Downloading $file from $base" >&2
    if "${CURL[@]}" --max-time 900 -o "$DEST/$file" "$base/Blender$SERIES/$file" \
      && tar -xJf "$DEST/$file" -C "$DEST"; then
      ok=1
      break
    fi
    echo "Download from $base failed, trying next mirror" >&2
  done
  rm -f "$DEST/$file"
  [[ -n "$ok" ]] || { echo "Could not download $file" >&2; exit 1; }
fi

if [[ -n "${GITHUB_ENV:-}" ]]; then
  echo "BLENDER=$dir/blender" >>"$GITHUB_ENV"
  echo "BLENDER_VERSION=$version" >>"$GITHUB_ENV"
fi
echo "$dir/blender"
