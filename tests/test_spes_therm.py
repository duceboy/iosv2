"""spes_therm.h: Rechen- und Prüf-Logik auf dem Host (TSENS-Umrechnung, RTC, ADC-Listen und -Umrechnung).

Der Header kommt aus dem Patch 0218.
"""
from pathlib import Path
import subprocess
import tempfile
import unittest

from test_spes_ufs_log import new_file_from_patch

PATCH = Path(__file__).resolve().parents[1] / 'xnu/patches/0218-spes-therm-tsens-rtc-readonly.patch'

C_TEST = r'''
#include <stdint.h>
#include <stdbool.h>
#include <stdio.h>
#include "spes_therm.h"
static int fails;
#define CHECK(c) do { if (!(c)) { printf("FAIL line %d: %s\n", __LINE__, #c); fails++; } } while (0)
int main(void)
{
	/* TSENS: 12 bit two's complement tenths -> mdegC */
	CHECK(spes_tsens_code_to_mc(0) == 0);
	CHECK(spes_tsens_code_to_mc(345) == 34500);
	CHECK(spes_tsens_code_to_mc(0x7ff) == 204700);
	CHECK(spes_tsens_code_to_mc(0x800) == -204800);
	CHECK(spes_tsens_code_to_mc(0xfff) == -100);
	CHECK(spes_tsens_code_to_mc(SPES_TSENS_VALID | (1u << 19) | 0x159) == 34500);   /* flags ignored */
	/* enable mask: bit 0 = controller on, bits 18:3 = sensors */
	CHECK(spes_tsens_enabled_mask(0x0007fff9) == 0xffff);
	CHECK(spes_tsens_enabled_mask(0x0007fff8) == 0);          /* controller off */
	CHECK(spes_tsens_enabled_mask(0x00000009) == 0x0001);
	CHECK(spes_tsens_enabled_mask(0x00040001) == 0x8000);
	/* three-read rule */
	CHECK(spes_tsens_pick(SPES_TSENS_VALID | 300, 0, 0) == 30000);
	CHECK(spes_tsens_pick(100, SPES_TSENS_VALID | 310, 0) == 31000);
	CHECK(spes_tsens_pick(100, 200, SPES_TSENS_VALID | 320) == 32000);
	CHECK(spes_tsens_pick(100, 100, 300) == 10000);           /* 1st == 2nd */
	CHECK(spes_tsens_pick(100, 200, 200) == 20000);           /* 2nd == 3rd */
	CHECK(spes_tsens_pick(100, 200, 300) == 10000);           /* nothing agrees: first */

	/* RTC */
	const uint8_t b[4] = { 0x78, 0x56, 0x34, 0x12 };
	CHECK(spes_rtc_assemble(b) == 0x12345678u);
	CHECK(spes_rtc_read_consistent(0x10, 0x10));
	CHECK(spes_rtc_read_consistent(0x10, 0x11));
	CHECK(!spes_rtc_read_consistent(0xff, 0x00));             /* carry between the reads */
	CHECK(spes_rtc_to_utc(1000, 0) == 0);                     /* no offset */
	CHECK(spes_rtc_to_utc(1000, 1794880000ull) == 1794881000ull);
	CHECK(spes_rtc_to_utc(1000, 1000) == 0);                  /* 1970: not plausible */
	CHECK(spes_rtc_to_utc(0xffffffffu, 4102444800ull) == 0);  /* after 2100 */

	/* SPMI read list: exactly the registers the driver reads */
	CHECK(spes_therm_spmi_read_allowed(0, 0x6046));
	CHECK(spes_therm_spmi_read_allowed(0, 0x6048) && spes_therm_spmi_read_allowed(0, 0x604b));
	CHECK(!spes_therm_spmi_read_allowed(0, 0x6047) && !spes_therm_spmi_read_allowed(0, 0x604c));
	CHECK(!spes_therm_spmi_read_allowed(0, 0x6040));          /* RTC write data: not even read */
	CHECK(!spes_therm_spmi_read_allowed(0, 0x6146));          /* alarm block */
	CHECK(spes_therm_spmi_read_allowed(0, 0x2405) && spes_therm_spmi_read_allowed(0, 0x2408) && spes_therm_spmi_read_allowed(0, 0x2440));
	CHECK(!spes_therm_spmi_read_allowed(0, 0x2446));
	CHECK(spes_therm_spmi_read_allowed(0, 0x3108) && spes_therm_spmi_read_allowed(0, 0x3142) && spes_therm_spmi_read_allowed(0, 0x3147));
	CHECK(spes_therm_spmi_read_allowed(0, 0x3150) && spes_therm_spmi_read_allowed(0, 0x3151));
	CHECK(!spes_therm_spmi_read_allowed(0, 0x3148) && !spes_therm_spmi_read_allowed(0, 0x3152));
	CHECK(!spes_therm_spmi_read_allowed(0, 0x3542));          /* ADC_TM */
	CHECK(!spes_therm_spmi_read_allowed(1, 0x6046) && !spes_therm_spmi_read_allowed(1, 0x3142));
	CHECK(!spes_therm_spmi_read_allowed(0, 0x16046));

	/* SPMI write list: SID 0, 0x3142..0x3147, one byte; nothing else */
	for (uint32_t a = 0x3142; a <= 0x3147; a++) {
		CHECK(spes_therm_adc_write_allowed(0, a, 1));
		CHECK(!spes_therm_adc_write_allowed(1, a, 1));
		CHECK(!spes_therm_adc_write_allowed(0, a, 0));
		CHECK(!spes_therm_adc_write_allowed(0, a, 2));
		CHECK(!spes_therm_adc_write_allowed(0, a | 0x10000u, 1));
	}
	CHECK(!spes_therm_adc_write_allowed(0, 0x3141, 1));
	CHECK(!spes_therm_adc_write_allowed(0, 0x3148, 1));
	CHECK(!spes_therm_adc_write_allowed(0, 0x3140, 1));
	CHECK(!spes_therm_adc_write_allowed(0, 0x3442, 1) && !spes_therm_adc_write_allowed(0, 0x3542, 1));   /* ADC_TM */
	CHECK(!spes_therm_adc_write_allowed(0, 0x6040, 1) && !spes_therm_adc_write_allowed(0, 0x6046, 1));   /* RTC */
	CHECK(!spes_therm_adc_write_allowed(0, 0x6146, 1));       /* RTC alarm */
	CHECK(!spes_therm_adc_write_allowed(0, 0x88F, 1));        /* PON belongs to spes_spmi_allow.h */
	CHECK(!spes_therm_adc_write_allowed(0, 0x2440, 1));       /* temp alarm */

	/* channels: the 11 live-FDT ones, nothing else */
	CHECK(SPES_ADC_NCHAN == 11);
	CHECK(spes_adc_chan_find(0x4c) && spes_adc_chan_find(0x4c)->kind == SPES_ADC_NTC);
	CHECK(spes_adc_chan_find(0x06) && spes_adc_chan_find(0x06)->kind == SPES_ADC_DIE);
	CHECK(spes_adc_chan_find(0x83) && spes_adc_chan_find(0x83)->den == 3);
	CHECK(!spes_adc_chan_find(0x4a) && !spes_adc_chan_find(0x4b));   /* battery thermistor / battery ID: not in the FDT */
	CHECK(!spes_adc_chan_find(0x07) && !spes_adc_chan_find(0x08) && !spes_adc_chan_find(0x09));   /* USB/charger channels */
	CHECK(!spes_adc_chan_find(0x14c));

	/* register values as Linux adc_configure() builds them */
	const struct spes_adc_chan *xo = spes_adc_chan_find(0x4c), *die = spes_adc_chan_find(0x06);
	CHECK(spes_adc_dig_param(0x00, xo) == 0x18);
	CHECK(spes_adc_dig_param(0xff, xo) == 0x9b);              /* bits 7, 1, 0 kept */
	CHECK(spes_adc_dig_param(0x00, die) == 0x28);
	CHECK(spes_adc_fast_avg(0x87) == 0x80);
	CHECK(spes_adc_delay(0xf0, xo) == 0xf2);
	CHECK(spes_adc_delay(0xff, die) == 0xf0);

	/* value gate: target value or restore value, per register */
	CHECK(spes_therm_adc_value_ok(0x3142, 0x18, 0x00, 0x4c));
	CHECK(spes_therm_adc_value_ok(0x3142, 0x00, 0x00, 0x4c)); /* restore */
	CHECK(!spes_therm_adc_value_ok(0x3142, 0x58, 0x00, 0x4c));/* cal_val bit: not ours */
	CHECK(!spes_therm_adc_value_ok(0x3142, 0x28, 0x00, 0x4c));/* absolute cal on a thermistor */
	CHECK(spes_therm_adc_value_ok(0x3144, 0x4c, 0x00, 0x4c));
	CHECK(!spes_therm_adc_value_ok(0x3144, 0x4d, 0x00, 0x4c));/* other channel than announced */
	CHECK(!spes_therm_adc_value_ok(0x3144, 0x4a, 0x00, 0x4a));/* channel not in the FDT */
	CHECK(spes_therm_adc_value_ok(0x3146, 0x80, 0x00, 0x4c));
	CHECK(spes_therm_adc_value_ok(0x3146, 0x00, 0x00, 0x4c));
	CHECK(!spes_therm_adc_value_ok(0x3146, 0xc0, 0x00, 0x4c));
	CHECK(spes_therm_adc_value_ok(0x3147, 0x80, 0x00, 0x4c));
	CHECK(!spes_therm_adc_value_ok(0x3147, 0x00, 0x00, 0x4c));
	CHECK(!spes_therm_adc_value_ok(0x3147, 0x81, 0x00, 0x4c));
	CHECK(!spes_therm_adc_value_ok(0x3148, 0x00, 0x00, 0x4c));
	CHECK(!spes_therm_adc_value_ok(0x3141, 0x00, 0x00, 0x4c));

	/* conversion */
	CHECK(spes_adc_code_to_uv(0, 1) == 0);
	CHECK(spes_adc_code_to_uv(0x70e4, 1) == 1875000);         /* full scale = reference */
	CHECK(spes_adc_code_to_uv(0x70e4, 3) == 5625000);
	CHECK(spes_adc_code_to_uv(0x8000, 1) == 0);               /* above the maximum code: 0, as Linux */
	CHECK(spes_adc_die_mc(0) == -273150);
	/* 596.3 mV at the die sensor = 298.15 K = 25 degC: code = 596300 * 0x70e4 / 1875000 = 9191 */
	CHECK(spes_adc_die_mc(9191) > 24800 && spes_adc_die_mc(9191) < 25200);
	/* thermistor table: exact points, clamps, interpolation, monotony */
	CHECK(spes_adc_ntc_mc(0x70e4) == -40000);                 /* 1.875 V: colder than the table */
	CHECK(spes_adc_ntc_mc(0) == 125000);                      /* 0 V: hotter than the table */
	/* 937000 uV = 25 degC: code 14442 gives 936955 uV -> just above 25000 */
	CHECK(spes_adc_ntc_mc(14442) >= 25000 && spes_adc_ntc_mc(14442) <= 25010);
	/* halfway between 937000 (25) and 828000 (30): 882500 uV -> code 13603 -> about 27500 */
	CHECK(spes_adc_ntc_mc(13603) > 27400 && spes_adc_ntc_mc(13603) < 27600);
	int prev = -40001;
	for (uint32_t code = 0x70e4; ; code -= 4) {
		int mc = spes_adc_ntc_mc(code);
		CHECK(mc >= prev);                                    /* lower voltage = hotter, never backwards */
		prev = mc;
		if (code < 4) {
			break;
		}
	}
	CHECK(spes_adc_convert(xo, 14442) == spes_adc_ntc_mc(14442));
	CHECK(spes_adc_convert(die, 9191) == spes_adc_die_mc(9191));
	CHECK(spes_adc_convert(spes_adc_chan_find(0x83), 0x70e4) == 5625000);
	printf("%d failures\n", fails);
	return fails != 0;
}
'''


class ThermTests(unittest.TestCase):
    def test_header_logic(self):
        header = new_file_from_patch(PATCH, 'bsd/dev/spes_therm.h')
        with tempfile.TemporaryDirectory() as d:
            (Path(d) / 'spes_therm.h').write_text(header)
            (Path(d) / 't.c').write_text(C_TEST)
            subprocess.run(['cc', '-std=c11', '-Wall', '-Wextra', '-Werror', '-o', 't', 't.c'], cwd=d, check=True)
            run = subprocess.run(['./t'], cwd=d, capture_output=True, text=True)
            self.assertEqual(run.returncode, 0, run.stdout + run.stderr)
            self.assertIn('0 failures', run.stdout)


if __name__ == '__main__':
    unittest.main()
