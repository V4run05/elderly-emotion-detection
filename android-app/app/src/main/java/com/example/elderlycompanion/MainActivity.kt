package com.example.elderlycompanion

import android.Manifest
import android.content.pm.PackageManager
import android.media.MediaPlayer
import android.media.MediaRecorder
import android.os.Build
import android.os.Bundle
import android.os.Handler
import android.os.Looper
import android.util.Log
import android.view.View
import android.widget.ImageButton
import android.widget.ProgressBar
import android.widget.TextView
import android.widget.Toast
import androidx.appcompat.app.AppCompatActivity
import androidx.camera.core.CameraSelector
import androidx.camera.core.ImageCapture
import androidx.camera.core.ImageCaptureException
import androidx.camera.core.Preview
import androidx.camera.lifecycle.ProcessCameraProvider
import androidx.camera.view.PreviewView
import androidx.core.app.ActivityCompat
import androidx.core.content.ContextCompat
import androidx.recyclerview.widget.LinearLayoutManager
import androidx.recyclerview.widget.RecyclerView
import com.google.android.material.appbar.MaterialToolbar
import com.google.android.material.floatingactionbutton.FloatingActionButton
import java.io.File
import java.util.Locale

private enum class AppState { IDLE, RECORDING, SENDING, SPEAKING }

class MainActivity : AppCompatActivity() {

    private lateinit var statusLabel: TextView
    private lateinit var errorLabel: TextView
    private lateinit var emptyStateLabel: TextView
    private lateinit var checkinButton: FloatingActionButton
    private lateinit var resetButton: ImageButton
    private lateinit var progressIndicator: ProgressBar
    private lateinit var chatRecyclerView: RecyclerView
    private lateinit var cameraPreview: PreviewView

    private val messages = mutableListOf<ChatMessage>()
    private lateinit var chatAdapter: ChatAdapter

    private var recorder: MediaRecorder? = null
    private var player: MediaPlayer? = null
    private var state = AppState.IDLE

    private var cameraProvider: ProcessCameraProvider? = null
    private var imageCapture: ImageCapture? = null
    private var lastCapturedFace: File? = null

    private val mainHandler = Handler(Looper.getMainLooper())
    private val recordingFile: File by lazy { File(cacheDir, "checkin.m4a") }
    private val faceFile: File by lazy { File(cacheDir, "face.jpg") }
    private val responseFile: File by lazy { File(cacheDir, "response.mp3") }

    companion object {
        private const val TAG = "MainActivity"
        private const val PERMISSION_REQUEST = 1001
        private const val RECORDING_DURATION_MS = 5000L
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContentView(R.layout.activity_main)

        val toolbar: MaterialToolbar = findViewById(R.id.toolbar)
        setSupportActionBar(toolbar)
        supportActionBar?.setDisplayShowTitleEnabled(true)

        statusLabel = findViewById(R.id.statusLabel)
        errorLabel = findViewById(R.id.errorLabel)
        emptyStateLabel = findViewById(R.id.emptyStateLabel)
        checkinButton = findViewById(R.id.checkinButton)
        resetButton = findViewById(R.id.resetButton)
        progressIndicator = findViewById(R.id.progressIndicator)
        chatRecyclerView = findViewById(R.id.chatRecyclerView)
        cameraPreview = findViewById(R.id.cameraPreview)

        chatAdapter = ChatAdapter(messages)
        chatRecyclerView.layoutManager = LinearLayoutManager(this)
        chatRecyclerView.adapter = chatAdapter

        checkinButton.setOnClickListener { onCheckinTapped() }
        resetButton.setOnClickListener { onResetTapped() }
    }

    private fun onCheckinTapped() {
        if (state != AppState.IDLE) return

        hideError()

        val missingPermissions = listOfNotNull(
            Manifest.permission.RECORD_AUDIO.takeIf { !hasPermission(it) },
            Manifest.permission.CAMERA.takeIf { !hasPermission(it) }
        )
        if (missingPermissions.isNotEmpty()) {
            ActivityCompat.requestPermissions(
                this, missingPermissions.toTypedArray(), PERMISSION_REQUEST
            )
            return
        }

        startCheckin()
    }

