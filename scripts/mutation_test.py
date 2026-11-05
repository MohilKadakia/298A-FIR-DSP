#!/usr/bin/env python3
"""Check that the system regression catches realistic RTL bugs.

Each mutation below changes one thing in a scratch copy of the repository. The
pin-level regression (test/test.py) then runs against it. A mutation that "survives"
means the regression passed despite the bug, which is either a testbench gap or an
equivalent change. Known equivalents are marked and explained.

Usage: scripts/mutation_test.py [--jobs N] [--only SUBSTRING] [--work DIR]
"""

import argparse
import concurrent.futures
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from xml.etree import ElementTree

ROOT = Path(__file__).resolve().parent.parent

# (file, original text, replacement, optional reason it is expected to survive)
MUTATIONS = [
    # Wrapper
    ("project.v", "2'b00, ~spi_cs_n, 2'b00", "2'b00, 1'b1, 2'b00"),
    ("project.v", "{3'b111, 2'b00,", "{3'b110, 2'b00,"),
    ("project.v", "{saturated, output_valid, ready,", "{saturated, ready, output_valid,"),
    ("project.v", "2'b00, spi_miso, 2'b00", "2'b01, spi_miso, 2'b00"),
    ("project.v", ".rst_n        (core_rst_n)", ".rst_n        (rst_n)",
     "Reset released directly from the pin works the same in simulation. The synchronizer "
     "guards against a metastable release, which zero-delay simulation cannot show."),
    # Strobe synchronizer
    ("strobe_sync.v", ".RESET_VALUE(1'b1)", ".RESET_VALUE(1'b0)"),
    ("strobe_sync.v", "strobe_prev_q <= 1'b1", "strobe_prev_q <= 1'b0"),
    ("strobe_sync.v", "strobe_rise = strobe_s & ~strobe_prev_q", "strobe_rise = strobe_s"),
    ("strobe_sync.v", "strobe_rise = strobe_s & ~strobe_prev_q",
     "strobe_rise = ~strobe_s & strobe_prev_q"),
    ("strobe_sync.v", "strobe_low  = ~strobe_prev_q", "strobe_low  = 1'b1"),
    # Controller
    ("fir_controller.v", "ST_INIT: if (strobe_low) state_q <= ST_IDLE;", "ST_INIT: state_q <= ST_IDLE;"),
    ("fir_controller.v", "tap_q == 3'd7", "tap_q == 3'd6"),
    ("fir_controller.v", "tap_q + 3'd1", "tap_q + 3'd3"),
    ("fir_controller.v", "overrun     = ~ready & strobe_rise", "overrun     = 1'b0"),
    ("fir_controller.v", "accept      = ready & strobe_rise", "accept      = strobe_rise"),
    ("fir_controller.v", "calc_active = state_q[1] | state_q[2]", "calc_active = state_q[1]"),
    ("fir_controller.v", "calc_active = state_q[1] | state_q[2]", "calc_active = state_q[2]"),
    ("fir_controller.v", "calc_active = state_q[1] | state_q[2]",
     "calc_active = state_q[1] | state_q[2] | ~state_q[0]"),
    ("fir_controller.v", "ST_PUBLISH: state_q <= ST_IDLE;", "ST_PUBLISH: state_q <= ST_MAC;"),
    # Sample history
    ("sample_history.v", "accept ? sample_in : 8'd0", "8'd0"),
    ("sample_history.v", "{56'd0, accept", "{hist_q[63:8], accept"),
    ("sample_history.v", "{hist_q[55:0], sample_in}", "{hist_q[63:8], sample_in}"),
    ("sample_history.v", "{tap, 3'b000}+:8", "{~tap, 3'b000}+:8"),
    ("sample_history.v", "else if (clear)", "else if (1'b0)"),
    ("sample_history.v", "if (!rst_n) hist_q <= 64'd0", "if (!rst_n) hist_q <= 64'd1"),
    # Coefficient registers
    ("coef_regs.v", "COEF_RESET = 9'd16", "COEF_RESET = 9'd32"),
    ("coef_regs.v", "write_addr == i[2:0]", "write_addr[1:0] == i[1:0]"),
    ("coef_regs.v", "coef_tap  = coef[tap]", "coef_tap  = coef[~tap]"),
    ("coef_regs.v", "read_data = coef[read_addr]", "read_data = coef[tap]"),
    # Multiplier and accumulator
    ("fir_mac.v", "wire signed [ 7:0] sample_s", "wire [ 7:0] sample_s"),
    ("fir_mac.v", "wire signed [ 8:0] coef_s", "wire [ 8:0] coef_s"),
    ("fir_mac.v", "{{3{product[16]}}, product}", "{3'b000, product}"),
    ("fir_mac.v", "acc + {", "acc - {"),
    ("fir_mac.v", "else if (clear) acc", "else if (1'b0) acc"),
    ("fir_mac.v", "else if (enable) acc", "else if (1'b1) acc",
     "The accumulator would run freely outside a calculation, but it is cleared on acceptance "
     "and read before it can change again, so the pins cannot see it. test/unit/test_fir_mac.py "
     "does catch this one."),
    # Output stage
    ("output_stage.v", "acc_scaled[12:7] != {6{acc_scaled[7]}}", "acc_scaled[12:8] != {5{acc_scaled[8]}}"),
    ("output_stage.v", "acc_scaled[12:7] != {6{acc_scaled[7]}}", "acc_scaled[11:7] != {5{acc_scaled[7]}}",
     "The accumulator cannot reach a value where bit 19 differs from bits 18:14, because "
     "131072 needs only 19 bits. Bit 19 is redundant by the proposal's chosen width."),
    ("output_stage.v", "8'h80 : 8'h7F", "8'h7F : 8'h80"),
    ("output_stage.v", "8'h80 : 8'h7F", "8'h81 : 8'h7F"),
    ("output_stage.v", "8'h80 : 8'h7F", "8'h80 : 8'h7E"),
    ("output_stage.v", "saturated  <= overflow;", "saturated  <= overflow | saturated;"),
    ("output_stage.v", "output_valid <= publish;", "output_valid <= publish | output_valid;"),
    ("output_stage.v", "if (publish) begin", "if (1'b1) begin"),
    ("output_stage.v", "posedge clk or negedge rst_n", "posedge clk"),
    # SPI protocol and validation
    ("spi_interface.v", " | (shift_q == 16'h0080)", ""),
    ("spi_interface.v", "(&shift_q[15:7])", "(&shift_q[15:8])"),
    ("spi_interface.v", "(~|shift_q[15:7])", "(~|shift_q[15:8])"),
    ("spi_interface.v", "(shift_q == 16'h0080)", "(shift_q == 16'h0081)"),
    ("spi_interface.v", "(bit_count_q == BITS_TOTAL) & reserved_ok_q", "(bit_count_q >= BITS_TOTAL) & reserved_ok_q"),
    ("spi_interface.v", "(bit_count_q == BITS_TOTAL) & reserved_ok_q", "(bit_count_q >= 5'd23) & reserved_ok_q"),
    ("spi_interface.v", "if (bit_count_q != BITS_OVERLONG) bit_count_q", "bit_count_q"),
    ("spi_interface.v", "(bit_count_q == BITS_TOTAL) & reserved_ok_q & ~calc_active", "(bit_count_q == BITS_TOTAL) & ~calc_active"),
    ("spi_interface.v", "reserved_ok_q & ~calc_active", "reserved_ok_q"),
    ("spi_interface.v", "control_legal = shift_q[15:2] == 14'd0", "control_legal = 1'b1"),
    ("spi_interface.v", "addr_is_control = addr_q == ADDR_CONTROL", "addr_is_control = addr_q[3]"),
    ("spi_interface.v", "addr_is_coef = ~addr_q[3]", "addr_is_coef = 1'b1"),
    ("spi_interface.v", "cs_end & (bit_count_q != 5'd0) & ~is_read_q", "cs_end & ~is_read_q"),
    ("spi_interface.v", "cs_end & (bit_count_q != 5'd0) & ~is_read_q", "cs_end & (bit_count_q != 5'd0)"),
    ("spi_interface.v", "is_read_q & in_data_phase & shift_q[15]", "in_data_phase & shift_q[15]"),
    ("spi_interface.v", "is_read_q & in_data_phase & shift_q[15]", "is_read_q & shift_q[15]"),
    ("spi_interface.v", "{{7{coef_read_data[8]}}, coef_read_data}", "{7'd0, coef_read_data}"),
    ("spi_interface.v", "{12'd0, status}", "{status, 12'd0}"),
    ("spi_interface.v", "if (shift_q[5:3] != 3'b000) read_word = 16'd0;", "if (1'b0) read_word = 16'd0;"),
    ("spi_interface.v", "if (sclk_fall) spi_miso", "if (sclk_rise) spi_miso"),
    ("spi_interface.v", "else read_word = 16'd0;", "else read_word = 16'hFFFF;"),
    ("spi_interface.v", "shift_q <= {shift_q[14:0], mosi_s};", "shift_q <= {shift_q[14:0], ~mosi_s};"),
    ("spi_interface.v", "        spi_miso    <= 1'b0;\n        bit_count_q <= 5'd0;", "        spi_miso    <= 1'b0;"),
    ("spi_interface.v", "        spi_miso    <= 1'b0;\n        bit_count_q <= 5'd0;", "        bit_count_q <= 5'd0;"),
    ("spi_interface.v", "if (bit_count_q == 5'd0) is_read_q", "if (last_command_bit) is_read_q"),
    ("spi_interface.v", "cs_end = cs_n_s & ~cs_n_prev_q", "cs_end = ~cs_n_s & cs_n_prev_q"),
    ("spi_interface.v", "coef_write_data = shift_q[8:0]", "coef_write_data = {1'b0, shift_q[7:0]}"),
    ("spi_interface.v", "addr_is_control & shift_q[0]", "addr_is_control & shift_q[1]"),
    ("spi_interface.v", "addr_is_control & shift_q[1]", "addr_is_control & shift_q[0]"),
    ("spi_interface.v", "coef_write_addr = addr_q[2:0]", "coef_write_addr = {1'b0, addr_q[1:0]}"),
    # Top-level connections and flags
    ("fir_core.v", "write_rejected | (rejected_flag_q & ~clear_flags)", "write_rejected"),
    ("fir_core.v", "write_rejected | (rejected_flag_q & ~clear_flags)", "write_rejected | rejected_flag_q"),
    ("fir_core.v", "overrun | (overrun_flag_q & ~clear_flags)", "overrun | overrun_flag_q"),
    ("fir_core.v", "overrun | (overrun_flag_q & ~clear_flags)", "overrun"),
    ("fir_core.v", ".clear (accept)", ".clear (1'b0)"),
    ("fir_core.v", ".enable(mac_enable)", ".enable(1'b1)",
     "The same free-running accumulator as above, here from the connection in fir_core."),
    ("fir_core.v", "{overrun_flag_q, rejected_flag_q, saturated, ready}", "{rejected_flag_q, overrun_flag_q, saturated, ready}"),
    ("fir_core.v", "{overrun_flag_q, rejected_flag_q, saturated, ready}", "{overrun_flag_q, rejected_flag_q, ready, saturated}"),
]


