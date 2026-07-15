# CORDIC ROMless 8-core, 

## wafer.space run2 GF180MCU

Eight independent ROM-less CORDIC engines on a single GF180MCU die, each with its own SPI-slave interface. Built for the [wafer.space](https://wafer.space/) shuttle on the 0.5×0.5 slot. 

Second silicon of the [Tiny Tapeout SKY25a single-core version](https://github.com/rohanverma94/ttsky-romless-cordic-engine), re-architected for GF180MCU: 8x cores.



## What it does

Each core computes sin θ and cos θ using a CORDIC rotator in rotation mode, with the arctan micro-rotation angles generated on the fly by Taylor-series approximation , no coefficient ROM. Data format is 16-bit signed fixed point (1 sign, 3 integer, 12 fraction bits); the engine runs 13 iterations, with quadrant pre-mapping and output post-processing to cover the full [0, 2π] range. Mean absolute error ≈ 0.003 over 1000 samples versus MATLAB reference.

Full math, block diagram, and accuracy plots: [docs/info.md](docs/info.md).

## Architecture

The cores are fully independent ie separate SCLK, MOSI, CSn, MISO and RDY per core; only clock and reset are shared, and nothing is bussed on-chip. To drive several cores from one host, bus SCLK/MOSI on the board and use the chip selects.

Each iteration is executed in two clock phases (shift, then add/subtract), splitting the barrel-shift moved to adder chain that dominated the critical path. This only latency changes (26 cycles per rotation plus load/output — irrelevant against SPI transfer time). The `dynamic_atan` generator is kept in lockstep via a step-enable pulsed each add phase.

Timing closed on 40 ns (25MHz) with 5.56 ns setup slack on max_ss_125C_4v50 corner

So could be clocked upto  34.4 ns ie ~29 MHz. 

## Pin map (0.5×0.5 slot: 4 input pads, 38 bidir pads)

| Pads | Function | Direction |
|---|---|---|
| `input[0..3]` | CSn[0..3] | in |
| `bidir[0..7]` | SCLK[0..7] | in |
| `bidir[8..15]` | MOSI[0..7] | in |
| `bidir[16..19]` | CSn[4..7] | in |
| `bidir[20..27]` | MISO[0..7] | out |
| `bidir[28..35]` | RDY[0..7] | out |
| `bidir[36..37]` | spare, driven low | out |

The map is computed parametrically in `src/chip_core.sv` from `NUM_CORES` and the slot's pad counts; the testbench derives the same map from the same formulas.

## SPI protocol (per core)

Mode 0, MSB-first within a byte, one CSn pulse per byte, SCLK ≤ core_clk/4 (≤ 5 MHz at 20 MHz core).

Write 8 bytes — the 64-bit word `{in_atan_0, in_alpha, in_y, in_x}` (16 bits each), transmitted least-significant byte first. Wait for RDY to assert, then read 6 bytes back: `{out_alpha, out_costheta, out_sintheta}`, also LSB-first per 16-bit word.

| Signal | Meaning |
|---|---|
| `in_x`, `in_y` | scaled input vector (y = 0 for sin/cos computation) |
| `in_alpha` | input angle θ in radians |
| `in_atan_0` | initial micro-rotation angle, arctan(2⁰) |
| `out_costheta`, `out_sintheta` | cos θ, sin θ |
| `out_alpha` | residual angle (converges to ~0) |

Reference vector: `in_x=0x09B8, in_y=0x0000, in_alpha=0x3244 (π), in_atan_0=0x0C91` → `cos=0xF001 (≈ −1.0), sin=0x0012 (≈ 0), alpha=0xFFFF`.

An RP2040 (Pico) was used as the SPI master for all bring-up of the original silicon.

## Building the chip

Dependencies are managed with Nix — see the [LibreLane installation guide](https://librelane.readthedocs.io/en/latest/installation/nix_installation/index.html), then `nix-shell` in the repo root.

```
make clone-pdk                      # fetch gf180mcuD PDK via ciel
make SLOT=0p5x0p5 librelane         # full RTL-to-GDS flow
make SLOT=0p5x0p5 librelane-klayout # view the result
```

Final views land in `final/`. Timing-relevant config lives in `librelane/config.yaml` (`CLOCK_PERIOD: 50`, `SYNTH_STRATEGY: "DELAY 1"`, setup-repair margins).

## Verification

`cocotb/chip_top_tb.py` drives full transactions through the chip pads: an 8-byte write, RDY poll, 6-byte read, checked against the golden vector. Two tests: every core sequentially, and all eight cores concurrently (staggered) to prove independence.

```
SLOT=0p5x0p5 make sim       # RTL simulation
SLOT=0p5x0p5 make sim-gl    # gate-level, requires final/ from a completed hardening run
NUM_CORES=8                 # default; must match the localparam in chip_core.sv
```

A standalone core-level testbench is in `sim/`, and `fpga/` carries the FPGA validation setup from the original project.

The release ws1.0 contains the gds submitted for wafer.space run-2.

## Reference

[50 Years of CORDIC: Algorithms, Architectures, and Applications](https://ieeexplore.ieee.org/document/5089431)
