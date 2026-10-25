"""Round N+1: Gemini reads the prompts and critiques of the last round and writes 3 revised prompts."""
import os, sys, json, re
from pathlib import Path
from dotenv import load_dotenv; load_dotenv()
from google import genai
OUT = Path("output/_competitor/empyreal"); prev, nxt = sys.argv[1], sys.argv[2]
res = json.loads((OUT / f"takes_{prev}.json").read_text())
src = Path(sys.argv[3]) if len(sys.argv) > 3 else OUT / "study.md"
prompts = json.loads(re.search(r"```json\s*(.*?)```", src.read_text(), re.S).group(1))["prompts"]
ctx = "\n\n".join(f"PROMPT {p['name']}:\n{p['prompt']}\nRESULT score {r['score']}/10, critique:\n{r['critique']}"
                  for p, r in zip(prompts, res))
c = genai.Client(api_key=os.environ["GEMINI_API_KEY"])
r = c.models.generate_content(model="gemini-4-argon", contents=[(OUT / "study.md").read_text()[:6000],
    "Above: your study of the reference. Below: the prompts we sent to ElevenLabs music_v2 and how each take scored "
    "against the reference.\n\n" + ctx + "\n\nWrite 3 revised prompts (under 900 chars each) that fix what the critiques "
    "found, building mainly on the best-scoring one. Things that matter: thick warm pad with real sub-bass and 150-300 Hz "
    "body, slow two-chord swell every 15-20 s (not static, not rigid), one recessed duduk motif every 30-40 s drowned in "
    "dark reverb, no hiss, no harsh attacks. Text-to-music models respond to plain descriptive language, so prefer "
    "positive descriptions over long NO lists. Return only ```json {\"prompts\": [{\"name\": ..., \"prompt\": ...}]}```"])
(OUT / f"prompts_{nxt}.md").write_text(r.text); print(r.text)
