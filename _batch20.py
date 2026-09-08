import requests, time, json
BASE="http://127.0.0.1:5050"
# (seed, mode, model, minutes, stitch_cell_sec)
JOBS=[
 # 6 stitch 5+5 (warm / journey themes)
 ("Project Hail Mary — Grace and Rocky's warm friendship across the dark","stitch","music_v1",10,300),
 ("Interstellar — love reaching across time and space, warm and hopeful","stitch","music_v1",10,300),
 ("Rivendell — elven serenity, warm misty forests at golden hour","stitch","music_v1",10,300),
 ("Ancient observatory — the warm wonder of stargazing, hopeful awe","stitch","music_v1",10,300),
 ("Cozy starship cabin drifting between distant stars, warm and safe","stitch","music_v1",10,300),
 ("Dune — golden dawn warming the dunes of Arrakis, reverent and vast","stitch","music_v1",10,300),
 # 9 text 10 min v2 (cinematic)
 ("Inception — dream layers, a city folding slowly, surreal and grand","text","music_v2",10,0),
 ("Blade Runner — neon rain over a melancholy future city, cyberpunk","text","music_v2",10,0),
 ("Arrival — first contact, circular time, aching awe and mystery","text","music_v2",10,0),
 ("2001 A Space Odyssey — cosmic vastness, the silent monolith, solemn wonder","text","music_v2",10,0),
 ("Foundation — a vast galactic empire, slow grandeur across the stars","text","music_v2",10,0),
 ("A derelict starship adrift in cold dark space, dread and isolation","text","music_v2",10,0),
 ("Tron — a luminous digital grid, glowing synth geometry, electric","text","music_v2",10,0),
 ("Annihilation — the Shimmer, eerie iridescent beauty, biological wonder","text","music_v2",10,0),
 ("Skyrim — snowy Nordic peaks, ancient halls, aurora and stillness","text","music_v2",10,0),
 # 5 text 5 min v1 (quick loops)
 ("Gravity — orbital solitude, the fragile silence of space","text","music_v1",5,0),
 ("The Witcher — somber medieval dark-folk, candlelit and weary","text","music_v1",5,0),
 ("A fantasy tavern at night, cozy hearth, lute and firelight","text","music_v1",5,0),
 ("Hyrule fields — wistful adventure, ocarina warmth, open and free","text","music_v1",5,0),
 ("A sunken cathedral, vast reverberant underwater abyss, deep blue","text","music_v1",5,0),
]
done=[]
for i,(seed,mode,model,mins,csec) in enumerate(JOBS,1):
    try:
        e=requests.post(f"{BASE}/api/enhance-prompt",json={"prompt":seed,"mode":"musical","approach":"unified","enhance_style":"world"},timeout=240).json()
        layers=e.get("layers"); enh=e.get("enhanced_prompt")
        body={"prompt":enh,"layer_plan":layers,"mode":"musical","approach":"unified","music_length":mins,"duration":mins,
              "planner_mode":"claude","music_generation_mode":mode,"music_model":model,"mastering":True}
        if csec: body["stitch_cell_sec"]=csec
        g=requests.post(f"{BASE}/api/generate",json=body,timeout=60).json()
        jid=g.get("job_id"); tag=f"{mode}/{model.split('_')[1]}/{mins}m"+(f"/{csec}s" if csec else "")
        print(f"[{i}/20] JOB {jid} {tag} ({seed[:34]})",flush=True)
        while True:
            s=requests.get(f"{BASE}/api/status/{jid}",timeout=30).json()
            if s.get("status") in ("complete","error","canceled"):
                print(f"[{i}/20] {s.get('status').upper()} {jid}",flush=True); done.append((jid,s.get('status'),seed)); break
            time.sleep(12)
    except Exception as ex:
        print(f"[{i}/20] FAILED: {ex}",flush=True)
print("BATCH20 COMPLETE",flush=True)
