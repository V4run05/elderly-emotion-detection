package com.example.elderlycompanion

import okhttp3.Call
import okhttp3.Callback
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.MultipartBody
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.RequestBody.Companion.asRequestBody
import okhttp3.Response
import java.io.File
import java.io.IOException
import java.util.concurrent.TimeUnit

/** The one value that must be edited per network: the laptop server's local IP address. */
const val SERVER_URL = "http://192.168.1.100:8000/checkin"

object NetworkClient {

    private val client = OkHttpClient.Builder()
        .connectTimeout(10, TimeUnit.SECONDS)
        .readTimeout(30, TimeUnit.SECONDS)
        .build()

    /**
     * POSTs the recorded audio file as multipart/form-data to SERVER_URL and writes the raw
     * response body to responseFile on success. Callback is invoked on a background thread.
     */
    fun sendAudio(audioFile: File, responseFile: File, onResult: (success: Boolean) -> Unit) {
        val requestBody = MultipartBody.Builder()
            .setType(MultipartBody.FORM)
            .addFormDataPart(
                "file",
                audioFile.name,
                audioFile.asRequestBody("audio/mp4".toMediaType())
            )
            .build()

        val request = Request.Builder()
            .url(SERVER_URL)
            .post(requestBody)
            .build()

        client.newCall(request).enqueue(object : Callback {
            override fun onFailure(call: Call, e: IOException) {
                onResult(false)
            }

            override fun onResponse(call: Call, response: Response) {
                response.use {
                    if (!it.isSuccessful) {
                        onResult(false)
                        return
                    }
                    it.body?.byteStream()?.use { input ->
                        responseFile.outputStream().use { output -> input.copyTo(output) }
                    }
                    onResult(true)
                }
            }
        })
    }
}
