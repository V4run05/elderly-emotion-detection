from gtts import gTTS


def synthesize(text: str, output_path: str) -> str:
    """Convert text to speech and save it as an MP3 at output_path."""
    gTTS(text).save(output_path)
    return output_path
