import math
import utime
import ujson as json
from machine import SPI, Pin

FRAC_BITS = 12
SCALE = 1 << FRAC_BITS  # 4096 for S3.12

# Convert signed S3.12 16-bit fixed-point to float
def s3_12_to_float(val):
    if val & 0x8000:
        val -= (1 << 16)
    return val / SCALE

# Convert float to signed S3.12 16-bit fixed-point
def float_to_s3_12(f):
    val = int(round(f * SCALE))
    val = max(min(val, 0x7FFF), -0x8000)
    return val & 0xFFFF

def pack_cordic_input(in_x, in_y, in_alpha, i_atan_0):
    return (i_atan_0 << 48) | (in_alpha << 32) | (in_y << 16) | in_x

def to_spi_bytes(packed_val):
    return [(packed_val >> (8 * i)) & 0xFF for i in range(8)]

# Raspberry Pi Pico SPI0 pins - adjust as needed
spi = SPI(0, baudrate=20_000, polarity=0, phase=0,
          sck=Pin(2), mosi=Pin(3), miso=Pin(4))
cs = Pin(5, Pin.OUT, value=1)

def send_byte(byte_val):
    cs.value(0)
    spi.write(bytearray([byte_val]))
    cs.value(1)
    utime.sleep_us(10)

def read_byte():
    cs.value(0)
    val = spi.read(1, 0x00)[0]
    cs.value(1)
    utime.sleep_us(10)
    return val

def receive_response(num_bytes=6):
    rx = []
    for _ in range(num_bytes):
        rx.append(read_byte())
    return rx

def unpack_response(rx_bytes):
    val = 0
    for i in range(len(rx_bytes)):
        val |= (rx_bytes[i] << (8 * i))
    word_0 = (val >> 0) & 0xFFFF
    word_1 = (val >> 16) & 0xFFFF
    return word_0, word_1

def generate_test_angles(num_angles=100):
    step = 2.0 * math.pi / num_angles
    return [i * step for i in range(num_angles)]

