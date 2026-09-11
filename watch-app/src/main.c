#include "main.h"
#include "audio_capture.h"
#include "audio_playback.h"
#include "network_client.h"

typedef struct appdata {
    Evas_Object *win;
    Evas_Object *conform;
    Evas_Object *label;
    Evas_Object *button;
    app_state_t state;
} appdata_s;

static void set_state(appdata_s *ad, app_state_t state)
{
    ad->state = state;
    const char *text = "Idle";
    switch (state) {
    case APP_STATE_RECORDING: text = "Recording..."; break;
    case APP_STATE_SENDING: text = "Sending..."; break;
    case APP_STATE_SPEAKING: text = "Speaking..."; break;
    default: text = "Tap to check in"; break;
    }
    elm_object_text_set(ad->label, text);
}

static void on_playback_done(void *user_data)
{
    appdata_s *ad = (appdata_s *)user_data;
    set_state(ad, APP_STATE_IDLE);
}

static void on_network_response(bool success, const char *response_path, void *user_data)
{
    appdata_s *ad = (appdata_s *)user_data;
    if (!success) {
        dlog_print(DLOG_ERROR, LOG_TAG, "check-in failed: no response from server");
        set_state(ad, APP_STATE_IDLE);
        return;
    }

    set_state(ad, APP_STATE_SPEAKING);
    audio_playback_start(response_path, on_playback_done, ad);
}

static void on_recording_done(const char *recorded_path, void *user_data)
{
    appdata_s *ad = (appdata_s *)user_data;
    set_state(ad, APP_STATE_SENDING);
    network_client_send_audio(recorded_path, on_network_response, ad);
}

static Eina_Bool audio_capture_stop_timer_cb(void *data)
{
    appdata_s *ad = (appdata_s *)data;
    audio_capture_stop(on_recording_done, ad);
    return ECORE_CALLBACK_CANCEL;
}

static void checkin_button_clicked_cb(void *data, Evas_Object *obj, void *event_info)
{
    appdata_s *ad = (appdata_s *)data;

    if (ad->state != APP_STATE_IDLE) {
        return;
    }

    if (audio_capture_start() != 0) {
        dlog_print(DLOG_ERROR, LOG_TAG, "failed to start recording");
        return;
    }
    set_state(ad, APP_STATE_RECORDING);

    /* Fixed ~5s clip length, per the plan's "record ~4-6 seconds" spec. */
    ecore_timer_add(5.0, audio_capture_stop_timer_cb, ad);
}

static void create_base_gui(appdata_s *ad)
{
    ad->win = elm_win_util_standard_add(PACKAGE, PACKAGE);
    elm_win_autodel_set(ad->win, EINA_TRUE);

    if (elm_win_wm_rotation_supported_get(ad->win)) {
        int rots[4] = {0, 90, 180, 270};
        elm_win_wm_rotation_available_rotations_set(ad->win, (const int *)(&rots), 4);
    }

    evas_object_smart_callback_add(ad->win, "delete,request", NULL, NULL);
    eext_object_event_callback_add(ad->win, EEXT_CALLBACK_BACK, eext_win_back_event_cb, NULL);

    ad->conform = elm_conformant_add(ad->win);
    evas_object_size_hint_weight_set(ad->conform, EVAS_HINT_EXPAND, EVAS_HINT_EXPAND);
    elm_win_resize_object_add(ad->win, ad->conform);
    evas_object_show(ad->conform);

    Evas_Object *box = elm_box_add(ad->conform);
    evas_object_size_hint_weight_set(box, EVAS_HINT_EXPAND, EVAS_HINT_EXPAND);
    elm_object_content_set(ad->conform, box);
    evas_object_show(box);

    ad->label = elm_label_add(box);
    elm_object_text_set(ad->label, "Tap to check in");
    evas_object_size_hint_weight_set(ad->label, EVAS_HINT_EXPAND, 0.0);
    evas_object_size_hint_align_set(ad->label, EVAS_HINT_FILL, 0.5);
    elm_box_pack_end(box, ad->label);
    evas_object_show(ad->label);

    ad->button = elm_button_add(box);
    elm_object_text_set(ad->button, "Check in");
    evas_object_size_hint_weight_set(ad->button, EVAS_HINT_EXPAND, EVAS_HINT_EXPAND);
    evas_object_smart_callback_add(ad->button, "clicked", checkin_button_clicked_cb, ad);
    elm_box_pack_end(box, ad->button);
    evas_object_show(ad->button);

    ad->state = APP_STATE_IDLE;

    evas_object_show(ad->win);
}

static bool app_create(void *data)
{
    appdata_s *ad = (appdata_s *)data;
    create_base_gui(ad);
    return true;
}

static void app_control(app_control_h app_control, void *data) { }
static void app_pause(void *data) { }
static void app_resume(void *data) { }
static void app_terminate(void *data) { }

static void ui_app_lang_changed(app_event_info_h event_info, void *user_data) { }

int main(int argc, char *argv[])
{
    appdata_s ad = {0,};
    int ret = 0;

    ui_app_lifecycle_callback_s event_callback = {0,};
    app_event_handler_h handlers[5] = {NULL,};

    event_callback.create = app_create;
    event_callback.terminate = app_terminate;
    event_callback.pause = app_pause;
    event_callback.resume = app_resume;
    event_callback.app_control = app_control;

    ui_app_add_event_handler(&handlers[APP_EVENT_LANGUAGE_CHANGED], APP_EVENT_LANGUAGE_CHANGED,
                              ui_app_lang_changed, &ad);

    ret = ui_app_main(argc, argv, &event_callback, &ad);
    if (ret != APP_ERROR_NONE) {
        dlog_print(DLOG_ERROR, LOG_TAG, "ui_app_main() failed: %d", ret);
    }

    return ret;
}
