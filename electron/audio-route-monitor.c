#include <CoreAudio/CoreAudio.h>
#include <stdio.h>
#include <unistd.h>

/* No microphone access: observe only the default output route and jack source. */
static UInt32 read_value(AudioObjectID object, AudioObjectPropertySelector selector,
                         AudioObjectPropertyScope scope) {
    AudioObjectPropertyAddress address = {selector, scope, kAudioObjectPropertyElementMain};
    UInt32 value = 0, size = sizeof(value);
    AudioObjectGetPropertyData(object, &address, 0, NULL, &size, &value);
    return value;
}
int main(void) {
    setbuf(stdout, NULL);
    AudioObjectID previous = 0;
    UInt32 source = 0, jack = 0;
    int initialized = 0;
    while (getppid() != 1) {
        AudioObjectID device = read_value(kAudioObjectSystemObject,
            kAudioHardwarePropertyDefaultOutputDevice, kAudioObjectPropertyScopeGlobal);
        UInt32 next_source = read_value(device, kAudioDevicePropertyDataSource, kAudioDevicePropertyScopeOutput);
        UInt32 next_jack = read_value(device, kAudioDevicePropertyJackIsConnected, kAudioDevicePropertyScopeOutput);
        if (!initialized) puts("ready");
        else if (device != previous || next_source != source || next_jack != jack) puts("changed");
        previous = device; source = next_source; jack = next_jack; initialized = 1;
        usleep(100000);
    }
    return 0;
}
