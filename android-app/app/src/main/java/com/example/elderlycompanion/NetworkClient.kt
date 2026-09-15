package com.example.elderlycompanion

import android.util.Log
import okhttp3.Call
import okhttp3.Callback
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.MultipartBody
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.RequestBody.Companion.asRequestBody
import okhttp3.RequestBody.Companion.toRequestBody
import okhttp3.Response
import java.io.File
import java.io.IOException
import java.net.URLDecoder
import java.util.concurrent.TimeUnit

/** The one value that must be edited per network: the laptop server's local IP address. */
const val SERVER_URL_BASE = "http://10.180.225.254:8000"

private const val TAG = "NetworkClient"

sealed class CheckinResult {
    data class Success(
        val responseFile: File,
        val userText: String,
        val emotionLabel: String,
        val confidence: Float,
        val responseText: String,
        val voiceLabel: String?,
        val voiceConfidence: Float?,
        val faceLabel: String?,
        val faceConfidence: Float?
    ) : CheckinResult()

    data class Failure(val message: String) : CheckinResult()
}

object NetworkClient {

    private val client = OkHttpClient.Builder()
        .connectTimeout(10, TimeUnit.SECONDS)
        .readTimeout(45, TimeUnit.SECONDS)
        .build()

    /**
     * POSTs the recorded audio file (and, if available, a face photo taken during recording) as
     * multipart/form-data to /checkin and, on success, writes the raw response body (an MP3) to
     * responseFile. onResult is invoked on a background thread. Face is an optional signal --
     * pass imageFile = null to fall back to voice-only, same as if the camera permission was
     * denied or no photo could be captured.
     */
    fun sendAudio(
        audioFile: File,
        imageFile: File?,
        responseFile: File,
        onResult: (CheckinResult) -> Unit
    ) {
        val bodyBuilder = MultipartBody.Builder()
            .setType(MultipartBody.FORM)
            .addFormDataPart(
                "file",
                audioFile.name,
                audioFile.asRequestBody("audio/mp4".toMediaType())
            )
        if (imageFile != null && imageFile.exists()) {
            bodyBuilder.addFormDataPart(
                "image",
                imageFile.name,
                imageFile.asRequestBody("image/jpeg".toMediaType())
            )
        }
        val requestBody = bodyBuilder.build()

        val request = Request.Builder()
            .url("$SERVER_URL_BASE/checkin")
            .post(requestBody)
            .build()

        client.newCall(request).enqueue(object : Callback {
            override fun onFailure(call: Call, e: IOException) {
                Log.e(TAG, "Request failed", e)
                onResult(CheckinResult.Failure("Couldn't reach the server: ${e.message}"))
            }

            override fun onResponse(call: Call, response: Response) {
                response.use {
                    if (!it.isSuccessful) {
                        val body = it.body?.string().orEmpty()
                        Log.e(TAG, "Server returned ${it.code}: $body")
                        onResult(CheckinResult.Failure("Server error (${it.code}): $body"))
                        return
                    }

                    val userText = decodeHeader(it.headers["X-User-Text"]) ?: ""
                    val emotionLabel = decodeHeader(it.headers["X-Emotion-Label"]) ?: "Unknown"
                    val confidence = it.headers["X-Emotion-Confidence"]?.toFloatOrNull() ?: 0f
                    val responseText = decodeHeader(it.headers["X-Response-Text"]) ?: ""
                    val voiceLabel = decodeHeader(it.headers["X-Voice-Label"])
                    val voiceConfidence = it.headers["X-Voice-Confidence"]?.toFloatOrNull()
                    val faceLabel = decodeHeader(it.headers["X-Face-Label"])
                    val faceConfidence = it.headers["X-Face-Confidence"]?.toFloatOrNull()

                    val bodyBytes = it.body
                    if (bodyBytes == null) {
                        onResult(CheckinResult.Failure("Server sent an empty response"))
                        return
                    }

                    bodyBytes.byteStream().use { input ->
                        responseFile.outputStream().use { output -> input.copyTo(output) }
                    }

                    onResult(
                        CheckinResult.Success(
                            responseFile, userText, emotionLabel, confidence, responseText,
                            voiceLabel, voiceConfidence, faceLabel, faceConfidence
                        )
                    )
                }
            }
        })
    }

    /** Clears the server-side conversation history so the next check-in starts fresh. */
    fun resetConversation(onResult: (Boolean) -> Unit) {
        val request = Request.Builder()
            .url("$SERVER_URL_BASE/reset")
            .post(ByteArray(0).toRequestBody(null))
            .build()

        client.newCall(request).enqueue(object : Callback {
            override fun onFailure(call: Call, e: IOException) {
                Log.e(TAG, "Reset failed", e)
                onResult(false)
            }

            override fun onResponse(call: Call, response: Response) {
                response.use { onResult(it.isSuccessful) }
            }
        })
    }

    private fun decodeHeader(value: String?): String? {
        if (value == null) return null
        return try {
            URLDecoder.decode(value, "UTF-8")
        } catch (e: Exception) {
            value
        }
    }
}
