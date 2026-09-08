import requests, time
BASE="http://127.0.0.1:5050"
# (seed, model, minutes) — 5x v1@5min, 5x v2@10min, alternating
JOBS=[
 ("Dune — dawn breaking over the endless dunes of Arrakis, vast and reverent","music_v1",5),
 ("Dune — deep in a sietch, the water of life, sacred and hidden","music_v2",10),
 ("Project Hail Mary — Grace and Rocky, an unlikely friendship across the dark","music_v1",5),
 ("Project Hail Mary — alone at Tau Ceti, the quiet weight of saving humanity","music_v2",10),
 ("Interstellar — drifting past Saturn toward the wormhole, awe and the unknown","music_v1",5),
 ("Interstellar — the ache of time lost, a father's love across the years","music_v2",10),
 ("Inception — limbo, an empty city dissolving into the sea","music_v1",5),
 ("Inception — the slow fold of a dreamed world, gravity bending","music_v2",10),
 ("Adrift in a luminous nebula, stardust and quiet wonder","music_v1",5),
 ("The long sleep of a generation ship gliding between distant stars","music_v2",10),
]
for i,(seed,model,mins) in enumerate(JOBS,1):
    try:
        e=requests.post(f"{BASE}/api/enhance-prompt",json={"prompt":seed,"mode":"musical","approach":"unified","enhance_style":"world"},timeout=240).json()
        layers=e.get("layers"); enh=e.get("enhanced_prompt")
        g=requests.post(f"{BASE}/api/generate",json={"prompt":enh,"layer_plan":layers,"mode":"musical","approach":"unified",
            "music_length":mins,"duration":mins,"planner_mode":"claude","music_generation_mode":"text","music_model":model,"mastering":True},timeout=60).json()
        jid=g.get("job_id"); print(f"[{i}/10] JOB {jid} {model} {mins}min ({seed[:35]})",flush=True)
        while True:
            s=requests.get(f"{BASE}/api/status/{jid}",timeout=30).json()
            if s.get("status") in ("complete","error","canceled"): print(f"[{i}/10] {s.get('status').upper()} {jid}",flush=True); break
            time.sleep(12)
    except Exception as ex:
        print(f"[{i}/10] FAILED: {ex}",flush=True)
print("BATCH_TEXT10 COMPLETE",flush=True)
