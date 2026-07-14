# SPDX-FileCopyrightText: © 2025 ROM-less CORDIC Engine Authors
# SPDX-License-Identifier: Apache-2.0

import os
import logging
from pathlib import Path

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import Timer, RisingEdge, ClockCycles
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


# ---------------- Pad access helpers ----------------
#
# cocotb cannot reliably write individual bits of a packed vector,
# so the input_PAD vector is driven through a shared read-modify-write
# shadow register. Output pads are read from the bidir_PAD vector.

class InputBus:
    """Drives the whole input_PAD vector with a shadow value."""

    def __init__(self, signal, width):
        self.signal = signal
        self.width = width
        self.shadow = 0
        self.signal.value = 0

    def set_bit(self, idx, val):
        if val:
            self.shadow |= (1 << idx)
        else:
            self.shadow &= ~(1 << idx)
        self.signal.value = self.shadow


class InputBit:
    """One bit of the input_PAD vector (mimics a cocotb handle)."""

    def __init__(self, bus, idx):
        self.bus = bus
        self.idx = idx

    @property
    def value(self):
        return (self.bus.shadow >> self.idx) & 1

    @value.setter
    def value(self, val):
        self.bus.set_bit(self.idx, int(val))


class OutputBit:
    """One bit of the bidir_PAD vector (read-only)."""

    def __init__(self, signal, idx):
        self.signal = signal
        self.idx = idx

    @property
    def value(self):
        return (int(self.signal.value) >> self.idx) & 1


# ---------------- SPI bit-bang helpers ----------------

class SpiCfg:
    def __init__(self, cpol=False, cpha=False, msb_first=True, sclk_period_ns=40):
        self.cpol = int(bool(cpol))
        self.cpha = int(bool(cpha))
        self.msb_first = bool(msb_first)
        self.t_half = sclk_period_ns // 2  # ns


async def spi_transfer_byte(dut, cfg: SpiCfg, sclk, mosi, miso, cs_n, tx_byte: int) -> int:
    """
    Transfer one 8-bit word with one CS pulse.
    Returns the received byte.
    CPOL/CPHA modes:
      - Mode 0: cpol=0,cpha=0  (sample on rising)
      - Mode 1: cpol=0,cpha=1  (sample on falling)
      - Mode 2: cpol=1,cpha=0  (sample on falling)
      - Mode 3: cpol=1,cpha=1  (sample on rising)
    """
    # Idle levels
    sclk.value = cfg.cpol
    cs_n.value = 1
    mosi.value = 0
    await Timer(cfg.t_half, units="ns")

    # Assert CS for this byte
    cs_n.value = 0
    await Timer(cfg.t_half, units="ns")

    rx = 0
    bit_indices = range(7, -1, -1) if cfg.msb_first else range(0, 8)

    for i in bit_indices:
        bit = (tx_byte >> i) & 1

        if cfg.cpha == 0:
            # Data valid BEFORE the leading (sample) edge
            mosi.value = bit
            await Timer(cfg.t_half, units="ns")

            # Leading edge (sample edge)
            sclk.value = 1 ^ cfg.cpol
            await Timer(1, units="ns")  # tiny delta before sampling
            rx = (rx << 1) | int(miso.value)
            await Timer(cfg.t_half - 1, units="ns")

            # Trailing edge (shift edge)
            sclk.value = cfg.cpol
            await Timer(cfg.t_half, units="ns")
        else:
            # First edge (shift edge): update MOSI on the leading edge
            await Timer(cfg.t_half, units="ns")
            sclk.value = 1 ^ cfg.cpol
            mosi.value = bit
            await Timer(cfg.t_half, units="ns")

            # Second edge (sample edge)
            sclk.value = cfg.cpol
            await Timer(1, units="ns")
            rx = (rx << 1) | int(miso.value)
            await Timer(cfg.t_half - 1, units="ns")

    # Deassert CS after 8 clocks
    cs_n.value = 1
    await Timer(cfg.t_half, units="ns")
    return rx & 0xFF


async def spi_write_bytes(dut, cfg, sclk, mosi, miso, cs_n, data_bytes):
    for b in data_bytes:
        await spi_transfer_byte(dut, cfg, sclk, mosi, miso, cs_n, b)


async def spi_read_bytes(dut, cfg, sclk, mosi, miso, cs_n, n_bytes):
    rx = []
    for _ in range(n_bytes):
        val = await spi_transfer_byte(dut, cfg, sclk, mosi, miso, cs_n, 0x00)
        rx.append(val)
    return rx


# ---------------- Pack helper ----------------

def pack_cordic_input(in_x, in_y, in_alpha, i_atan_0):
    """Pack 4x16-bit words into a 64-bit integer."""
    return (i_atan_0 << 48) | (in_alpha << 32) | (in_y << 16) | in_x


# ---------------- Startup helpers ----------------

async def enable_power(dut):
    dut.VDD.value = 1
    dut.VSS.value = 0


async def start_clock(clock, freq=100):
    """Start the clock @ freq MHz"""
    c = Clock(clock, 1 / freq * 1000, "ns")
    cocotb.start_soon(c.start())


async def reset(reset, active_low=True, time_ns=1000):
    """Reset dut"""
    cocotb.log.info("Reset asserted...")

    reset.value = not active_low
    await Timer(time_ns, "ns")
    reset.value = active_low

    cocotb.log.info("Reset deasserted.")


# ---------------- The actual test ----------------