def run_one(index: int, mutation: tuple, work: Path) -> dict:
    filename, old, new = mutation[:3]
    expected_survivor = mutation[3] if len(mutation) > 3 else None
    label = f"{filename}: {old.strip()!r} -> {new.strip()!r}"
    run_dir = Path(tempfile.mkdtemp(prefix=f"mut{index:03d}_", dir=work))
    try:
        for name in ("src", "test", "model"):
            shutil.copytree(
                ROOT / name, run_dir / name,
                ignore=shutil.ignore_patterns("sim_build", "__pycache__", "*.fst", "results*.xml", "unit"),
            )
        source = run_dir / "src" / filename
        text = source.read_text()
        if text.count(old) != 1:
            return {"index": index, "label": label, "status": f"BAD MUTATION ({text.count(old)} matches)"}
        source.write_text(text.replace(old, new))
        try:
            completed = subprocess.run(
                ["make", "-B"], cwd=run_dir / "test", capture_output=True, text=True, timeout=900
            )
        except subprocess.TimeoutExpired:
            return {"index": index, "label": label, "status": "KILLED (timeout)"}
        results = run_dir / "test" / "results.xml"
        if not results.exists():
            tail = completed.stdout[-400:] + completed.stderr[-400:]
            return {"index": index, "label": label, "status": "BUILD ERROR", "detail": tail}
        failures = [
            case.get("name")
            for case in ElementTree.parse(results).getroot().iter("testcase")
            if case.find("failure") is not None or case.find("error") is not None
        ]
        if failures:
            return {"index": index, "label": label, "status": "KILLED", "tests": failures}
        status = "SURVIVED (expected)" if expected_survivor else "SURVIVED"
        return {"index": index, "label": label, "status": status, "reason": expected_survivor}
    finally:
        shutil.rmtree(run_dir, ignore_errors=True)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--jobs", type=int, default=8)
    parser.add_argument("--only", default="")
    parser.add_argument("--work", type=Path, default=None)
    args = parser.parse_args()

    work = args.work or Path(tempfile.mkdtemp(prefix="tinyfir_mut_"))
    work.mkdir(parents=True, exist_ok=True)
    selected = [(i, m) for i, m in enumerate(MUTATIONS) if args.only in f"{m[0]} {m[1]} {m[2]}"]

    with concurrent.futures.ThreadPoolExecutor(max_workers=args.jobs) as pool:
        futures = [pool.submit(run_one, i, m, work) for i, m in selected]
        results = []
        for future in concurrent.futures.as_completed(futures):
            result = future.result()
            results.append(result)
            caught_by = len(result.get("tests", []))
            print(
                f"[{len(results):3d}/{len(selected)}] {result['status']:20s} "
                f"{caught_by:2d} tests  {result['label']}",
                flush=True,
            )

    results.sort(key=lambda r: r["index"])
    counts = {}
    for result in results:
        counts[result["status"].split(" (")[0] if "BAD" not in result["status"] else "BAD"] = (
            counts.get(result["status"].split(" (")[0] if "BAD" not in result["status"] else "BAD", 0) + 1
        )
    print("\nSummary:", counts)
    unexpected = [
        r for r in results
        if r["status"] == "SURVIVED" or "BAD" in r["status"] or r["status"] == "BUILD ERROR"
    ]
    for result in unexpected:
        print(f"  NEEDS ATTENTION: {result['status']}: {result['label']} {result.get('detail', '')}")
    for result in results:
        if result["status"] == "SURVIVED (expected)":
            print(f"  equivalent: {result['label']}\n      {result['reason']}")
    return 1 if unexpected else 0


if __name__ == "__main__":
    sys.exit(main())
