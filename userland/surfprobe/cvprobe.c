/* cvprobe: make a CoreVideo pixel buffer backed by an IOSurface and print the plane geometry as CoreVideo sees it,
 * as IOSurface reports it, and as a second reference (lookup by ID) reports it. Own code. Usage: cvprobe W H [FOURCC] */
#include <CoreFoundation/CoreFoundation.h>
#include <CoreVideo/CoreVideo.h>
#include <IOSurface/IOSurfaceRef.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

static void show(const char *who, IOSurfaceRef s)
{
	uint8_t *base = IOSurfaceGetBaseAddress(s);
	printf("%s: id %u %zux%zu bpe %zu bpr %zu alloc %zu planes %zu\n", who, IOSurfaceGetID(s), IOSurfaceGetWidth(s),
	    IOSurfaceGetHeight(s), IOSurfaceGetBytesPerElement(s), IOSurfaceGetBytesPerRow(s), IOSurfaceGetAllocSize(s),
	    IOSurfaceGetPlaneCount(s));
	for (size_t i = 0; i < IOSurfaceGetPlaneCount(s); i++) {
		printf("  plane %zu: %zux%zu bpe %zu bpr %zu at +%ld\n", i, IOSurfaceGetWidthOfPlane(s, i), IOSurfaceGetHeightOfPlane(s, i),
		    IOSurfaceGetBytesPerElementOfPlane(s, i), IOSurfaceGetBytesPerRowOfPlane(s, i),
		    (long)((uint8_t *)IOSurfaceGetBaseAddressOfPlane(s, i) - base));
	}
}

int main(int argc, char **argv)
{
	size_t w = argc > 1 ? strtoul(argv[1], NULL, 0) : 787, h = argc > 2 ? strtoul(argv[2], NULL, 0) : 1705;
	const char *cc = argc > 3 ? argv[3] : "420f";
	OSType f = ((OSType)cc[0] << 24) | ((OSType)cc[1] << 16) | ((OSType)cc[2] << 8) | (OSType)cc[3];
	CFDictionaryRef empty = CFDictionaryCreate(NULL, NULL, NULL, 0, &kCFTypeDictionaryKeyCallBacks, &kCFTypeDictionaryValueCallBacks);
	const void *k[] = { kCVPixelBufferIOSurfacePropertiesKey }, *v[] = { empty };
	CFDictionaryRef attrs = CFDictionaryCreate(NULL, k, v, 1, &kCFTypeDictionaryKeyCallBacks, &kCFTypeDictionaryValueCallBacks);
	CVPixelBufferRef pb = NULL;
	CVReturn r = CVPixelBufferCreate(NULL, w, h, f, attrs, &pb);
	if (r != 0 || pb == NULL) { printf("CVPixelBufferCreate %zux%zu '%s': %d\n", w, h, cc, r); return 1; }
	CVPixelBufferLockBaseAddress(pb, 0);
	printf("CoreVideo: %zux%zu planes %zu\n", CVPixelBufferGetWidth(pb), CVPixelBufferGetHeight(pb), CVPixelBufferGetPlaneCount(pb));
	uint8_t *b0 = CVPixelBufferGetBaseAddressOfPlane(pb, 0);
	for (size_t i = 0; i < CVPixelBufferGetPlaneCount(pb); i++) {
		printf("  plane %zu: %zux%zu bpr %zu at plane0%+ld\n", i, CVPixelBufferGetWidthOfPlane(pb, i), CVPixelBufferGetHeightOfPlane(pb, i),
		    CVPixelBufferGetBytesPerRowOfPlane(pb, i), (long)((uint8_t *)CVPixelBufferGetBaseAddressOfPlane(pb, i) - b0));
	}
	IOSurfaceRef s = CVPixelBufferGetIOSurface(pb);
	if (s == NULL) { printf("no IOSurface behind it\n"); return 1; }
	IOSurfaceLock(s, kIOSurfaceLockReadOnly, NULL);
	show("IOSurface (creator)", s);
	IOSurfaceRef again = IOSurfaceLookup(IOSurfaceGetID(s));
	if (again != NULL) { IOSurfaceLock(again, kIOSurfaceLockReadOnly, NULL); show("IOSurface (lookup)", again); }
	else printf("lookup of own id failed\n");
	return 0;
}
