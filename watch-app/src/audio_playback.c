#include "audio_playback.h"
#include "main.h"

#include <player.h>
#include <stdlib.h>

static player_h g_player = NULL;
static audio_playback_done_cb g_done_cb = NULL;
static void *g_done_cb_user_data = NULL;

static void player_completed_cb(void *user_data)
{
    if (g_done_cb) {
        g_done_cb(g_done_cb_user_data);
        g_done_cb = NULL;
    }

    if (g_player) {
        player_stop(g_player);
        player_unprepare(g_player);
        player_destroy(g_player);
        g_player = NULL;
    }
}

int audio_playback_start(const char *mp3_path, audio_playback_done_cb callback, void *user_data)
{
    if (g_player) {
        player_stop(g_player);
        player_unprepare(g_player);
        player_destroy(g_player);
        g_player = NULL;
    }

    g_done_cb = callback;
    g_done_cb_user_data = user_data;

    int ret = player_create(&g_player);
    if (ret != PLAYER_ERROR_NONE) {
        dlog_print(DLOG_ERROR, LOG_TAG, "player_create failed: %d", ret);
        return -1;
    }

    ret = player_set_uri(g_player, mp3_path);
    if (ret != PLAYER_ERROR_NONE) {
        dlog_print(DLOG_ERROR, LOG_TAG, "player_set_uri failed: %d", ret);
        player_destroy(g_player);
        g_player = NULL;
        return -1;
    }

    player_set_completed_cb(g_player, player_completed_cb, NULL);

    ret = player_prepare(g_player);
    if (ret != PLAYER_ERROR_NONE) {
        dlog_print(DLOG_ERROR, LOG_TAG, "player_prepare failed: %d", ret);
        player_destroy(g_player);
        g_player = NULL;
        return -1;
    }

    ret = player_start(g_player);
    if (ret != PLAYER_ERROR_NONE) {
        dlog_print(DLOG_ERROR, LOG_TAG, "player_start failed: %d", ret);
        player_unprepare(g_player);
        player_destroy(g_player);
        g_player = NULL;
        return -1;
    }

    return 0;
}
