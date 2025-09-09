#!/usr/bin/env bash
# extract_slice_v3.sh — ImageMagick crop/split with debug and prefix.

set -euo pipefail

IM=
if command -v magick >/dev/null 2>&1; then IM="magick"
elif command -v convert >/dev/null 2>&1; then IM="convert"
else echo "ImageMagick not found"; exit 1; fi

usage(){ cat <<'EOF'
Usage:
  extract_slice_v3.sh IN.png OUT [--x0 N --y0 N --x1 N --y1 N]
                               [--res WxH] [--coords tiles|pixels]
                               [--split] [--prefix NAME] [--dry-run] [--verbose]
Notes:
  End indices are EXCLUSIVE. OUT is a file (single crop) or dir (--split).
EOF
}

[[ $# -lt 2 ]] && usage && exit 1
in="$1"; out="$2"; shift 2

# defaults
coords=tiles; res_w=16; res_h=16; split=0; prefix="tile"; dry=0; verbose=0
x0= y0= x1= y1=

while [[ $# -gt 0 ]]; do
  case "$1" in
    --x0) x0="$2"; shift 2;;
    --y0) y0="$2"; shift 2;;
    --x1) x1="$2"; shift 2;;
    --y1) y1="$2"; shift 2;;
    --res) res_w="${2%x*}"; res_h="${2#*x}"; shift 2;;
    --coords) coords="$2"; shift 2;;
    --split) split=1; shift;;
    --prefix) prefix="$2"; shift 2;;
    --dry-run) dry=1; shift;;
    --verbose) verbose=1; shift;;
    -h|--help) usage; exit 0;;
    *) echo "Unknown arg: $1"; exit 1;;
  esac
done
for v in x0 y0 x1 y1; do [[ -z "${!v:-}" ]] && echo "Missing --$v" && exit 1; done

# image size
iw="$($IM identify -format "%w" "$in")"
ih="$($IM identify -format "%h" "$in")"

# coords -> pixels
if [[ "$coords" == tiles ]]; then
  px0=$(( x0 * res_w )); py0=$(( y0 * res_h ))
  px1=$(( x1 * res_w )); py1=$(( y1 * res_h ))
else
  px0=$x0; py0=$y0; px1=$x1; py1=$y1
fi

# clamp
px0=$(( px0<0?0:(px0>iw?iw:px0) ))
py0=$(( py0<0?0:(py0>ih?ih:py0) ))
px1=$(( px1<0?0:(px1>iw?iw:px1) ))
py1=$(( py1<0?0:(py1>ih?ih:py1) ))
cw=$(( px1 - px0 )); ch=$(( py1 - py0 ))
(( cw>0 && ch>0 )) || { echo "Empty crop after clamping"; exit 1; }

if (( verbose )); then
  echo "IN: $in  (${iw}x${ih})"
  echo "Crop: ${cw}x${ch}+${px0}+${py0}  (coords=$coords, tile=${res_w}x${res_h})"
  if (( split )); then echo "Split tiles -> $out/${prefix}_%03d.png"; else echo "Single -> $out"; fi
fi

if (( dry )); then
  if (( split )); then
    echo "$IM \"$in\" -crop ${cw}x${ch}+${px0}+${py0} +repage -crop ${res_w}x${res_h} +repage +adjoin \"$out/${prefix}_%03d.png\""
  else
    echo "$IM \"$in\" -crop ${cw}x${ch}+${px0}+${py0} +repage \"$out\""
  fi
  exit 0
fi


# --- replace the single-crop block in v3 with this ---
if (( split==0 )); then
  # decide outfile
  if [[ -d "$out" || "$out" == */ ]]; then
    mkdir -p "$out"
    outfile="$out/${prefix}_crop_${px0}_${py0}_${cw}x${ch}.png"
  else
    mkdir -p "$(dirname "$out")"
    outfile="$out"
  fi
  $IM "$in" -crop "${cw}x${ch}+${px0}+${py0}" +repage "$outfile"
  (( verbose )) && echo "Wrote $outfile"
else
  mkdir -p "$out"
  if (( cw % res_w || ch % res_h )); then
    echo "Cropped area not divisible by ${res_w}x${res_h}"; exit 1
  fi
  $IM "$in" -crop "${cw}x${ch}+${px0}+${py0}" +repage \
            -crop "${res_w}x${res_h}" +repage +adjoin \
            "$out/${prefix}_%03d.png"
fi
