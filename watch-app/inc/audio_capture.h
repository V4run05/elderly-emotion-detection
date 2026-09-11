#ifndef __AUDIO_CAPTURE_H__
#define __AUDIO_CAPTURE_H__

typedef void (*audio_capture_done_cb)(const char *recorded_path, void *user_data);

/* Starts recording from the mic via the Recorder API. */
int audio_capture_start(void);

/*
 * Stops and commits the current recording, saving it as app-private .m4a.
 * Invokes callback with the saved file path once the recorder finishes committing.
 */
int audio_capture_stop(audio_capture_done_cb callback, void *user_data);

#endif /* __AUDIO_CAPTURE_H__ */
