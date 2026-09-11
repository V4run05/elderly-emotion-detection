#include "audio_capture.h"
#include "main.h"

#include <recorder.h>
#include <app_common.h>
#include <stdlib.h>
#include <string.h>

static recorder_h g_recorder = NULL;
static char g_recorded_path[PATH_MAX];
static audio_capture_done_cb g_done_cb = NULL;
static void *g_done_cb_user_data = NULL;

static void recorder_state_changed_cb(recorder_state_e previous, recorder_state_e current,
                                       bool by_policy, void *user_data)
{
    if (current == RECORDER_STATE_READY && previous == RECORDER_STATE_RECORDING) {
        /* Commit finished; the file at g_recorded_path is now finalized. */
        if (g_done_cb) {
            g_done_cb(g_recorded_path, g_done_cb_user_data);
            g_done_cb = NULL;
        }
        recorder_unprepare(g_recorder);
        recorder_destroy(g_recorder);
        g_recorder = NULL;
    }
}

int audio_capture_start(void)
{
    char *data_path = app_get_data_path();
    if (!data_path) {
        dlog_print(DLOG_ERROR, LOG_TAG, "audio_capture_start: app_get_data_path failed");
        return -1;
    }
    snprintf(g_recorded_path, sizeof(g_recorded_path), "%scheckin.m4a", data_path);
    free(data_path);

    int ret = recorder_create_audiorecorder(&g_recorder);
    if (ret != RECORDER_ERROR_NONE) {
        dlog_print(DLOG_ERROR, LOG_TAG, "recorder_create_audiorecorder failed: %d", ret);
        return -1;
    }

    recorder_attr_set_audio_device(g_recorder, RECORDER_AUDIO_DEVICE_MIC);
    recorder_set_filename(g_recorder, g_recorded_path);
    recorder_set_file_format(g_recorder, RECORDER_FILE_FORMAT_M4A);
    recorder_set_state_changed_cb(g_recorder, recorder_state_changed_cb, NULL);

    ret = recorder_prepare(g_recorder);
    if (ret != RECORDER_ERROR_NONE) {
        dlog_print(DLOG_ERROR, LOG_TAG, "recorder_prepare failed: %d", ret);
        recorder_destroy(g_recorder);
        g_recorder = NULL;
        return -1;
    }

    ret = recorder_start(g_recorder);
    if (ret != RECORDER_ERROR_NONE) {
        dlog_print(DLOG_ERROR, LOG_TAG, "recorder_start failed: %d", ret);
        recorder_unprepare(g_recorder);
        recorder_destroy(g_recorder);
        g_recorder = NULL;
        return -1;
    }

    return 0;
}

int audio_capture_stop(audio_capture_done_cb callback, void *user_data)
{
    if (!g_recorder) {
        dlog_print(DLOG_ERROR, LOG_TAG, "audio_capture_stop: no active recorder");
        return -1;
    }

    g_done_cb = callback;
    g_done_cb_user_data = user_data;

    int ret = recorder_commit(g_recorder);
    if (ret != RECORDER_ERROR_NONE) {
        dlog_print(DLOG_ERROR, LOG_TAG, "recorder_commit failed: %d", ret);
        return -1;
    }

    return 0;
}
