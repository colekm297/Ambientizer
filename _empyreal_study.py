"""Cole 2026-10-24: Empyreal Ambient's 'Ultimate DUNE Ambience' (3SnFFdHVvdo, 209K views in 38 days)
"crushes everything we do... ours has so many random elements". Gemini listens to the reference at
three points plus our Last Light, names the difference, and writes music_v2 prompts in its style."""
import os, sys, json, subprocess
from pathlib import Path
from dotenv import load_dotenv; load_dotenv()
from google import genai
from google.genai import types
REF = "https://www.youtube.com/watch?v=3SnFFdHVvdo"
OUT = Path("output/_competitor/empyreal"); OUT.mkdir(parents=True, exist_ok=True)
c = genai.Client(api_key=os.environ["GEMINI_API_KEY"]); M = "gemini-4-argon"

def yt(a, b):
    return types.Part(file_data=types.FileData(file_uri=REF, mime_type="video/mp4"),
                      video_metadata=types.VideoMetadata(start_offset=f"{a}s", end_offset=f"{b}s", fps=0.2))

ours = OUT / "ours_lastlight_4m.mp3"
if not ours.exists():
    subprocess.run(["ffmpeg","-y","-v","error","-ss","60","-t","240","-i","output/release/dusk_arrakis/audio_cell.wav",
                    "-b:a","192k",str(ours)], check=True)

ASK = """You are a senior ambient music producer. Listen closely to the AUDIO only.
Clips 1-3 are from a hugely successful Dune ambient video (start, 1 hour in, 2.5 hours in).
Clip 4 is OUR Dune ambient track, which the channel owner says sounds low quality next to it, with
"so many random elements".

Answer in this order, concretely, as a producer would:
1. THE REFERENCE: every sound source you hear (instrument, synth type, field recording), its register,
   how often it moves, harmonic content (key, how many chords, does it ever change), tempo or pulse if any,
   melodic density (notes per minute for any lead), dynamics over time, reverb/space, stereo width,
   low end, high end, perceived loudness, and how much it changes between clip 1, 2 and 3.
2. OUR TRACK: the same checklist.
3. THE DIFFERENCE: ranked, the specific things that make ours sound cheaper or busier. Name the
   "random elements" exactly (what sound, roughly when).
4. Is the reference most likely human-produced (DAW, real instruments, e.g. a played duduk) or AI-generated? Why.
5. Write 3 prompts for ElevenLabs Music (music_v2, instrumental, 10 minutes) that would get as close as
   possible to the reference. Each under 900 characters. Be explicit about what must NOT appear (no
   percussion, no new instruments entering, etc.). Vary them slightly (one closest to the reference, one
   with more of its lead voice, one sparser).
Return the prose for 1-4, then a final fenced ```json block: {"prompts": [{"name": "...", "prompt": "..."}]}"""

ours_part = types.Part.from_bytes(data=ours.read_bytes(), mime_type="audio/mpeg")
r = c.models.generate_content(model=M, contents=[
    "Clip 1 (reference, 0:00-4:00):", yt(0, 240),
    "Clip 2 (reference, 60:00-63:00):", yt(3600, 3780),
    "Clip 3 (reference, 150:00-153:00):", yt(9000, 9180),
    "Clip 4 (ours):", ours_part, ASK])
(OUT / "study.md").write_text(r.text); print(r.text)
