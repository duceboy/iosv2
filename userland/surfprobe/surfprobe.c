/* surfprobe: look an IOSurface up by ID, print its geometry (every plane) and write plane 0 as a PGM whose
 * width is the plane's full bytes per row, so a wrong stride shows as it is. Own code.
 * Usage: surfprobe ID [OUT.pgm] */
#include <CoreFoundation/CoreFoundation.h>
#include <IOSurface/IOSurfaceRef.h>
#include <stdio.h>
#include <stdlib.h>

int main(int argc, char **argv)
{
	if (argc < 2) { fprintf(stderr, "usage: surfprobe ID [OUT.pgm]\n"); return 2; }
	IOSurfaceRef s = IOSurfaceLookup((IOSurfaceID)strtoul(argv[1], NULL, 0));
	if (s == NULL) { printf("id %s: lookup failed\n", argv[1]); return 1; }
	uint32_t f = IOSurfaceGetPixelFormat(s);
	size_t n = IOSurfaceGetPlaneCount(s);
	printf("id %u '%c%c%c%c' %zux%zu bpe %zu bpr %zu alloc %zu planes %zu\n", IOSurfaceGetID(s), f >> 24, (f >> 16) & 255,
	    (f >> 8) & 255, f & 255, IOSurfaceGetWidth(s), IOSurfaceGetHeight(s), IOSurfaceGetBytesPerElement(s),
	    IOSurfaceGetBytesPerRow(s), IOSurfaceGetAllocSize(s), n);
	if (IOSurfaceLock(s, kIOSurfaceLockReadOnly, NULL) != 0) { printf("lock failed\n"); return 1; }
	uint8_t *base = IOSurfaceGetBaseAddress(s);
	for (size_t i = 0; i < n; i++) {
		printf(" plane %zu: %zux%zu bpe %zu bpr %zu elem %zux%zu at +%ld\n", i, IOSurfaceGetWidthOfPlane(s, i),
		    IOSurfaceGetHeightOfPlane(s, i), IOSurfaceGetBytesPerElementOfPlane(s, i), IOSurfaceGetBytesPerRowOfPlane(s, i),
		    IOSurfaceGetElementWidthOfPlane(s, i), IOSurfaceGetElementHeightOfPlane(s, i),
		    (long)((uint8_t *)IOSurfaceGetBaseAddressOfPlane(s, i) - base));
	}
	if (argc > 2 && n > 0) {
		size_t row = IOSurfaceGetBytesPerRowOfPlane(s, 0), h = IOSurfaceGetHeightOfPlane(s, 0);
		FILE *o = fopen(argv[2], "wb");
		if (o != NULL && row > 0) {
			fprintf(o, "P5\n%zu %zu\n255\n", row, h);
			fwrite(IOSurfaceGetBaseAddressOfPlane(s, 0), 1, row * h, o);
			fclose(o);
			printf(" plane 0 written: %zu x %zu\n", row, h);
		}
	}
	IOSurfaceUnlock(s, kIOSurfaceLockReadOnly, NULL);
	return 0;
}
