# SPDX-FileCopyrightText: © 2025 ROM-less CORDIC Engine Authors
# SPDX-License-Identifier: Apache-2.0

import os
import logging
from pathlib import Path

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import Timer, RisingEdge, ClockCycles, Combine
from cocotb.types import LogicArray
from cocotb_tools.runner import get_runner

sim = os.getenv("SIM", "icarus")
gl = os.getenv("GL", False)
pdk_root = os.getenv("PDK_ROOT", Path(__file__).resolve().parent / "../gf180mcu")
pdk = os.getenv("PDK", "gf180mcuD")
scl = os.getenv("SCL", "gf180mcu_fd_sc_mcu7t5v0")
pad = os.getenv("PAD", "gf180mcu_fd_io")
sram = os.getenv("SRAM", "gf180mcu_fd_ip_sram")
slot = os.getenv("SLOT", "1x1")

hdl_toplevel = "chip_top"

# ---------------------------------------------------------------
# Pad map -- MUST mirror chip_core.sv
# ---------------------------------------------------------------

NUM_CORES = int(os.getenv("NUM_CORES", "8"))

SLOT_PADS = {   # slot -> (NUM_INPUT_PADS, NUM_BIDIR_PADS)  see slot_defines.svh
    "1x1":     (12, 40),
    "0p5x0p5": (4, 38),
}
NUM_INPUT_PADS, NUM_BIDIR_PADS = SLOT_PADS.get(slot, (4, 38))

CS_ON_INPUT = min(NUM_CORES, NUM_INPUT_PADS)
CS_ON_BIDIR = NUM_CORES - CS_ON_INPUT

SCLK_BASE = 0
MOSI_BASE = SCLK_BASE + NUM_CORES
CSN_BASE  = MOSI_BASE + NUM_CORES
MISO_BASE = CSN_BASE + CS_ON_BIDIR
RDY_BASE  = MISO_BASE + NUM_CORES
PADS_USED = RDY_BASE + NUM_CORES

# Golden result for the standard input vector (bit-exact for the engine)
GOLDEN_IN  = dict(in_x=0x09B8, in_y=0x0000, in_alpha=0x3244, i_atan_0=0x0C91)
GOLDEN_OUT = dict(alpha=0xFFFF, cos=0xF001, sin=0x0012)


# ---------------------------------------------------------------
# Pad access helpers
#
# input_PAD carries CSn[0..CS_ON_INPUT-1] -> driven via an int shadow.
# bidir_PAD carries SCLK/MOSI/CSn-overflow (we drive) and MISO/RDY/spares
# (the chip drives). We deposit the whole vector each update with 'z' on
# every chip-driven bit so the pad drivers win resolution there.
# cocotb cannot reliably write single bits of a packed vector, hence the
# shadow read-modify-write approach.
# ---------------------------------------------------------------

class InputBus:
    def __init__(self, signal, width):
        self.signal = signal
        self.width = width
        self.shadow = (1 << width) - 1  # all CSn idle high
        self.signal.value = self.shadow

    def set_bit(self, idx, val):
        if val:
            self.shadow |= (1 << idx)
        else:
            self.shadow &= ~(1 << idx)
        self.signal.value = self.shadow


class BidirBus:
    def __init__(self, signal, width, driven_default):
        """driven_default: dict {bit_index: initial 0/1} for TB-driven bits;
        every other bit is left 'z' (chip-driven)."""
        self.signal = signal
        self.width = width
        self.chars = ["z"] * width          # index = bit number
        for idx, v in driven_default.items():
            self.chars[idx] = "1" if v else "0"
        self._apply()

    def _apply(self):
        # LogicArray string is MSB first
        self.signal.value = LogicArray("".join(reversed(self.chars)))

    def set_bit(self, idx, val):
        self.chars[idx] = "1" if val else "0"
        self._apply()

    def get_bit(self, idx):
        s = str(self.signal.value)          # MSB first
        c = s[len(s) - 1 - idx]
        return 1 if c == "1" else 0


class DriveBit:
    """One TB-driven bit on either bus (mimics a cocotb handle)."""
    def __init__(self, bus, idx):
        self.bus = bus
        self.idx = idx

    @property
    def value(self):
        return None

    @value.setter
    def value(self, val):
        self.bus.set_bit(self.idx, int(val))


class ReadBit:
    """One chip-driven bit on the bidir bus (read-only)."""
    def __init__(self, bus, idx):
        self.bus = bus
        self.idx = idx

    @property
    def value(self):
        return self.bus.get_bit(self.idx)


