# Regression Test on Raspberry Pi Pico with the FPGA

The Pico acts as an SPI master, sending test angles to the FPGA and reading back computed sine and cosine values for verification against expected results.

## Prepare bitsream and upload to ULX3S
```bash
make clean
make
make prog
```
## Hardware Connections

Connect the Raspberry Pi Pico to the ULX3S as follows:

| FPGA Signal | ULX3S Pin | Raspberry Pi Pico Pin | RP2040 GPIO Number | Description       |
|-------------|----------|----------------------|------------------|-------------------|
| SCK         | 22       | Pin 2                | GP2              | SPI Clock (SCK)   |
| MOSI        | 23       | Pin 3                | GP3              | SPI Master Out    |
| MISO        | 24       | Pin 4                | GP4              | SPI Master In     |
| CS_N       | 25       | Pin 5                | GP5              | SPI Chip Select   |
| RST_N       | PWR Btn  | N/A                  | N/A            | Design's Reset tied to PWR Btn |

<p align="center">
  <img src="misc/board_connections.png" alt="Block Diagarm of the ROM-less CORDIC Engine" width="800"/>
  </p>
<p align="center"><em>Hardware connections from ulx3s-85f to Raspbery Pi Pico</em></p>
   
## Overview
- **Communication Protocol:**  
  - SPI is used on the Pico with the following pins:
    - SCK: GP2 (Pin 2)  
    - MOSI: GP3 (Pin 3)  
    - MISO: GP4 (Pin 4)  
    - CS: GP5 (Pin 5) (manual control)  
  - SPI mode 0 (polarity=0, phase=0) at 20 kHz baudrate.
- **SPI Transaction:**  
  - The Pico sends 8 bytes per test angle representing fixed-point input data.
  - Then reads 6 bytes response containing calculated sine and cosine values from FPGA.
  - Chip Select (CS) pin is toggled individually around each byte transferred.
- **Regression Test:**  
  - Tests multiple angles evenly spaced between 0 and 2π radians.
  - Compares FPGA results with Python math library sine and cosine.
  - Outputs detailed pass/fail results and error statistics.


## Usage Instructions

1. **Wiring:** Connect ULX3S pins 22-25 to Pico as described.
2. **Load MicroPython code:** Copy the regression test script to the Raspberry Pi Pico filesystem.
3. **Run the test:** Run the script via serial REPL or in an IDE like Thonny.
4. **View results:** The test prints detailed results, including any failed angle cases, maximum and mean error values.
5. **Save logs:** Optionally, the test results can be saved as JSON on the Pico and transferred to the host for further analysis(use mpremote or Thonny). 
   
   For instance, following copies the JSON result from Pico to the host filesystem - 
```bash
mpremote connect /dev/ACM0 fs cp :cordic_test_results_20250901_061553.json  .
```
## Comprehensive Regression test with tolerance=±0.005741 
 > **Note:** Adjust tolerance level in the script for cosine and sine to perform a custom regression test.
 > Also set an appropriate baudrate on SPI master so that the regression tests work well.

```log
=== CORDIC Regression Test: 100 Angles ===
Fixed parameters:
  in_x = 0x09B8 (+0.607422)
  in_y = 0x0000 (+0.000000)
  i_atan_0 = 0x0C91 (+0.785400)
Tolerance: cos=±0.005741, sin=±0.005741
--------------------------------------------------------------------------------
Test  10: θ= 0.565 rad (  32.4°) | cos_err=0.003328, sin_err=0.003844 | ✅ PASS
Test  20: θ= 1.194 rad (  68.4°) | cos_err=0.003378, sin_err=0.001620 | ✅ PASS
Test  30: θ= 1.822 rad ( 104.4°) | cos_err=0.005038, sin_err=0.002120 | ✅ PASS
Test  40: θ= 2.450 rad ( 140.4°) | cos_err=0.003168, sin_err=0.003879 | ✅ PASS
Test  50: θ= 3.079 rad ( 176.4°) | cos_err=0.000997, sin_err=0.004685 | ✅ PASS
Test  60: θ= 3.707 rad ( 212.4°) | cos_err=0.003328, sin_err=0.003844 | ✅ PASS
Test  70: θ= 4.335 rad ( 248.4°) | cos_err=0.003378, sin_err=0.001620 | ✅ PASS
Test  80: θ= 4.964 rad ( 284.4°) | cos_err=0.005038, sin_err=0.002120 | ✅ PASS
Test  90: θ= 5.592 rad ( 320.4°) | cos_err=0.003168, sin_err=0.003879 | ✅ PASS
Test 100: θ= 6.220 rad ( 356.4°) | cos_err=0.000997, sin_err=0.004685 | ✅ PASS

================================================================
REGRESSION TEST SUMMARY
================================================================
Total tests run:     100
Passed:              100 (100.0%)
Failed:              0 (0.0%)
Execution time:      0.92 seconds
Max cosine error:    0.00574060
Max sine error:      0.00574060
Mean cosine error:   0.00329450
Mean sine error:     0.00328961
```