    private fun hasPermission(permission: String): Boolean {
        return ContextCompat.checkSelfPermission(this, permission) ==
            PackageManager.PERMISSION_GRANTED
    }

    private fun onResetTapped() {
        if (state != AppState.IDLE) return
        resetButton.isEnabled = false
        NetworkClient.resetConversation { success ->
            mainHandler.post {
                resetButton.isEnabled = true
                if (success) {
                    chatAdapter.clear()
                    emptyStateLabel.visibility = View.VISIBLE
                    Toast.makeText(this, "Started a new conversation", Toast.LENGTH_SHORT).show()
                } else {
                    showError("Couldn't start a new conversation")
                }
            }
        }
    }

    override fun onRequestPermissionsResult(
        requestCode: Int,
        permissions: Array<out String>,
        grantResults: IntArray
    ) {
        super.onRequestPermissionsResult(requestCode, permissions, grantResults)
        if (requestCode != PERMISSION_REQUEST) return

        val micGranted = hasPermission(Manifest.permission.RECORD_AUDIO)
        if (micGranted) {
            startCheckin()
        } else {
            Toast.makeText(
                this,
                "Microphone permission is needed to check in",
                Toast.LENGTH_LONG
            ).show()
        }
    }

    /** Starts the camera preview (if permitted) and the audio recording together. */
    private fun startCheckin() {
        lastCapturedFace = null
        if (hasPermission(Manifest.permission.CAMERA)) {
            startCamera()
        }
        startRecording()
    }

    private fun startCamera() {
        cameraPreview.visibility = View.VISIBLE
        val providerFuture = ProcessCameraProvider.getInstance(this)
        providerFuture.addListener({
            try {
                val provider = providerFuture.get()
                cameraProvider = provider

                val preview = Preview.Builder().build().also {
                    it.setSurfaceProvider(cameraPreview.surfaceProvider)
                }
                val capture = ImageCapture.Builder().build()
                imageCapture = capture

                provider.unbindAll()
                provider.bindToLifecycle(
                    this, CameraSelector.DEFAULT_FRONT_CAMERA, preview, capture
                )
            } catch (e: Exception) {
                Log.e(TAG, "Failed to start camera, continuing voice-only", e)
                imageCapture = null
                cameraPreview.visibility = View.GONE
            }
        }, ContextCompat.getMainExecutor(this))
    }

    private fun stopCamera() {
        cameraProvider?.unbindAll()
        cameraProvider = null
        imageCapture = null
        cameraPreview.visibility = View.GONE
    }

    private fun setState(newState: AppState) {
        state = newState
        val (statusText, tintColor, icon, showProgress) = when (newState) {
            AppState.IDLE -> Quad("Tap to check in", R.color.state_idle, R.drawable.ic_mic, false)
            AppState.RECORDING -> Quad("Listening...", R.color.state_recording, R.drawable.ic_stop, false)
            AppState.SENDING -> Quad("Thinking...", R.color.state_sending, R.drawable.ic_cloud_upload, true)
            AppState.SPEAKING -> Quad("Speaking...", R.color.state_speaking, R.drawable.ic_volume_up, false)
        }
        statusLabel.text = statusText
        checkinButton.backgroundTintList = ContextCompat.getColorStateList(this, tintColor)
        checkinButton.setImageResource(icon)
        checkinButton.isEnabled = newState == AppState.IDLE
        resetButton.isEnabled = newState == AppState.IDLE
        progressIndicator.visibility = if (showProgress) View.VISIBLE else View.INVISIBLE
    }

    private data class Quad(
        val statusText: String,
        val colorRes: Int,
        val iconRes: Int,
        val showProgress: Boolean
    )

    private fun showError(message: String) {
        errorLabel.text = message
        errorLabel.visibility = View.VISIBLE
    }

    private fun hideError() {
        errorLabel.visibility = View.GONE
    }

