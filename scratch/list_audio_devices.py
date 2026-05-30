# -*- coding: utf-8 -*-
import pyaudio

def main():
    p = pyaudio.PyAudio()
    print("=== Available Audio Input Devices ===")
    info = p.get_host_api_info_by_index(0)
    numdevices = info.get('deviceCount')
    
    default_input_idx = p.get_default_input_device_info().get('index')
    print(f"Default Input Device Index: {default_input_idx}\n")
    
    for i in range(0, numdevices):
        try:
            device_info = p.get_device_info_by_host_api_device_index(0, i)
            if device_info.get('maxInputChannels') > 0:
                is_default = " (DEFAULT)" if device_info.get('index') == default_input_idx else ""
                print(f"Index {device_info.get('index')}: {device_info.get('name')}{is_default}")
                print(f"  Max Input Channels: {device_info.get('maxInputChannels')}")
                print(f"  Default Sample Rate: {device_info.get('defaultSampleRate')} Hz")
        except Exception as e:
            pass
            
    p.terminate()

if __name__ == "__main__":
    main()
