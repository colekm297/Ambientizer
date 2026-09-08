import os, requests, time
from elevenlabs.client import ElevenLabs
BASE="http://127.0.0.1:5050"
el=ElevenLabs(api_key=os.environ["ELEVENLABS_API_KEY"])
STOP_AT=60000; MAX_TRACKS=50
THEMES=[
 "Blade Runner 2049 — a golden irradiated wasteland, quiet melancholy","Dune Messiah — Paul's burden of prescience, tragic weight",
 "The Fifth Element — a colorful future megacity, playful wonder","Wall-E — a lonely robot among ruins, tender hope",
 "Her — a warm near-future city at dusk, intimate longing","Children of Men — a bleak dystopian future, weary resolve",
 "Snow Crash — a neon virtual metaverse, electric curiosity","Neuromancer — a rain-slick sprawl at night, cool detachment",
 "Hyperion — pilgrims crossing alien world, epic dread","The Left Hand of Darkness — an icebound alien world, stark beauty",
 "Legend of Zelda: Breath of the Wild — a ruined kingdom reclaimed by nature, quiet awe",
 "Studio Ghibli — a countryside train at sunset, gentle nostalgia","Final Fantasy — a crystal shrine at dawn, epic hope",
 "Bloodborne — a gaslit gothic city at night, unsettling grandeur","Ico — a crumbling castle by the sea, lonely tenderness",
 "Shadow of the Colossus — an empty forbidden land, solemn vastness","No Man's Sky — drifting between alien planets, endless wonder",
 "Subnautica — an alien ocean world, awe and quiet dread","Outer Wilds — a dying solar system on loop, wistful curiosity",
 "Everybody's Gone to the Rapture — an empty English village, eerie calm",
 "a bamboo forest in the mist, tranquil","an old bookstore on a rainy evening, cozy nostalgia",
 "a candlelit wine cellar, warm and hushed","a rooftop garden above a sleeping city, peaceful",
 "an old windmill on a hill at dusk, pastoral calm","a desert oasis at twilight, quiet relief",
 "a foggy harbor town at dawn, wistful","an alpine meadow under stars, serene vastness",
 "a moonlit rice paddy terrace, still and reflective","a hot spring in snowy mountains, warm stillness",
 "an ancient stone bridge over a misty river, timeless","a lantern-lit temple courtyard, sacred hush",
 "a coastal cave with bioluminescent waves, magical wonder","a quiet orchard in late autumn, gentle melancholy",
 "an observatory dome opening to the night sky, hopeful wonder","a frozen waterfall cave, crystalline stillness",
 "a solitary cabin by a still lake, peaceful isolation","an old growth cypress swamp at dusk, mysterious calm",
 "a mountain pass in the clouds, quiet grandeur","a sunlit greenhouse full of orchids, tender warmth",
 "a distant space colony orbiting a gas giant, hopeful frontier","an underground crystal city, glowing wonder",
 "a floating monastery among clouds, serene detachment","a quiet tide pool at low tide, gentle discovery",
 "an ancient sequoia grove at dawn, reverent scale","a desert stargazing camp, warm companionship",
 "a snow-covered shrine at New Year's, quiet hope","a lighthouse keeper's quiet evening, steady solitude",
 "a canal city at night reflected in water, romantic stillness","an aurora over a frozen sea, cold luminous wonder",
 "a hidden waterfall grotto, secret tranquility","a terraced hillside vineyard at dusk, warm harvest calm",
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
print(f"BURN4 DONE — {n_ok} tracks generated",flush=True)
