package com.example.elderlycompanion

import android.Manifest
import android.content.pm.PackageManager
import android.media.MediaPlayer
import android.media.MediaRecorder
import android.os.Build
import android.os.Bundle
import android.os.Handler
import android.os.Looper
import android.widget.Button
import android.widget.TextView
import androidx.appcompat.app.AppCompatActivity
import androidx.core.app.ActivityCompat
import androidx.core.content.ContextCompat
import java.io.File

private enum class AppState { IDLE, RECORDING, SENDING, SPEAKING }

class MainActivity : AppCompatActivity() {

    private lateinit var statusLabel: TextView
    private lateinit var checkinButton: Button

    private var recorder: MediaRecorder? = null
    private var player: MediaPlayer? = null
    private var state = AppState.IDLE

    private val mainHandler = Handler(Looper.getMainLooper())
    private val recordingFile: File by lazy { File(cacheDir, "checkin.m4a") }
    private val responseFile: File by lazy { File(cacheDir, "response.mp3") }

    companion object {
        private const val RECORD_AUDIO_PERMISSION_REQUEST = 1001
        private const val RECORDING_DURATION_MS = 5000L
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContentView(R.layout.activity_main)

        statusLabel = findViewById(R.id.statusLabel)
        checkinButton = findViewById(R.id.checkinButton)

        checkinButton.setOnClickListener { onCheckinTapped() }
    }

    private fun onCheckinTapped() {
        if (state != AppState.IDLE) return

        if (ContextCompat.checkSelfPermission(this, Manifest.permission.RECORD_AUDIO)
            != PackageManager.PERMISSION_GRANTED
        ) {
            ActivityCompat.requestPermissions(
                this,
                arrayOf(Manifest.permission.RECORD_AUDIO),
                RECORD_AUDIO_PERMISSION_REQUEST
            )
            return
        }

        startRecording()
    }

    override fun onRequestPermissionsResult(
        requestCode: Int,
        permissions: Array<out String>,
        grantResults: IntArray
    ) {
        super.onRequestPermissionsResult(requestCode, permissions, grantResults)
        if (requestCode == RECORD_AUDIO_PERMISSION_REQUEST &&
            grantResults.isNotEmpty() && grantResults[0] == PackageManager.PERMISSION_GRANTED
        ) {
            startRecording()
        }
    }

    private fun setState(newState: AppState) {
        state = newState
        statusLabel.text = when (newState) {
            AppState.IDLE -> "Tap to check in"
            AppState.RECORDING -> "Recording..."
            AppState.SENDING -> "Sending..."
            AppState.SPEAKING -> "Speaking..."
        }
    }

    private fun startRecording() {
        @Suppress("DEPRECATION")
        val newRecorder = if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.S) {
            MediaRecorder(this)
        } else {
            MediaRecorder()
        }

        newRecorder.apply {
            setAudioSource(MediaRecorder.AudioSource.MIC)
            setOutputFormat(MediaRecorder.OutputFormat.MPEG_4)
            setAudioEncoder(MediaRecorder.AudioEncoder.AAC)
            setOutputFile(recordingFile.absolutePath)
            prepare()
            start()
        }
        recorder = newRecorder
        setState(AppState.RECORDING)

        mainHandler.postDelayed({ stopRecordingAndSend() }, RECORDING_DURATION_MS)
    }

    private fun stopRecordingAndSend() {
        recorder?.apply {
            stop()
            release()
        }
        recorder = null

        setState(AppState.SENDING)
        NetworkClient.sendAudio(recordingFile, responseFile) { success ->
            mainHandler.post {
                if (success) {
                    playResponse()
                } else {
                    setState(AppState.IDLE)
                }
            }
        }
    }

    private fun playResponse() {
        setState(AppState.SPEAKING)
        player?.release()
        player = MediaPlayer().apply {
            setDataSource(responseFile.absolutePath)
            setOnCompletionListener {
                it.release()
                player = null
                setState(AppState.IDLE)
            }
            prepare()
            start()
        }
    }

    override fun onDestroy() {
        super.onDestroy()
        recorder?.release()
        player?.release()
    }
}
