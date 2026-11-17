/* happrobe: ask iOS's system sound server for vibrations (kSystemSoundID_Vibrate 4095, peek 1519, pop 1520, nope 1521).
 * Own code. Usage: happrobe [ID...] */
#include <AudioToolbox/AudioToolbox.h>
#include <CoreFoundation/CoreFoundation.h>
#include <stdio.h>
#include <stdlib.h>
#include <unistd.h>

int main(int argc, char **argv)
{
	UInt32 def[] = { 4095, 1519, 1520, 1521 };
	int n = argc > 1 ? argc - 1 : 4;
	for (int i = 0; i < n; i++) {
		UInt32 id = argc > 1 ? (UInt32)atoi(argv[i + 1]) : def[i];
		printf("playing system sound %u\n", id); fflush(stdout);
		AudioServicesPlaySystemSoundWithCompletion(id, NULL);
		CFRunLoopRunInMode(kCFRunLoopDefaultMode, 1.5, false);
	}
	return 0;
}
