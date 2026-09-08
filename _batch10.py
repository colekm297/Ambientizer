import requests, time, json, sys
BASE="http://127.0.0.1:5050"
SEEDS=[
 "Dune — dawn breaking over the endless dunes of Arrakis, vast and reverent",
 "Dune — deep in a sietch, the water of life, sacred and hidden",
 "Project Hail Mary — Grace and Rocky, an unlikely friendship across the dark",
 "Project Hail Mary — alone at Tau Ceti, the quiet weight of saving humanity",
 "Interstellar — drifting past Saturn toward the wormhole, awe and the unknown",
 "Interstellar — the ache of time lost, a father's love across the years",
 "Inception — limbo, an empty city dissolving into the sea",
 "Inception — the slow fold of a dreamed world, gravity bending",
 "Adrift in a luminous nebula, stardust and quiet wonder",
 "The long sleep of a generation ship gliding between distant stars",
]
done=[]
for i,seed in enumerate(SEEDS,1):
    try:
        e=requests.post(f"{BASE}/api/enhance-prompt",json={"prompt":seed,"mode":"musical","approach":"unified","enhance_style":"world"},timeout=240).json()
        layers=e.get("layers"); enh=e.get("enhanced_prompt")
        prm=(layers[0].get("prompt_preview") if layers else enh) or ""
        print(f"[{i}/10] ENHANCED: {prm[:90]}",flush=True)
        g=requests.post(f"{BASE}/api/generate",json={"prompt":enh,"layer_plan":layers,"mode":"musical","approach":"unified",
            "music_length":15,"duration":15,"planner_mode":"claude","music_generation_mode":"stitch","music_model":"music_v1","mastering":True},timeout=60).json()
        jid=g.get("job_id"); print(f"[{i}/10] JOB {jid} ({seed[:40]})",flush=True)
        while True:
            s=requests.get(f"{BASE}/api/status/{jid}",timeout=30).json()
            st=s.get("status")
            if st in ("complete","error","canceled"):
                print(f"[{i}/10] {st.upper()} {jid}",flush=True); done.append((jid,st,seed)); break
            time.sleep(12)
    except Exception as ex:
        print(f"[{i}/10] FAILED: {ex}",flush=True)
print("BATCH10 COMPLETE:",flush=True)
for jid,st,seed in done: print(f"  {st}  {jid}  {seed[:50]}",flush=True)
