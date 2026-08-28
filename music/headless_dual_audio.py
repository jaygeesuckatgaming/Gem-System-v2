"""
Headless Dual Audio Player
Plays two audio files simultaneously on different output devices
No Tkinter - safe to run in background threads
"""

import sounddevice as sd
import numpy as np
import threading
import scipy.io.wavfile as wavfile


def get_device_id(device_str):
    """Extract device ID from '[ID] Name' string"""
    try:
        return int(device_str.split(']')[0].strip('['))
    except Exception:
        return None


def find_voicemeeter_devices():
    """Find Voicemeeter Input and AUX devices by name"""
    devices = sd.query_devices()
    input_device = None
    aux_device = None

    for dev in devices:
        if dev['max_output_channels'] <= 0:
            continue
        name = dev['name'].lower()
        if "voicemeeter input" in name and "vaio" in name and input_device is None:
            input_device = dev['index']
        elif "voicemeeter aux" in name and "vaio" in name and aux_device is None:
            aux_device = dev['index']

    return input_device, aux_device


def play_file_on_device(filepath, device_id, device_name):
    """Play audio file on a specific device"""
    try:
        sample_rate, audio_data = wavfile.read(filepath)

        # Convert to float for sounddevice
        if audio_data.dtype == np.int16:
            audio_data = audio_data / 32768.0
        elif audio_data.dtype == np.int32:
            audio_data = audio_data / 2147483648.0

        print(f"Playing {filepath} on device {device_id} ({device_name})")
        sd.play(audio_data, sample_rate, device=device_id)
        sd.wait()
        print(f"Finished playing {filepath}")
    except Exception as e:
        print(f"Error playing {filepath} on device {device_id}: {e}")


def play_dual(file1, file2, device1_id=None, device2_id=None):
    """Play two files simultaneously on two devices (headless)"""
    # Auto-detect Voicemeeter devices if not specified
    if device1_id is None or device2_id is None:
        vm_input, vm_aux = find_voicemeeter_devices()
        if device1_id is None:
            device1_id = vm_input
        if device2_id is None:
            device2_id = vm_aux

    if device1_id is None or device2_id is None:
        print("❌ Could not find Voicemeeter devices")
        return False

    print(f"🎵 Playing File 1 (vocals) on device {device1_id}")
    print(f"🎵 Playing File 2 (instrumental) on device {device2_id}")

    thread1 = threading.Thread(target=play_file_on_device, args=(file1, device1_id, "Vocals"), daemon=True)
    thread2 = threading.Thread(target=play_file_on_device, args=(file2, device2_id, "Instrumental"), daemon=True)

    thread1.start()
    thread2.start()

    thread1.join()
    thread2.join()
    return True


if __name__ == "__main__":
    import sys
    if len(sys.argv) >= 3:
        play_dual(sys.argv[1], sys.argv[2])
    else:
        print("Usage: python headless_dual_audio.py <file1> <file2>")
