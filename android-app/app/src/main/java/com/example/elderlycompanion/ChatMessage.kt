package com.example.elderlycompanion

data class ChatMessage(val role: Role, val text: String, val caption: String? = null) {
    enum class Role { USER, ASSISTANT }
}
