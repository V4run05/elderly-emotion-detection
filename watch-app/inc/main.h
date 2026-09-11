#ifndef __elderly_companion_watch_H__
#define __elderly_companion_watch_H__

#include <app.h>
#include <Elementary.h>
#include <system_settings.h>
#include <efl_extension.h>
#include <dlog.h>

#ifdef LOG_TAG
#undef LOG_TAG
#endif
#define LOG_TAG "elderly_companion_watch"

#if !defined(PACKAGE)
#define PACKAGE "org.example.elderlycompanionwatch"
#endif

typedef enum {
    APP_STATE_IDLE,
    APP_STATE_RECORDING,
    APP_STATE_SENDING,
    APP_STATE_SPEAKING
} app_state_t;

#endif /* __elderly_companion_watch_H__ */
