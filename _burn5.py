import os, requests, time
from elevenlabs.client import ElevenLabs
BASE="http://127.0.0.1:5050"
el=ElevenLabs(api_key=os.environ["ELEVENLABS_API_KEY"])
STOP_AT=15000  # push closer to zero since it resets tomorrow anyway
MAX_TRACKS=45
THEMES=[
 "Everything Everywhere All at Once — the multiverse unraveling, chaotic wonder","Arrival of Voyager — the golden record drifting past Neptune, hopeful farewell",
 "Interstellar's Cooper Station — a rotating space habitat, nostalgic hope","The Overlook Hotel — a snowbound empty hallway, uneasy stillness",
 "Twin Peaks — a foggy log cabin at midnight, mysterious dread","Pan's Labyrinth — an ancient stone faun's lair, dark fairy-tale wonder",
 "Coco — the land of the dead at dusk, warm and colorful","Encanto — a magical Colombian house at night, warm family wonder",
 "Moana — the open ocean under stars, adventurous hope","Kubo and the Two Strings — a paper-lantern spirit world, bittersweet wonder",
 "a whale song echoing through deep ocean trenches, vast and gentle","an aurora borealis over a silent tundra, cold luminous awe",
 "a monastery library at midnight, ancient and hushed","a paper lantern river festival, warm nostalgic glow",
 "a glacial fjord at dawn, vast and still","an old growth kelp forest underwater, swaying calm",
 "a desert night market under string lights, warm and alive","a mountain hot spring in falling snow, tranquil warmth",
 "a rain-soaked greenhouse at midnight, quiet growth","an abandoned amusement park at dusk, wistful nostalgia",
 "a coastal fishing village at dawn, gentle routine","a candlelit study filled with old maps, quiet curiosity",
 "an orchard in first bloom, tender renewal","a snowfall over a quiet mountain village, hushed peace",
 "a floating market at sunrise, warm bustling calm","a night train through mountain tunnels, rhythmic solitude",
 "a hidden shrine beneath a waterfall, sacred stillness","a coral atoll at high tide, warm and expansive",
 "an old astronomer's rooftop observatory, wistful wonder","a firefly meadow at dusk, magical and warm",
 "a quiet chapel bathed in stained-glass light, reverent calm","a desert canyon echoing with wind, ancient solitude",
 "a snow globe village frozen in time, cozy nostalgia","a lakeside cabin during a gentle rain, warm shelter",
 "an ancient library sinking slowly into the sea, melancholic wonder","a cloud forest at dawn, misty and alive",
 "a starlit desert campfire circle, warm companionship","a moonlit glacier bay, vast luminous cold",
 "an overgrown greenhouse ruin, quiet reclaiming",
]
def credits_left():
    try: s=el.user.subscription.get(); return s.character_limit - s.character_count
    except: return None
i=0; n_ok=0
while i < MAX_TRACKS:
    if i % 3 == 0:
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
print(f"BURN5 DONE — {n_ok} tracks generated",flush=True)
