/* vtprobe: decode an H.264 file with AVAssetReader (VideoToolbox, 420v IOSurfaces) and report frames. Own code.
 * Reproduces the video path that crashes mediaserverd, inside this process. Usage: vtprobe FILE [biplanar=1] */
#import <AVFoundation/AVFoundation.h>
#import <CoreVideo/CoreVideo.h>
#include <stdio.h>

int main(int argc, char **argv)
{
	@autoreleasepool {
		if (argc < 2) { printf("usage: vtprobe FILE\n"); return 2; }
		NSURL *u = [NSURL fileURLWithPath:[NSString stringWithUTF8String:argv[1]]];
		AVAsset *a = [AVAsset assetWithURL:u];
		AVAssetTrack *t = [[a tracksWithMediaType:AVMediaTypeVideo] firstObject];
		if (!t) { printf("no video track\n"); return 1; }
		NSError *e = nil;
		AVAssetReader *r = [AVAssetReader assetReaderWithAsset:a error:&e];
		OSType fmt = (argc > 2 && atoi(argv[2]) == 0) ? kCVPixelFormatType_32BGRA : kCVPixelFormatType_420YpCbCr8BiPlanarVideoRange;
		NSDictionary *o = @{ (id)kCVPixelBufferPixelFormatTypeKey: @(fmt), (id)kCVPixelBufferIOSurfacePropertiesKey: @{} };
		AVAssetReaderTrackOutput *out = [AVAssetReaderTrackOutput assetReaderTrackOutputWithTrack:t outputSettings:o];
		[r addOutput:out];
		if (![r startReading]) { printf("startReading failed: %s\n", r.error.description.UTF8String); return 1; }
		printf("reading %s as %s\n", argv[1], fmt == kCVPixelFormatType_32BGRA ? "BGRA" : "420v"); fflush(stdout);
		int n = 0;
		CMSampleBufferRef sb;
		while ((sb = [out copyNextSampleBuffer]) != NULL) {
			CVImageBufferRef ib = CMSampleBufferGetImageBuffer(sb);
			if (ib && n < 3) {
				CVPixelBufferLockBaseAddress(ib, kCVPixelBufferLock_ReadOnly);
				size_t planes = CVPixelBufferGetPlaneCount(ib);
				printf("frame %d: %zux%zu planes %zu", n, CVPixelBufferGetWidth(ib), CVPixelBufferGetHeight(ib), planes);
				for (size_t p = 0; p < planes; p++) {
					uint8_t *b = CVPixelBufferGetBaseAddressOfPlane(ib, p);
					size_t bpr = CVPixelBufferGetBytesPerRowOfPlane(ib, p), h = CVPixelBufferGetHeightOfPlane(ib, p);
					unsigned sum = 0;
					for (size_t y = 0; y < h; y += 37) sum += b[y * bpr];
					printf(" | p%zu bpr %zu h %zu sum %u", p, bpr, h, sum);
				}
				printf("\n"); fflush(stdout);
				CVPixelBufferUnlockBaseAddress(ib, kCVPixelBufferLock_ReadOnly);
			}
			CFRelease(sb);
			n++;
		}
		printf("done: %d frames, status %ld %s\n", n, (long)r.status, r.error ? r.error.description.UTF8String : "");
	}
	return 0;
}
