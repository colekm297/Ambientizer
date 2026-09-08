import os, requests, time
from elevenlabs.client import ElevenLabs
BASE="http://127.0.0.1:5050"
el=ElevenLabs(api_key=os.environ["ELEVENLABS_API_KEY"])
STOP_AT=60000; MAX_TRACKS=50
THEMES=[
 "Star Wars — a lonely desert moisture farm at twilight, wistful","Halo — a ringworld at dawn, vast and solemn",
 "Mass Effect — deep space exploration, awe and mystery","Doctor Who — the TARDIS drifting through the vortex, curious",
 "Stargate — an ancient alien temple, mysterious and sacred","Firefly — a lone ship crossing the black, weary and free",
 "The Matrix — the green-tinted machine city, cold and vast","Ghost in the Shell — a rain-soaked cybernetic city, introspective",
 "Akira — neo-Tokyo at night, electric and uneasy","Cowboy Bebop — a jazz-lit spaceship, melancholy and cool",
 "Elden Ring — the Lands Between at dusk, tragic grandeur","Hollow Knight — a ruined insect kingdom, haunting and quiet",
 "Journey — endless golden sand dunes, hopeful and lonely","Ori and the Blind Forest — a glowing enchanted wood, tender",
 "Death Stranding — a desolate post-apocalyptic America, somber","Horizon Zero Dawn — an overgrown ruined world, wild wonder",
 "Avatar — the bioluminescent forests of Pandora, alive and vast","Spirited Away — a magical bathhouse at night, whimsical",
 "Howl's Moving Castle — a floating castle over hills, dreamlike","Princess Mononoke — an ancient forest spirit realm, sacred",
 "a quiet lighthouse on a stormy coast, resilient","an abandoned space station drifting, eerie calm",
 "a greenhouse biodome on Mars, hopeful and green","a monastery bell tower at dawn, peaceful",
 "an underground bunker city, close and warm","a floating sky city above the clouds, majestic",
 "a crystal cave glowing softly, magical stillness","an old growth redwood forest at dawn, ancient calm",
 "a desert canyon at sunset, warm and vast","a coral reef city underwater, alive and colorful",
 "a train crossing endless snowy plains, contemplative","a night market in a rain-soaked alley, warm and busy",
 "a solitary space elevator climbing to orbit, awe","an orbital ring city above Earth, hopeful future",
 "a hidden valley monastery in the mountains, serene","a bioluminescent cave system, otherworldly wonder",
 "a wheat field under a slow sunset, nostalgic warmth","an old clocktower city at midnight, whimsical mystery",
 "a glacier cavern of blue ice, vast and cold","a terraformed moon colony, hopeful frontier",
 "the last library on Earth, quiet and sacred","a desert caravan under the stars, timeless journey",
 "an ancient underwater ruin, mysterious and still","a mountain observatory above the clouds, contemplative",
 "a quiet zen garden at dusk, tranquil","a starlit vineyard at harvest, warm nostalgia",
 "a snowbound research station, isolated calm","a floating lantern festival at night, warm wonder",
 "a canyon of singing wind, ancient and vast","a coastal cliffside temple, reverent and windswept",
]
def credits_left():
    try: s=el.user.subscription.get(); return s.character_limit - s.character_count
    except: return None
i=0; n_ok=0
while i < MAX_TRACKS:
    if i % 5 == 0:
        c=credits_left()
        if c is not None:
            print(f"[credits] {c:,} left  ({n_ok} made)",flush=True)
            if c < STOP_AT: print("STOP: below threshold",flush=True); break
    seed=THEMES[i % len(THEMES)]
    mins=[10,5,15,10][i%4]; mode=["text","text","stitch","text"][i%4]; model=["music_v2","music_v1"][i%2]
    try:
        e=requests.post(f"{BASE}/api/enhance-prompt",json={"prompt":seed,"mode":"musical","approach":"unified","enhance_style":"world"},timeout=240).json()
        body={"prompt":e.get("enhanced_prompt"),"layer_plan":e.get("layers"),"seed_idea":seed,"mode":"musical",
              "approach":"unified","music_length":mins,"duration":mins,"planner_mode":"claude",
              "music_generation_mode":mode,"music_model":model,"mastering":True}
        if mode=="stitch": body["stitch_cell_sec"]=300
        jid=requests.post(f"{BASE}/api/generate",json=body,timeout=60).json().get("job_id")
        while True:
            s=requests.get(f"{BASE}/api/status/{jid}",timeout=30).json()
            if s.get("status") in ("complete","error","canceled"): break
            time.sleep(10)
        if s.get("status")=="complete": n_ok+=1
        print(f"[{i+1}] {s.get('status')} {jid} {mode}/{model.split('_')[1]}/{mins}m :: {seed[:30]}",flush=True)
    except Exception as ex:
        print(f"[{i+1}] FAILED: {ex}",flush=True)
    i+=1
print(f"BURN3 DONE — {n_ok} tracks generated",flush=True)
