"""0185 PMIC write allow-list: compile bsd/dev/spes_spmi_allow.h exactly as the patch adds it, on the host."""
from pathlib import Path
import subprocess
import tempfile
import unittest

from test_spes_ufs_log import new_file_from_patch

ROOT = Path(__file__).resolve().parents[1]
PATCH = ROOT / 'xnu/patches/0185-spes-pon-read-allowlist.patch'

C_TEST = r'''
#include <stdint.h>
#include <stdbool.h>
#include <stdio.h>
#include "spes_spmi_allow.h"
static int fails;
#define CHECK(c) do { if (!(c)) { printf("FAIL line %d: %s\n", __LINE__, #c); fails++; } } while (0)
int main(void)
{
	/* the one allowed register */
	CHECK(spes_spmi_write_allowed(0, 0x88F, 1));
	/* address one before / one behind, the PON base, other PON registers, the LPG */
	CHECK(!spes_spmi_write_allowed(0, 0x88E, 1));
	CHECK(!spes_spmi_write_allowed(0, 0x890, 1));
	CHECK(!spes_spmi_write_allowed(0, 0x800, 1));
	CHECK(!spes_spmi_write_allowed(0, 0x85A, 1));       /* PS_HOLD reset control: not allowed */
	CHECK(!spes_spmi_write_allowed(0, 0x85B, 1));
	CHECK(!spes_spmi_write_allowed(1, 0xB346, 1));      /* LPG: not in this allow-list (yet) */
	/* other SID with the same offset */
	CHECK(!spes_spmi_write_allowed(1, 0x88F, 1));
	CHECK(!spes_spmi_write_allowed(2, 0x88F, 1));
	CHECK(!spes_spmi_write_allowed(UINT32_MAX, 0x88F, 1));
	/* other lengths */
	CHECK(!spes_spmi_write_allowed(0, 0x88F, 0));
	CHECK(!spes_spmi_write_allowed(0, 0x88F, 2));
	CHECK(!spes_spmi_write_allowed(0, 0x88F, UINT32_MAX));
	/* address aliases above 16 bits */
	CHECK(!spes_spmi_write_allowed(0, 0x1088F, 1));
	CHECK(!spes_spmi_write_allowed(0, 0xFFFF088F, 1));
	/* the value: gen2 keeps bit 0, bits 7:1 = 2 */
	CHECK(spes_pon_bootloader_value(0x00, 0x04) == 0x04);
	CHECK(spes_pon_bootloader_value(0x01, 0x04) == 0x05);
	CHECK(spes_pon_bootloader_value(0xFE, 0x05) == 0x04);
	CHECK(spes_pon_bootloader_value(0xFF, 0x05) == 0x05);
	/* not gen2: no write */
	CHECK(spes_pon_bootloader_value(0x00, 0x00) == -1);
	CHECK(spes_pon_bootloader_value(0x00, 0x03) == -1);
	CHECK(spes_pon_bootloader_value(0x00, 0x06) == -1);
	CHECK(spes_pon_bootloader_value(0x00, 0xFF) == -1);
	printf("%d failures\n", fails);
	return fails != 0;
}
'''


class SpmiAllowTests(unittest.TestCase):
    def test_allow_list(self):
        header = new_file_from_patch(PATCH, 'bsd/dev/spes_spmi_allow.h')
        with tempfile.TemporaryDirectory() as d:
            Path(d, 'spes_spmi_allow.h').write_text(header)
            Path(d, 't.c').write_text(C_TEST)
            subprocess.run(['cc', '-std=c11', '-Wall', '-Wextra', '-Werror', '-o', 't', 't.c'], cwd=d, check=True)
            r = subprocess.run(['./t'], cwd=d, capture_output=True, text=True)
            self.assertEqual(r.returncode, 0, r.stdout)
            self.assertIn('0 failures', r.stdout)


if __name__ == '__main__':
    unittest.main()