    private fun startRecording() {
        try {
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

            mainHandler.postDelayed({ captureFaceThenStop() }, RECORDING_DURATION_MS)
        } catch (e: Exception) {
            Log.e(TAG, "Failed to start recording", e)
            showError("Couldn't start recording: ${e.message}")
            stopCamera()
            setState(AppState.IDLE)
        }
    }

    /** Captures a photo (if the camera is active) right as the recording window ends, so the
     * face reflects how the person looked while actually speaking, then stops the recorder and
     * sends everything. */
    private fun captureFaceThenStop() {
        val capture = imageCapture
        if (capture == null) {
            stopRecordingAndSend()
            return
        }

        val outputOptions = ImageCapture.OutputFileOptions.Builder(faceFile).build()
        capture.takePicture(
            outputOptions,
            ContextCompat.getMainExecutor(this),
            object : ImageCapture.OnImageSavedCallback {
                override fun onImageSaved(output: ImageCapture.OutputFileResults) {
                    lastCapturedFace = faceFile
                    stopRecordingAndSend()
                }

                override fun onError(exception: ImageCaptureException) {
                    Log.e(TAG, "Failed to capture face photo, continuing voice-only", exception)
                    lastCapturedFace = null
                    stopRecordingAndSend()
                }
            }
        )
    }

    private fun stopRecordingAndSend() {
        try {
            recorder?.apply {
                stop()
                release()
            }
        } catch (e: Exception) {
            Log.e(TAG, "Failed to stop recording", e)
        }
        recorder = null
        stopCamera()

        setState(AppState.SENDING)
        NetworkClient.sendAudio(recordingFile, lastCapturedFace, responseFile) { result ->
            mainHandler.post {
                when (result) {
                    is CheckinResult.Success -> {
                        showResult(result)
                        playResponse()
                    }
                    is CheckinResult.Failure -> {
                        showError(result.message)
                        setState(AppState.IDLE)
                    }
                }
            }
        }
    }

    private val emotionCaptions = mapOf(
        "Anger" to "sounds a bit frustrated",
        "Happiness" to "sounds happy",
        "Neutral" to "sounds calm",
        "Sadness" to "sounds a bit down"
    )

    private fun showResult(result: CheckinResult.Success) {
        emptyStateLabel.visibility = View.GONE

        if (result.userText.isNotBlank()) {
            val phrase = emotionCaptions[result.emotionLabel]
                ?: result.emotionLabel.lowercase(Locale.getDefault())
            val confidencePct = (result.confidence * 100).toInt()
            val usedFace = result.faceLabel != null
            val caption = String.format(
                Locale.getDefault(),
                "%s · %d%% %s",
                phrase,
                confidencePct,
                if (usedFace) "(voice+face)" else "(voice)"
            )
            chatAdapter.addMessage(ChatMessage(ChatMessage.Role.USER, result.userText, caption))
        }
        chatAdapter.addMessage(ChatMessage(ChatMessage.Role.ASSISTANT, result.responseText))
        chatRecyclerView.scrollToPosition(chatAdapter.itemCount - 1)
    }

    private fun playResponse() {
        setState(AppState.SPEAKING)
        player?.release()
        try {
            player = MediaPlayer().apply {
                setDataSource(responseFile.absolutePath)
                setOnCompletionListener {
                    it.release()
                    player = null
                    setState(AppState.IDLE)
                }
                setOnErrorListener { mp, what, extra ->
                    Log.e(TAG, "MediaPlayer error: what=$what extra=$extra")
                    mp.release()
                    player = null
                    showError("Couldn't play the response audio")
                    setState(AppState.IDLE)
                    true
                }
                prepare()
                start()
            }
        } catch (e: Exception) {
            Log.e(TAG, "Failed to play response", e)
            showError("Couldn't play the response: ${e.message}")
            setState(AppState.IDLE)
        }
    }

    override fun onDestroy() {
        super.onDestroy()
        recorder?.release()
        player?.release()
        cameraProvider?.unbindAll()
    }
}
