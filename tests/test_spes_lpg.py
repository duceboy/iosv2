"""0192 LPG (vibration PWM) allow-list and register values: compile bsd/dev/spes_lpg.h from the patch on
the host, and recompute the values with a Python copy of Linux pwm-qti-lpg.c's period/duty search."""
from pathlib import Path
import subprocess
import tempfile
import unittest

from test_spes_ufs_log import new_file_from_patch

ROOT = Path(__file__).resolve().parents[1]
PATCH = ROOT / 'xnu/patches/0192-spes-vib-lpg-write.patch'

C_TEST = r'''
#include <stdint.h>
#include <stdbool.h>
#include <stdio.h>
#include "spes_lpg.h"
static int fails;
#define CHECK(c) do { if (!(c)) { printf("FAIL line %d: %s\n", __LINE__, #c); fails++; } } while (0)
int main(void)
{
	for (uint32_t a = 0xb340; a <= 0xb347; a++) CHECK(spes_lpg_write_allowed(1, a, 1));
	CHECK(!spes_lpg_write_allowed(1, 0xb33f, 1));
	CHECK(!spes_lpg_write_allowed(1, 0xb348, 1));
	CHECK(!spes_lpg_write_allowed(1, 0xb305, 1));      /* subtype */
	CHECK(!spes_lpg_write_allowed(1, 0xb350, 1));      /* ramp registers */
	CHECK(!spes_lpg_write_allowed(0, 0xb346, 1));      /* PMIC SID 0 */
	CHECK(!spes_lpg_write_allowed(0, 0x88F, 1));       /* PON belongs to the other list */
	CHECK(!spes_lpg_write_allowed(2, 0xb346, 1));
	CHECK(!spes_lpg_write_allowed(UINT32_MAX, 0xb346, 1));
	CHECK(!spes_lpg_write_allowed(1, 0xb346, 0));
	CHECK(!spes_lpg_write_allowed(1, 0xb346, 2));
	CHECK(!spes_lpg_write_allowed(1, 0x1b346, 1));
	CHECK(!spes_lpg_write_allowed(1, 0xffffb346, 1));
	CHECK(spes_lpg_masked(0xff, 0x07, 0x07) == 0xff);
	CHECK(spes_lpg_masked(0x00, 0x67, 0x01) == 0x01);
	CHECK(spes_lpg_masked(0xff, 0x86, 0x04) == 0x7d);
	CHECK(spes_lpg_masked(0x00, 0x86, 0x84) == 0x84);
	CHECK(spes_lpg_masked(0x18, 0x20, 0x20) == 0x38);
	CHECK(spes_vib_clamp_ms(0) == 1);
	CHECK(spes_vib_clamp_ms(100) == 100);
	CHECK(spes_vib_clamp_ms(101) == 100);
	CHECK(spes_vib_clamp_ms(UINT32_MAX) == 100);
	printf("SIZE %u %u PREDIV %u %u MSB %u VALUE %u ON %u OFF %u GL %u\n", SPES_LPG_SIZE_CLK_MASK,
	    SPES_LPG_SIZE_CLK_VAL, SPES_LPG_PREDIV_MASK, SPES_LPG_PREDIV_VAL, SPES_LPG_MSB_MASK, SPES_LPG_VALUE,
	    SPES_LPG_ENABLE_ON, SPES_LPG_ENABLE_OFF, SPES_LPG_GLITCH_BIT);
	printf("%d failures\n", fails);
	return fails != 0;
}
'''

PWM_SIZE = [6, 9]
CLK_HZ = [1024, 32768, 19200000]
PREDIV = [1, 3, 5, 6]
EXP = list(range(8))


def linux_lpg(period_ns, duty_ns):
    """__qpnp_lpg_calc_pwm_period + __qpnp_lpg_calc_pwm_duty (no SDAM), min deltas kept across sizes."""
    best = None
    min_clk = min_period = 2**64
    for n, size in enumerate(PWM_SIZE):
        pcp = period_ns >> size
        cfg = None
        for hz in reversed(CLK_HZ):
            for pd in PREDIV:
                for e in EXP:
                    cp = (1 << e) * pd * (10**9 // hz)
                    if abs(pcp - cp) < min_clk:
                        min_clk = abs(pcp - cp)
                        cfg = dict(hz=hz, prediv=pd, exp=e, size=size)
        if cfg is not None and (min_clk << size) < min_period:
            min_period = min_clk << size
            best = cfg
    for size in reversed(PWM_SIZE[1:]):
        if best['size'] >= size:
            break
        step = size - best['size']
        if best['exp'] >= step:
            best['size'], best['exp'] = size, best['exp'] - step
    value = min((duty_ns << best['size']) // period_ns, (1 << best['size']) - 1)
    size_clk = (PWM_SIZE.index(best['size']) << 2) | (CLK_HZ.index(best['hz']) + 1)   # SUBTYPE_PWM
    prediv = (PREDIV.index(best['prediv']) << 5) | best['exp']
    return size_clk, prediv, value


class LpgTests(unittest.TestCase):
    def test_header(self):
        header = new_file_from_patch(PATCH, 'bsd/dev/spes_lpg.h')
        with tempfile.TemporaryDirectory() as d:
            Path(d, 'spes_lpg.h').write_text(header)
            Path(d, 't.c').write_text(C_TEST)
            subprocess.run(['cc', '-std=c11', '-Wall', '-Wextra', '-Werror', '-o', 't', 't.c'], cwd=d, check=True)
            r = subprocess.run(['./t'], cwd=d, capture_output=True, text=True)
            self.assertEqual(r.returncode, 0, r.stdout)
            self.assertIn('0 failures', r.stdout)
        size_clk, prediv, value = linux_lpg(50000, 42500)       # motor PWM from the OrangeFox log
        self.assertEqual((size_clk, prediv, value), (0x07, 0x01, 435))
        self.assertEqual(value, 435)
        self.assertIn('VALUE', r.stdout)
        self.assertIn(f'VALUE {value}', r.stdout)
        self.assertIn(f'SIZE 7 {size_clk}', r.stdout)
        self.assertIn(f'PREDIV 103 {prediv}', r.stdout)
        self.assertIn('ON 132 OFF 4 GL 32', r.stdout)            # 0x84 / 0x04 / bit 5

    def test_counter_example(self):
        # the search must change with the period: 1 kHz picks other settings (guards against constants)
        self.assertNotEqual(linux_lpg(1000000, 500000), (0x07, 0x01, 435))


if __name__ == '__main__':
    unittest.main()