def run_cordic_regression_test(num_angles=100, tolerance=1e-3, cos_tolerance=None, sin_tolerance=None):
    cos_tol = cos_tolerance if cos_tolerance is not None else tolerance
    sin_tol = sin_tolerance if sin_tolerance is not None else tolerance

    FIXED_IN_X = 0x09B8
    FIXED_IN_Y = 0x0000
    FIXED_I_ATAN_0 = 0x0C91

    print("\n=== CORDIC Regression Test: {} Angles ===".format(num_angles))
    print("Fixed parameters:")
    print("  in_x = 0x{:04X} ({:+.6f})".format(FIXED_IN_X, s3_12_to_float(FIXED_IN_X)))
    print("  in_y = 0x{:04X} ({:+.6f})".format(FIXED_IN_Y, s3_12_to_float(FIXED_IN_Y)))
    print("  i_atan_0 = 0x{:04X} ({:+.6f})".format(FIXED_I_ATAN_0, s3_12_to_float(FIXED_I_ATAN_0)))
    print("Tolerance: cos=±{:.6f}, sin=±{:.6f}".format(cos_tol, sin_tol))
    print("-" * 80)

    test_angles = generate_test_angles(num_angles)

    results = {
        'total_tests': num_angles,
        'passed': 0,
        'failed': 0,
        'max_cos_error': 0.0,
        'max_sin_error': 0.0,
        'cos_errors': [],
        'sin_errors': [],
        'failed_cases': [],
        'execution_time': 0.0
    }

    start_ms = utime.ticks_ms()

    for idx, angle_rad in enumerate(test_angles, 1):
        in_alpha = float_to_s3_12(angle_rad)
        packed_val = pack_cordic_input(FIXED_IN_X, FIXED_IN_Y, in_alpha, FIXED_I_ATAN_0)
        tx_bytes = to_spi_bytes(packed_val)

        # Send packed 8 bytes, per-byte with CS toggling
        for b in tx_bytes:
            send_byte(b)

        # Receive 6 bytes response, per-byte with CS toggling
        rx_bytes = receive_response(6)
        word0, word1 = unpack_response(rx_bytes)
        fpga_sin = s3_12_to_float(word0)
        fpga_cos = s3_12_to_float(word1)

        expected_cos = math.cos(angle_rad)
        expected_sin = math.sin(angle_rad)

        cos_err = abs(fpga_cos - expected_cos)
        sin_err = abs(fpga_sin - expected_sin)

        results['max_cos_error'] = max(results['max_cos_error'], cos_err)
        results['max_sin_error'] = max(results['max_sin_error'], sin_err)
        results['cos_errors'].append(cos_err)
        results['sin_errors'].append(sin_err)

        cos_pass = cos_err <= cos_tol
        sin_pass = sin_err <= sin_tol
        test_passed = cos_pass and sin_pass

        if test_passed:
            results['passed'] += 1
            status = "✅ PASS"
        else:
            results['failed'] += 1
            status = "❌ FAIL"
            results['failed_cases'].append({
                'test_num': idx,
                'angle_rad': angle_rad,
                'angle_deg': math.degrees(angle_rad),
                'cos_error': cos_err,
                'sin_error': sin_err,
                'fpga_cos': fpga_cos,
                'fpga_sin': fpga_sin,
                'expected_cos': expected_cos,
                'expected_sin': expected_sin
            })

        if idx % 10 == 0 or not test_passed:
            print(f"Test {idx:3d}: θ={angle_rad:6.3f} rad ({math.degrees(angle_rad):6.1f}°) "
                  f"| cos_err={cos_err:.6f}, sin_err={sin_err:.6f} | {status}")

    end_ms = utime.ticks_ms()
    results['execution_time'] = utime.ticks_diff(end_ms, start_ms) / 1000.0

    if results['cos_errors']:
        results['mean_cos_error'] = sum(results['cos_errors']) / len(results['cos_errors'])
        results['mean_sin_error'] = sum(results['sin_errors']) / len(results['sin_errors'])
    else:
        results['mean_cos_error'] = 0.0
        results['mean_sin_error'] = 0.0

    print("\n" + "=" * 64)
    print("REGRESSION TEST SUMMARY")
    print("=" * 64)
    print(f"Total tests run:     {results['total_tests']}")
    print(f"Passed:              {results['passed']} ({100.0 * results['passed'] / results['total_tests']:.1f}%)")
    print(f"Failed:              {results['failed']} ({100.0 * results['failed'] / results['total_tests']:.1f}%)")
    print(f"Execution time:      {results['execution_time']:.2f} seconds")
    print(f"Max cosine error:    {results['max_cos_error']:.8f}")
    print(f"Max sine error:      {results['max_sin_error']:.8f}")
    print(f"Mean cosine error:   {results['mean_cos_error']:.8f}")
    print(f"Mean sine error:     {results['mean_sin_error']:.8f}")

    if results['failed'] > 0:
        print("\nFAILED TEST DETAILS:")
        print("-" * 64)
        for case in results['failed_cases']:
            print(f"Test {case['test_num']:3d}: θ={case['angle_deg']:6.1f}° "
                  f"| FPGA: cos={case['fpga_cos']:+.6f}, sin={case['fpga_sin']:+.6f}")
            print(f"         Expected: cos={case['expected_cos']:+.6f}, sin={case['expected_sin']:+.6f}")
            print(f"         Errors:   cos={case['cos_error']:.8f}, sin={case['sin_error']:.8f}\n")

    if results['failed'] == 0:
        print("🎉 ALL TESTS PASSED! CORDIC IP looks good.")
    else:
        print("⚠️  Some tests failed. Please review the CORDIC implementation and wiring.")

    return results

# === Additional utility functions ===

def run_quick_test(tolerance=5.741e-3):
    """Run a quick 10-angle test for debugging."""
    return run_cordic_regression_test(num_angles=10, tolerance=tolerance)

def run_comprehensive_test(tolerance=5.741e-3):
    """Run full 100-angle regression test."""
    return run_cordic_regression_test(num_angles=100, tolerance=tolerance)

def run_high_precision_test(tolerance=5.741e-3):
    """Run test with tighter tolerance."""
    return run_cordic_regression_test(num_angles=100, tolerance=tolerance)

def run_custom_tolerance_test(cos_tolerance=5.741e-3, sin_tolerance=5.741e-3):
    """Run test with different tolerances for cos and sin."""
    return run_cordic_regression_test(num_angles=100, cos_tolerance=cos_tolerance, sin_tolerance=sin_tolerance)

if __name__ == "__main__":
    res = run_comprehensive_test()

    # Save results to file with timestamp
    t = utime.localtime()
    timestamp = "{:04d}{:02d}{:02d}_{:02d}{:02d}{:02d}".format(t[0], t[1], t[2], t[3], t[4], t[5])
    filename = "cordic_test_results_{}.json".format(timestamp)

    try:
        with open(filename, "w") as f:
            json.dump(res, f)
        print("\nTest results saved to:", filename)
    except Exception as e:
        print("Failed to save results to file:", e)