@cocotb.test()
async def test_cordic_spi(dut):
    """Test CORDIC FSM over SPI with per-byte CS toggle."""

    logger = logging.getLogger("my_testbench")

    if gl:
        await enable_power(dut)

    # System clock (DUT clock) - 100 MHz
    cocotb.start_soon(Clock(dut.clk_PAD, 10, units="ns").start())

    # Pad mapping (see chip_core.sv)
    inputs = InputBus(dut.input_PAD, 12)
    sclk = InputBit(inputs, 0)
    mosi = InputBit(inputs, 1)
    cs_n = InputBit(inputs, 2)
    miso = OutputBit(dut.bidir_PAD, 0)
    data_ready = OutputBit(dut.bidir_PAD, 1)

    # Reset
    dut._log.info("Reset")
    cs_n.value = 1
    dut.rst_n_PAD.value = 0
    await ClockCycles(dut.clk_PAD, 10)
    dut.rst_n_PAD.value = 1

    dut._log.info("Test project behavior")

    # SPI config: start with Mode 0 (cpol=0,cpha=0). Change to cpha=1 if your core is mode 1.
    cfg = SpiCfg(cpol=False, cpha=False, msb_first=True, sclk_period_ns=40)  # 25 MHz

    # Inputs
    in_x     = 0x09b8
    in_y     = 0x0000
    in_alpha = 0x3244
    i_atan_0 = 0x0c91

    # Pack -> 8 little-endian bytes (LSB first) to match the RX assembly
    spi_word = pack_cordic_input(in_x, in_y, in_alpha, i_atan_0)
    tx_bytes = [(spi_word >> (8 * i)) & 0xFF for i in range(8)]
    dut._log.info("TX bytes (LSB first): " + " ".join(f"{b:02x}" for b in tx_bytes))

    # --- Write 8 bytes (CS toggles per byte) ---
    await spi_write_bytes(dut, cfg, sclk, mosi, miso, cs_n, tx_bytes)

    # Wait for data_ready (bidir_PAD[1])
    got_ready = False
    for _ in range(10000):
        await RisingEdge(dut.clk_PAD)
        if data_ready.value == 1:
            got_ready = True
            break
    assert got_ready, "Timeout: data_ready was never asserted"

    # --- Read 6 bytes back (CS toggles per byte) ---
    rx_bytes = await spi_read_bytes(dut, cfg, sclk, mosi, miso, cs_n, 6)
    dut._log.info("RX bytes: " + " ".join(f"{b:02x}" for b in rx_bytes))

    assert len(rx_bytes) == 6, "Did not receive 6 bytes from DUT"

    # (optional) Repack into 16-bit words if you want to inspect:
    out_sinth = (rx_bytes[1] << 8) | rx_bytes[0]
    out_costh = (rx_bytes[3] << 8) | rx_bytes[2]
    out_alpha = (rx_bytes[5] << 8) | rx_bytes[4]
    dut._log.info(f"Parsed: alpha=0x{out_alpha:04x} cos=0x{out_costh:04x} sin=0x{out_sinth:04x}")

    logger.info("Done!")


def chip_top_runner():

    proj_path = Path(__file__).resolve().parent

    sources = []
    defines = {f"SLOT_{slot.upper()}": True}
    includes = [proj_path / "../src/"]

    # Set the LibreLane PDK/SCL/PAD defines
    defines[f"PDK_{pdk.replace('-','_')}"] = True
    defines[f"SCL_{scl}"] = True
    defines[f"PAD_{pad}"] = True
    defines[f"SRAM_{sram}"] = True

    if gl:
        # SCL models
        sources.append(Path(pdk_root) / pdk / "libs.ref" / scl / "verilog" / f"{scl}.v")
        if scl != "gf180mcu_as_sc_mcu7t3v3":
            sources.append(Path(pdk_root) / pdk / "libs.ref" / scl / "verilog" / "primitives.v")

        # We use the powered netlist
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

    sources += [
        # IO pad models
        Path(pdk_root) / pdk / f"libs.ref/{pad}/verilog/{pad}.v",

        # SRAM macros
        Path(pdk_root) / pdk / f"libs.ref/{sram}/verilog/{sram}__sram512x8m8wm1.v",

        # Custom IP
        proj_path / "../ip/gf180mcu_ws_ip__logo/vh/gf180mcu_ws_ip__logo.v",
        proj_path / "../ip/gf180mcu_ws_ip__marker/vh/gf180mcu_ws_ip__marker.v",
        proj_path / "../ip/gf180mcu_ws_ip__qrcode_id/vh/gf180mcu_ws_ip__qrcode_id.v",
        proj_path / "../ip/gf180mcu_ws_ip__shuttle_id/vh/gf180mcu_ws_ip__shuttle_id.v",
        proj_path / "../ip/gf180mcu_ws_ip__project_id/vh/gf180mcu_ws_ip__project_id.v",
        proj_path / "../ip/gf180mcu_dpk_ip__logo/vh/gf180mcu_dpk_ip__logo.v",

    ]

    build_args = []

    if sim == "icarus":
        # For debugging
        # build_args = ["-Winfloop", "-pfileline=1"]
        pass

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

    plusargs = []

    runner.test(
        hdl_toplevel=hdl_toplevel,
        test_module="chip_top_tb,",
        plusargs=plusargs,
        waves=True,
    )


if __name__ == "__main__":
    chip_top_runner()
