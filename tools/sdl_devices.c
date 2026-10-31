#include <SDL3/SDL.h>
#include <stdio.h>
int main(void) {
    if (!SDL_Init(SDL_INIT_AUDIO)) { printf("init failed: %s\n", SDL_GetError()); return 1; }
    int n = 0;
    SDL_AudioDeviceID *devs = SDL_GetAudioPlaybackDevices(&n);
    printf("PLAYBACK\n");
    for (int i = 0; i < n; i++) printf("%u|%s\n", devs[i], SDL_GetAudioDeviceName(devs[i]));
    SDL_free(devs);
    devs = SDL_GetAudioRecordingDevices(&n);
    printf("RECORDING\n");
    for (int i = 0; i < n; i++) printf("%u|%s\n", devs[i], SDL_GetAudioDeviceName(devs[i]));
    SDL_free(devs);
    SDL_Quit();
    return 0;
}
