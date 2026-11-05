#!/usr/bin/env bash
# Pre-layout synthesis with the real GF180 7-track library: reports cell area,
# estimates the critical path, and writes a powered gate-level netlist that
# `make -C test GATES=yes` can simulate. This is an estimate only; it has no
# placement, wires or clock tree. The authoritative result is the LibreLane run.
#
# Usage: scripts/synth_gf180.sh [output_dir]
# Environment: PDK_ROOT (default ~/pdk), YOSYS (default yosys), LIB_CORNER.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
OUT="${1:-$ROOT/runs/synth}"
PDK_ROOT="${PDK_ROOT:-$HOME/pdk}"
YOSYS="${YOSYS:-yosys}"
CORNER="${LIB_CORNER:-tt_025C_3v30}"
SCL=gf180mcu_fd_sc_mcu7t5v0
LIB="$PDK_ROOT/gf180mcuD/libs.ref/$SCL/lib/${SCL}__${CORNER}.lib"
TOP=tt_um_gurpalhamzamohilayaan_tinyfir

mkdir -p "$OUT"
sources=$(python3 - "$ROOT/info.yaml" "$ROOT/src" <<'PY'
import re, sys
text = open(sys.argv[1]).read()
block = text.split("source_files:")[1].split("\n\n")[0]
print(" ".join(f"{sys.argv[2]}/{name}" for name in re.findall(r'-\s*"([^"]+)"', block)))
PY
)

cat > "$OUT/abc.script" <<ABC
strash
dch
map -B 0.9
topo
stime -p
buffer -p
upsize
dnsize
stime -p
ABC

cat > "$OUT/synth.ys" <<YS
read_verilog -defer $sources
hierarchy -check -top $TOP
synth -flatten -top $TOP
opt -purge
dfflibmap -liberty $LIB
opt
abc -D 100000 -liberty $LIB -script $OUT/abc.script
hilomap -singleton -hicell ${SCL}__tieh Z -locell ${SCL}__tiel ZN
setundef -zero
splitnets
opt_clean -purge
tee -o $OUT/area.rpt stat -liberty $LIB
write_verilog -noattr -noexpr -nohex -nodec $OUT/netlist.v
YS

"$YOSYS" -q -l "$OUT/yosys.log" "$OUT/synth.ys"

# Add the power connections used by LibreLane's netlist and the testbench.
python3 - "$OUT/netlist.v" "$OUT/gate_level_netlist.v" "$TOP" <<'PY'
import re, sys
src, dst, top = sys.argv[1:]
text = open(src).read()
text = re.sub(r"(module\s+%s\s*\()" % top, r"\1VPWR, VGND, ", text, count=1)
text = re.sub(r"(module\s+%s\s*\([^;]*;)" % top, r"\1\n  input VPWR;\n  input VGND;", text, count=1)
text = re.sub(r"(gf180mcu_fd_sc_mcu7t5v0__\w+\s+\S+\s*\()",
              r"\1.VDD(VPWR), .VSS(VGND), .VNW(VPWR), .VPW(VGND), ", text)
open(dst, "w").write(text)
PY

grep -E "Chip area|Number of cells|cells$" "$OUT/area.rpt" | tail -3 || true
echo "Netlist: $OUT/gate_level_netlist.v"
