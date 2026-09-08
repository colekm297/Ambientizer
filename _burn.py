import os, requests, time, json
from elevenlabs.client import ElevenLabs
BASE="http://127.0.0.1:5050"
el=ElevenLabs(api_key=os.environ["ELEVENLABS_API_KEY"])
STOP_AT=60000   # stop when remaining credits drop below this
MAX_TRACKS=200
THEMES=[
 "Dune — moonlit dunes of Arrakis, vast and reverent","Project Hail Mary — alone at Tau Ceti, quiet awe",
 "Interstellar — drifting toward the wormhole, aching wonder","Inception — a dream city folding, surreal",
 "Blade Runner — neon rain, melancholy cyberpunk","Arrival — first contact, circular time",
 "2001 — cosmic vastness, the silent monolith","Solaris — the living ocean planet, strange and sad",
 "Foundation — a vast galactic empire, slow grandeur","Alien — a derelict ship adrift, cold dread",
 "Tron — the luminous digital grid, electric","Annihilation — the iridescent Shimmer, eerie beauty",
 "Gravity — orbital solitude, fragile silence","The Expanse — the asteroid belt, working-class space",
 "Contact — listening to the stars, hopeful awe","Ad Astra — the loneliness of deep space travel",
 "The Martian — red planet survival, determined calm","Moon — an isolated lunar base, weary",
 "Event Horizon — a haunted ship at the edge, ominous","Passengers — a sleeping starship, lonely beauty",
 "Middle-earth — Rivendell, elven serenity at golden hour","Skyrim — snowy Nordic peaks, aurora and stillness",
 "The Witcher — somber medieval dark-folk","Zelda — Hyrule fields, wistful adventure",
 "a fantasy tavern hearth at night, cozy","Dark Souls — a crumbling kingdom, mournful grandeur",
 "an ancient elven forest at dusk, mystical","vast dwarven halls deep underground, echoing",
 "a sleeping dragon's hoard cavern, smoldering","an enchanted library at midnight, hushed wonder",
 "the deep ocean abyss, vast and dark","a rainforest at night, humid and alive",
 "the arctic tundra under aurora, frozen stillness","a mountain monastery at dawn, sacred calm",
 "a sunken cathedral underwater, reverberant blue","ancient desert ruins under stars, timeless",
 "the cosmic void between galaxies, infinite","a lucid dream drifting, weightless",
 "a meditation temple, incense and stillness","a snowbound winter cabin, warm and safe",
]
def credits_left():
    try:
        s=el.user.subscription.get(); return s.character_limit - s.character_count
    except: return None
i=0; made=[]
while i < MAX_TRACKS:
    if i % 4 == 0:
        c=credits_left()
        if c is not None:
            print(f"[credits] {c:,} left",flush=True)
            if c < STOP_AT: print("STOP: credits below threshold",flush=True); break
    seed=THEMES[i % len(THEMES)]
    mins=[10,5,15,10][i%4]; mode=["text","text","stitch","text"][i%4]
    model=["music_v2","music_v1"][i%2]
    try:
        e=requests.post(f"{BASE}/api/enhance-prompt",json={"prompt":seed,"mode":"musical","approach":"unified","enhance_style":"world"},timeout=240).json()
        body={"prompt":e.get("enhanced_prompt"),"layer_plan":e.get("layers"),"seed_idea":seed,"mode":"musical",
              "approach":"unified","music_length":mins,"duration":mins,"planner_mode":"claude",
              "music_generation_mode":mode,"music_model":model,"mastering":True}
        if mode=="stitch": body["stitch_cell_sec"]=300
        g=requests.post(f"{BASE}/api/generate",json=body,timeout=60).json(); jid=g.get("job_id")
        print(f"[{i+1}] {jid} {mode}/{model.split('_')[1]}/{mins}m :: {seed[:34]}",flush=True)
        while True:
            s=requests.get(f"{BASE}/api/status/{jid}",timeout=30).json()
            if s.get("status") in ("complete","error","canceled"): break
            time.sleep(12)
        if s.get("status")=="complete":
            try:
                fb=requests.post(f"{BASE}/api/ai-feedback/{jid}",timeout=600).json(); sc=fb.get("score")
            except: sc=None
            made.append((jid,sc,seed)); print(f"[{i+1}] done score={sc}",flush=True)
        else:
            print(f"[{i+1}] {s.get('status')}: {s.get('error')}",flush=True)
    except Exception as ex:
        print(f"[{i+1}] FAILED: {ex}",flush=True)
    i+=1
print("\nBURN COMPLETE — top scorers:",flush=True)
for jid,sc,seed in sorted([m for m in made if m[1]],key=lambda x:x[1],reverse=True)[:15]:
    print(f"  {sc}/10  {jid}  {seed[:40]}",flush=True)
print(f"BURN DONE — {len(made)} tracks made",flush=True)
