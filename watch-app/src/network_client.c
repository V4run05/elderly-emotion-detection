#include "network_client.h"
#include "main.h"

#include <curl/curl.h>
#include <app_common.h>
#include <Ecore.h>
#include <stdlib.h>
#include <string.h>
#include <stdio.h>

typedef struct {
    char audio_path[PATH_MAX];
    char response_path[PATH_MAX];
    bool success;
    network_response_cb callback;
    void *user_data;
} network_task_t;

static size_t write_response_cb(void *ptr, size_t size, size_t nmemb, void *stream)
{
    return fwrite(ptr, size, nmemb, (FILE *)stream);
}

static void network_task_run(void *data, Ecore_Thread *thread)
{
    network_task_t *task = (network_task_t *)data;

    FILE *out = fopen(task->response_path, "wb");
    if (!out) {
        dlog_print(DLOG_ERROR, LOG_TAG, "network_client: failed to open %s for writing",
                   task->response_path);
        task->success = false;
        return;
    }

    CURL *curl = curl_easy_init();
    if (!curl) {
        fclose(out);
        task->success = false;
        return;
    }

    curl_mime *mime = curl_mime_init(curl);
    curl_mimepart *part = curl_mime_addpart(mime);
    curl_mime_name(part, "file");
    curl_mime_filedata(part, task->audio_path);

    curl_easy_setopt(curl, CURLOPT_URL, SERVER_URL);
    curl_easy_setopt(curl, CURLOPT_MIMEPOST, mime);
    curl_easy_setopt(curl, CURLOPT_WRITEFUNCTION, write_response_cb);
    curl_easy_setopt(curl, CURLOPT_WRITEDATA, out);
    curl_easy_setopt(curl, CURLOPT_TIMEOUT, 30L);

    CURLcode res = curl_easy_perform(curl);
    task->success = (res == CURLE_OK);
    if (res != CURLE_OK) {
        dlog_print(DLOG_ERROR, LOG_TAG, "network_client: curl_easy_perform failed: %s",
                   curl_easy_strerror(res));
    }

    curl_mime_free(mime);
    curl_easy_cleanup(curl);
    fclose(out);
}

static void network_task_end(void *data, Ecore_Thread *thread)
{
    network_task_t *task = (network_task_t *)data;
    if (task->callback) {
        task->callback(task->success, task->success ? task->response_path : NULL, task->user_data);
    }
    free(task);
}

static void network_task_cancel(void *data, Ecore_Thread *thread)
{
    free(data);
}

void network_client_send_audio(const char *audio_path, network_response_cb callback, void *user_data)
{
    network_task_t *task = calloc(1, sizeof(network_task_t));
    if (!task) {
        return;
    }

    snprintf(task->audio_path, sizeof(task->audio_path), "%s", audio_path);

    char *data_path = app_get_data_path();
    snprintf(task->response_path, sizeof(task->response_path), "%sresponse.mp3",
             data_path ? data_path : "");
    free(data_path);

    task->callback = callback;
    task->user_data = user_data;

    ecore_thread_run(network_task_run, network_task_end, network_task_cancel, task);
}
