"""Cole 2026-10-24: "make one like that now and use gemini to figure it out and listen to it".
Generates the three prompts Gemini wrote in output/_competitor/empyreal/study.md, then Gemini listens
to each take next to the reference and scores how close it is. Cole picks in the app."""
import re, sys, time, json, subprocess, os, requests
from pathlib import Path
from dotenv import load_dotenv; load_dotenv(".env")
from google import genai
from google.genai import types
BASE = "http://127.0.0.1:5050"; OUT = Path("output/_competitor/empyreal")
REF = "https://www.youtube.com/watch?v=3SnFFdHVvdo"
src = sys.argv[1] if len(sys.argv) > 1 else str(OUT / "study.md")
prompts = json.loads(re.search(r"```json\s*(.*?)```", Path(src).read_text(), re.S).group(1))["prompts"]
tag = sys.argv[2] if len(sys.argv) > 2 else "v1"
c = genai.Client(api_key=os.environ["GEMINI_API_KEY"])

def wav(jid):
    return json.load(open(f"saved_jobs/{jid}.json"))["config"]["layers"][0]["generated_audio_path"]
def secs(p):
    return float(subprocess.run(["ffprobe","-v","error","-show_entries","format=duration","-of","csv=p=0",p],capture_output=True,text=True).stdout or 0)

def grade(path, name):
    mp3 = OUT / f"take_{tag}_{re.sub(r'\W+','_',name)[:30]}.mp3"
    subprocess.run(["ffmpeg","-y","-v","error","-ss","90","-t","240","-i",path,"-b:a","192k",str(mp3)], check=True)
    r = c.models.generate_content(model="gemini-4-argon", contents=[
        "REFERENCE (0:00-4:00):", types.Part(file_data=types.FileData(file_uri=REF, mime_type="video/mp4"),
            video_metadata=types.VideoMetadata(start_offset="0s", end_offset="240s", fps=0.2)),
        "CANDIDATE:", types.Part.from_bytes(data=mp3.read_bytes(), mime_type="audio/mpeg"),
        "Listen to the AUDIO only. As a strict ambient producer: how close is the CANDIDATE to the REFERENCE's "
        "sound (thick warm unbroken pad, sub weight, rare recessed lead drowned in dark reverb, no busy melody, no "
        "random elements, rolled-off highs)? List every distracting or random element in the candidate with its "
        "time. List what is still missing. End with a line exactly 'SCORE: N/10'."])
    return r.text

res = []
for p in prompts:
    for attempt in (1, 2):
        g = requests.post(f"{BASE}/api/generate", json={"prompt": p["prompt"] + ("" if attempt == 1 else f" Take {attempt}."),
            "mode": "musical", "planner_mode": "raw", "music_length": 10, "duration": 10,
            "music_generation_mode": "text", "music_model": "music_v2", "mastering": True}, timeout=60).json()
        jid = g["job_id"]
        while True:
            s = requests.get(f"{BASE}/api/status/{jid}", timeout=30).json()
            if s.get("status") in ("complete", "error", "canceled"): break
            time.sleep(15)
        d = secs(wav(jid)) if s.get("status") == "complete" else 0
        print(p["name"], attempt, jid, s.get("status"), round(d), flush=True)
        if d >= 300: break
    name = re.sub(r"^\d+\.\s*", "", p["name"]).split("(")[0].strip()
    requests.post(f"{BASE}/api/job/{jid}/meta", json={"title": f"Empyreal-style · {name} ({tag})", "world": "Dune"}, timeout=30)
    try: crit = grade(wav(jid), name)
    except Exception as e: crit = f"grade failed: {e}"
    m = re.search(r"SCORE:\s*(\d+(?:\.\d+)?)", crit)
    res.append({"name": name, "job": jid, "secs": round(d), "score": float(m.group(1)) if m else None, "critique": crit})
    print(crit, flush=True)
    (OUT / f"takes_{tag}.json").write_text(json.dumps(res, indent=1))
print("DONE", flush=True)