class SpiCore:
    """Bundles one core's five SPI signals."""
    def __init__(self, n, inputs, bidirs):
        self.n = n
        self.sclk = DriveBit(bidirs, SCLK_BASE + n)
        self.mosi = DriveBit(bidirs, MOSI_BASE + n)
        if n < CS_ON_INPUT:
            self.cs_n = DriveBit(inputs, n)
        else:
            self.cs_n = DriveBit(bidirs, CSN_BASE + n - CS_ON_INPUT)
        self.miso = ReadBit(bidirs, MISO_BASE + n)
        self.rdy = ReadBit(bidirs, RDY_BASE + n)


# ---------------------------------------------------------------
# SPI bit-bang helpers (mode-configurable, one CS pulse per byte)
# ---------------------------------------------------------------

class SpiCfg:
    def __init__(self, cpol=False, cpha=False, msb_first=True, sclk_period_ns=400):
        self.cpol = int(bool(cpol))
        self.cpha = int(bool(cpha))
        self.msb_first = bool(msb_first)
        self.t_half = sclk_period_ns // 2  # ns


async def spi_transfer_byte(cfg: SpiCfg, core: SpiCore, tx_byte: int) -> int:
    """Transfer one 8-bit word with one CS pulse. Returns the received byte."""
    core.sclk.value = cfg.cpol
    core.cs_n.value = 1
    core.mosi.value = 0
    await Timer(cfg.t_half, units="ns")

    core.cs_n.value = 0
    await Timer(cfg.t_half, units="ns")

    rx = 0
    bit_indices = range(7, -1, -1) if cfg.msb_first else range(0, 8)

    for i in bit_indices:
        bit = (tx_byte >> i) & 1

        if cfg.cpha == 0:
            core.mosi.value = bit
            await Timer(cfg.t_half, units="ns")

            core.sclk.value = 1 ^ cfg.cpol
            await Timer(1, units="ns")
            rx = (rx << 1) | int(core.miso.value)
            await Timer(cfg.t_half - 1, units="ns")

            core.sclk.value = cfg.cpol
            await Timer(cfg.t_half, units="ns")
        else:
            await Timer(cfg.t_half, units="ns")
            core.sclk.value = 1 ^ cfg.cpol
            core.mosi.value = bit
            await Timer(cfg.t_half, units="ns")

            core.sclk.value = cfg.cpol
            await Timer(1, units="ns")
            rx = (rx << 1) | int(core.miso.value)
            await Timer(cfg.t_half - 1, units="ns")

    core.cs_n.value = 1
    await Timer(cfg.t_half, units="ns")
    return rx & 0xFF


def pack_cordic_input(in_x, in_y, in_alpha, i_atan_0):
    return (i_atan_0 << 48) | (in_alpha << 32) | (in_y << 16) | in_x


async def cordic_transaction(dut, cfg, core: SpiCore, vec=GOLDEN_IN, timeout_cycles=100000):
    """Full transaction on one core: 8-byte write, wait RDY, 6-byte read.
    Returns (alpha, cos, sin)."""
    word = pack_cordic_input(vec["in_x"], vec["in_y"], vec["in_alpha"], vec["i_atan_0"])
    tx = [(word >> (8 * i)) & 0xFF for i in range(8)]

    for b in tx:
        await spi_transfer_byte(cfg, core, b)

    for _ in range(timeout_cycles):
        await RisingEdge(dut.clk_PAD)
        if core.rdy.value == 1:
            break
    else:
        raise AssertionError(f"core {core.n}: timeout waiting for RDY")

    rx = [await spi_transfer_byte(cfg, core, 0x00) for _ in range(6)]
    sin = (rx[1] << 8) | rx[0]
    cos = (rx[3] << 8) | rx[2]
    alpha = (rx[5] << 8) | rx[4]
    return alpha, cos, sin


# ---------------------------------------------------------------
# Startup helpers
# ---------------------------------------------------------------

async def enable_power(dut):
    dut.VDD.value = 1
    dut.VSS.value = 0


async def setup(dut):
    if gl:
        await enable_power(dut)

    cocotb.start_soon(Clock(dut.clk_PAD, 10, units="ns").start())  # 100 MHz

    inputs = InputBus(dut.input_PAD, NUM_INPUT_PADS)

    driven = {}
    for n in range(NUM_CORES):
        driven[SCLK_BASE + n] = 0
        driven[MOSI_BASE + n] = 0
        if n >= CS_ON_INPUT:
            driven[CSN_BASE + n - CS_ON_INPUT] = 1  # CSn idle high
    bidirs = BidirBus(dut.bidir_PAD, NUM_BIDIR_PADS, driven)

    cores = [SpiCore(n, inputs, bidirs) for n in range(NUM_CORES)]

    dut.rst_n_PAD.value = 0
    await ClockCycles(dut.clk_PAD, 10)
    dut.rst_n_PAD.value = 1
    await ClockCycles(dut.clk_PAD, 5)

    return cores


