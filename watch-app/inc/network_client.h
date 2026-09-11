#ifndef __NETWORK_CLIENT_H__
#define __NETWORK_CLIENT_H__

#include <stdbool.h>

/* The one value that must be edited per network: the laptop server's local IP address. */
#define SERVER_URL "http://192.168.1.100:8000/checkin"

typedef void (*network_response_cb)(bool success, const char *response_path, void *user_data);

/*
 * POSTs the audio file at audio_path as multipart/form-data to SERVER_URL.
 * On success, writes the raw response body to <app-data-path>/response.mp3 and invokes
 * callback with success=true and response_path pointing at that file.
 * Runs the request on a worker thread; callback is invoked on the main loop.
 */
void network_client_send_audio(const char *audio_path, network_response_cb callback, void *user_data);

#endif /* __NETWORK_CLIENT_H__ */
