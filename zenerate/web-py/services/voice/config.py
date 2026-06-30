"""Shared constants for the pipecat agent and caller services."""

# ElevenLabs "Alice" — fallback when no voice_id is set on the agent.
# An empty voice_id produces a malformed URL that ElevenLabs rejects with 403.
DEFAULT_VOICE_ID = "Xb7hH8MSUJpSbSDYk0k2"

# ElevenLabs "Adam" — used for the synthetic caller bot TTS so the caller and
# agent sound like different people on the recording.
CALLER_DEFAULT_VOICE_ID = "pNInz6obpgDQGcFmaJgB"