# ---------------------------------------------------------------
# Tests
# ---------------------------------------------------------------

@cocotb.test()
async def test_each_core_sequential(dut):
    """Run the golden CORDIC transaction on every core, one at a time."""
    cores = await setup(dut)
    cfg = SpiCfg(sclk_period_ns=400)  # 2.5 MHz SCLK

    for core in cores:
        alpha, cos, sin = await cordic_transaction(dut, cfg, core)
        dut._log.info(f"core {core.n}: alpha=0x{alpha:04x} cos=0x{cos:04x} sin=0x{sin:04x}")
        assert (alpha, cos, sin) == (GOLDEN_OUT["alpha"], GOLDEN_OUT["cos"], GOLDEN_OUT["sin"]), \
            f"core {core.n} mismatch"


@cocotb.test()
async def test_all_cores_parallel(dut):
    """Drive all cores concurrently (staggered) and check independence."""
    cores = await setup(dut)
    cfg = SpiCfg(sclk_period_ns=400)

    results = {}

    async def run_core(core):
        await Timer(37 * core.n + 1, units="ns")  # stagger the buses
        results[core.n] = await cordic_transaction(dut, cfg, core)

    tasks = [cocotb.start_soon(run_core(c)) for c in cores]
    await Combine(*tasks)

    for n, (alpha, cos, sin) in sorted(results.items()):
        dut._log.info(f"core {n}: alpha=0x{alpha:04x} cos=0x{cos:04x} sin=0x{sin:04x}")
        assert (alpha, cos, sin) == (GOLDEN_OUT["alpha"], GOLDEN_OUT["cos"], GOLDEN_OUT["sin"]), \
            f"core {n} mismatch in parallel run"


def chip_top_runner():

    proj_path = Path(__file__).resolve().parent

    sources = []
    defines = {f"SLOT_{slot.upper()}": True}
    includes = [proj_path / "../src/"]

    defines[f"PDK_{pdk.replace('-','_')}"] = True
    defines[f"SCL_{scl}"] = True
    defines[f"PAD_{pad}"] = True
    defines[f"SRAM_{sram}"] = True

    if gl:
        sources.append(Path(pdk_root) / pdk / "libs.ref" / scl / "verilog" / f"{scl}.v")
        if scl != "gf180mcu_as_sc_mcu7t3v3":
            sources.append(Path(pdk_root) / pdk / "libs.ref" / scl / "verilog" / "primitives.v")
        sources.append(proj_path / f"../final/pnl/{hdl_toplevel}.pnl.v")
        defines.update({"FUNCTIONAL": True, "USE_POWER_PINS": True})
    else:
        sources.append(proj_path / "../src/chip_top.sv")
        sources.append(proj_path / "../src/chip_core.sv")
        sources.append(proj_path / "../src/top_fsm.v")
        sources.append(proj_path / "../src/spi_slave.v")
        sources.append(proj_path / "../src/top_CORDIC_Engine_v1.v")
        sources.append(proj_path / "../src/CORDIC_Engine_v1.v")
        sources.append(proj_path / "../src/dynamic_atan.v")
        sources.append(proj_path / "../src/rst_sync.v")

    sources += [
        Path(pdk_root) / pdk / f"libs.ref/{pad}/verilog/{pad}.v",
        Path(pdk_root) / pdk / f"libs.ref/{sram}/verilog/{sram}__sram512x8m8wm1.v",
        proj_path / "../ip/gf180mcu_ws_ip__logo/vh/gf180mcu_ws_ip__logo.v",
        proj_path / "../ip/gf180mcu_ws_ip__marker/vh/gf180mcu_ws_ip__marker.v",
        proj_path / "../ip/gf180mcu_ws_ip__qrcode_id/vh/gf180mcu_ws_ip__qrcode_id.v",
        proj_path / "../ip/gf180mcu_ws_ip__shuttle_id/vh/gf180mcu_ws_ip__shuttle_id.v",
        proj_path / "../ip/gf180mcu_ws_ip__project_id/vh/gf180mcu_ws_ip__project_id.v",
        proj_path / "../ip/gf180mcu_dpk_ip__logo/vh/gf180mcu_dpk_ip__logo.v",
    ]

    build_args = []
    if sim == "verilator":
        build_args = ["--timing", "--trace", "--trace-fst", "--trace-structs"]

    runner = get_runner(sim)
    runner.build(
        sources=sources,
        hdl_toplevel=hdl_toplevel,
        defines=defines,
        always=True,
        includes=includes,
        build_args=build_args,
        waves=True,
    )

    runner.test(
        hdl_toplevel=hdl_toplevel,
        test_module="chip_top_tb,",
        plusargs=[],
        waves=True,
    )


if __name__ == "__main__":
    chip_top_runner()

