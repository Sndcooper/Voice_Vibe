# Airoot / Voice Vibe handoff

Overlay source: `assets/airoot_overlay.py`. Build: `assets/AirootVoiceOverlay.spec`
using the existing `C:/Users/vilas/Documents/Codex/2026-09-23/make/work/overlay-venv`.
The spec preserves the machine-specific ICU DLL exclusion.
Configured executable: `C:/Users/vilas/Documents/Codex/2026-09-23/make/outputs/AirootVoiceOverlay.exe`.
Restart Voice Vibe using `run.bat` to pick up Python/config changes.

## Animation

Recording retains the small dancing red logo and Listening capsule at the bottom.
Processing gathers the sprite toward the existing 168 x 28 capsule over 380ms,
with fixed window geometry. The pill displays only `Transcribing...`.
A transcript packet signals completion without displaying its content. The pill
fades over 280ms. Fast results finish the gather first. A continuous session can
queue its return to Listening after the fade. Hide also signals completion;
repeated hide commands do not restart the fade. A new recording can interrupt
unfinished processing. Microphone device selection and focus-safe flags remain.

## Raw fidelity

No peak-amplitude drop, and no post-decode no_speech_prob drop. VAD is off by
default and may be opted into. Decoder no-speech skipping is disabled unless
explicitly configured; log_prob_threshold remains a fallback threshold.
Basic polishing is now enabled by default: capitals, spacing, and punctuation.
The live dictation path ignores legacy lists, replacements, edits and assistant
actions. Only a standalone `press enter` utterance sends Enter; a sentence mention
remains text. `raw_dictation = true` still bypasses both polish and commands.
The same model and precision use beam size 3 and temperature 0 for deterministic
decoding, with potentially longer processing time. Wake/session activation remains.
No changes to physical microphone routing, CUDA setup, HDC handling, or Xet setup.

## Checks

Run the ordinary suite in the app venv, and `test_overlay_animation.py` in the
PySide6 overlay venv. `assets/overlay-qa` contains recording, morph and processing
renders. Live spoken accuracy must be assessed with the user's actual microphone;
unit checks establish that quiet audio and uncertain decoded words are not dropped.
