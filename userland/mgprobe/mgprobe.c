/* mgprobe: print MobileGestalt answers for the keys given (or a default hardware list). Own code; loads
 * libMobileGestalt at run time. Usage: mgprobe [KEY...] */
#include <CoreFoundation/CoreFoundation.h>
#include <dlfcn.h>
#include <stdio.h>

typedef CFTypeRef (*mg_copy_t)(CFStringRef, CFDictionaryRef);

static void show(mg_copy_t copy, const char *k)
{
	CFStringRef key = CFStringCreateWithCString(NULL, k, kCFStringEncodingUTF8);
	CFTypeRef v = copy(key, NULL);
	char buf[256] = "(null)";
	if (v != NULL) {
		CFStringRef d = CFCopyDescription(v);
		CFStringGetCString(d, buf, sizeof(buf), kCFStringEncodingUTF8);
		CFRelease(d);
		CFRelease(v);
	}
	printf("%s = %s\n", k, buf);
	CFRelease(key);
}

int main(int argc, char **argv)
{
	void *h = dlopen("/usr/lib/libMobileGestalt.dylib", RTLD_NOW);
	mg_copy_t copy = h ? (mg_copy_t)dlsym(h, "MGCopyAnswer") : NULL;
	if (copy == NULL) {
		printf("no MGCopyAnswer\n");
		return 1;
	}
	static const char *def[] = { "DeviceSupportsClosedLoopHaptics", "DeviceSupportsHaptics", "HapticCapability",
		"DeviceSupports3rdPartyHaptics", "camera-flash", "HasBaseband", "BasebandFirmwareVersion", "telephony",
		"cellular-data", "CellularTelephonyCapability", "DeviceSupportsSimplisticRoadMesh", "ProductType",
		"HWModelStr", "DeviceClass", "main-screen-width", "main-screen-height", "ambient-light-sensor",
		"proximity-sensor", "gyroscope", "accelerometer", "magnetometer", "DeviceSupportsBarometer", NULL };
	if (argc > 1) {
		for (int i = 1; i < argc; i++) show(copy, argv[i]);
	} else {
		for (int i = 0; def[i]; i++) show(copy, def[i]);
	}
	return 0;
}
