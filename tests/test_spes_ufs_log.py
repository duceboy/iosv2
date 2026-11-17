"""0178 log-only bounds: compile bsd/dev/spes_ufs_log.h exactly as the patch adds it, on the host."""
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
PATCH = ROOT / 'xnu/patches/0178-spes-ufs-log-only.patch'


def new_file_from_patch(patch, path):
    """The lines a patch adds as the new file `path` (a/dev/null -> b/path)."""
    lines, inside = [], False
    for line in patch.read_text().splitlines():
        if line.startswith('+++ '):
            inside = line == f'+++ b/{path}'
            continue
        if line.startswith('diff --git'):
            inside = False
        if inside and line.startswith('+'):
            lines.append(line[1:])
    if not lines:
        raise AssertionError(f'{path} not added by {patch.name}')
    return '\n'.join(lines) + '\n'


C_TEST = r'''
#include <stdint.h>
#include <stdbool.h>
#include <stdio.h>
#include "spes_ufs_log.h"
#define LOG 1025u                       /* 1 + 4 MiB / 4 KiB, SWEET_LOG_BLOCKS */
static int fails;
#define CHECK(c) do { if (!(c)) { printf("FAIL line %d: %s\n", __LINE__, #c); fails++; } } while (0)
int main(void)
{
	/* synthetic partition (not a real phone's): first 0x300000, 100000 MiB of 4 KiB blocks */
	const uint64_t first = 0x300000, n = 100000ull * 256, end = first + n;   /* end: first block after */
	const uint64_t lo = spes_ufs_log_lo(first, n, LOG);
	CHECK(lo == end - LOG);
	/* first / last allowed block, one before, one behind */
	CHECK(spes_ufs_log_write_ok(lo, 1, first, n, lo));
	CHECK(spes_ufs_log_write_ok(end - 1, 1, first, n, lo));
	CHECK(!spes_ufs_log_write_ok(lo - 1, 1, first, n, lo));
	CHECK(!spes_ufs_log_write_ok(end, 1, first, n, lo));
	/* lengths > 1 block: the whole area fits, one more does not, crossing either edge does not */
	CHECK(spes_ufs_log_write_ok(lo, LOG, first, n, lo));
	CHECK(!spes_ufs_log_write_ok(lo, LOG + 1, first, n, lo));
	CHECK(spes_ufs_log_write_ok(end - 2, 2, first, n, lo));
	CHECK(!spes_ufs_log_write_ok(end - 1, 2, first, n, lo));
	CHECK(!spes_ufs_log_write_ok(lo - 1, 2, first, n, lo));
	/* overflow: lba + count would wrap */
	CHECK(!spes_ufs_log_write_ok(lo, UINT64_MAX, first, n, lo));
	CHECK(!spes_ufs_log_write_ok(UINT64_MAX, 2, first, n, lo));
	CHECK(!spes_ufs_log_write_ok(end - 1, UINT64_MAX - (end - 1) + 1, first, n, lo));
	/* nothing written without a log area, with count 0, or the whole partition */
	CHECK(!spes_ufs_log_write_ok(lo, 0, first, n, lo));
	CHECK(!spes_ufs_log_write_ok(lo, 1, first, n, 0));
	CHECK(!spes_ufs_log_write_ok(first, 1, first, n, lo));
	CHECK(!spes_ufs_log_write_ok(first, n, first, n, lo));
	/* log_lo outside the partition is refused */
	CHECK(!spes_ufs_log_write_ok(end, 1, first, n, end));
	CHECK(!spes_ufs_log_write_ok(first - 1, 1, first, n, first - 1));
	/* too small a partition or a wrapping one has no log area */
	CHECK(spes_ufs_log_lo(first, 2 * LOG - 1, LOG) == 0);
	CHECK(spes_ufs_log_lo(first, 2 * LOG, LOG) == first + LOG);
	CHECK(spes_ufs_log_lo(UINT64_MAX - 10, 2 * LOG, LOG) == 0);
	CHECK(spes_ufs_log_lo(first, n, 0) == 0);
	printf("%d failures\n", fails);
	return fails != 0;
}
'''


class UfsLogBoundsTests(unittest.TestCase):
    def test_edges(self):
        header = new_file_from_patch(PATCH, 'bsd/dev/spes_ufs_log.h')
        with tempfile.TemporaryDirectory() as d:
            Path(d, 'spes_ufs_log.h').write_text(header)
            Path(d, 't.c').write_text(C_TEST)
            subprocess.run(['cc', '-std=c11', '-Wall', '-Wextra', '-Werror', '-o', 't', 't.c'],
                           cwd=d, check=True)
            r = subprocess.run(['./t'], cwd=d, capture_output=True, text=True)
            self.assertEqual(r.returncode, 0, r.stdout)
            self.assertIn('0 failures', r.stdout)


if __name__ == '__main__':
    unittest.main()
