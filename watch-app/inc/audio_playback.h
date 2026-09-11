#ifndef __AUDIO_PLAYBACK_H__
#define __AUDIO_PLAYBACK_H__

typedef void (*audio_playback_done_cb)(void *user_data);

/* Plays the MP3 at mp3_path through the watch's default (built-in) speaker output. */
int audio_playback_start(const char *mp3_path, audio_playback_done_cb callback, void *user_data);

#endif /* __AUDIO_PLAYBACK_H__ */
