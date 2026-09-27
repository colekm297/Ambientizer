# How a track is made on this channel

Written 2026-09-26 from the saved jobs (`saved_jobs/*.json`, 432 of them), the files in `output/`, the
app code, and the published videos. Read this before generating any music for a release. It exists
because agent sessions (me included) drifted off this method without noticing, and Cole caught it.

## The method, in one paragraph

Cole writes a detailed music prompt in the app, generates **one 10-minute take** (Music engine: **Text
prompt (single cell)**, Loop Length **10 min**), listens to it in the app's **Listen** tab, which plays one
loop of it with the seam audible, and rates it. If it holds, that single take is **looped to fill the
hour**. There is no stitching, no multi-part assembly, no second generation spliced in. One take, one
loop, repeated.

## What the numbers show

Every video Cole published was made this way:

| Video | Job | Mode | Model | One generation |
|---|---|---|---|---|
| Arrakis Desert Rain | b97e79e4 | single (pre-mode) | - | 5 min |
| Spacecraft Ambience | 396936dc | single | - | 10 min |
| Escher's Paradox | 7a532b70 | single | - | 10 min |
| Sanctuary | 7858db06 | single | - | 3 min |
| A Small Light in the Dark | 003d71e2 | text | - | 10 min |
| Beneath the Desert Temples | 8fae45d5 | text | - | 10 min |
| Two Minds, One Light | 34b312a1 | text | - | 10 min |
| Dawn Over Arrakis | 10919aaa | text | - | 5 min |
| Trapped on Calypso's Shore | a38b5c83 | text | music_v2 | 10 min (540 s came back) |
| The Sirens' Strait | eec20d97 | text | music_v2 | 10 min (479 s came back) |
| Fair Wind Home | 2bacadbf | text | music_v2 | 10 min (600 s) |
| **Dusk Over Arrakis** | 5b507e87 | **stitch** | music_v1 | 20 min of stitched cells |

Dusk is the exception, and it was built by an agent session, not by Cole in the app. So was the held
Hail Mary render (Tau Ceti Vigil, ce42ae6f: stitch, music_v1, 30 min), the one Cole called a Doom
soundtrack. Stitch mode was tried in July (48 jobs at 15 min) and never published by Cole.

Across all 432 jobs: text at 10 min is the most-used setting by far (190 jobs), then text at 5 min (59).

## Where the files are, and what the lengths mean

- **The actual generation** is the layer's `generated_audio_path` in the job JSON, in the sample cache.
  For a text take that is at most 600 s; ElevenLabs sometimes returns less (Calypso 540 s, Sirens 479 s).
- `output/<job>_<layer>_<stamp>_loop.wav` is that take with dead silence trimmed and a 2 s crossfade at the
  wrap (`audio_engine.prepare_musical_loop`). This is the **loop cell**: Fair Wind's is 524 s.
- `output/<stamp>_<title>_raw_mastered.wav` is the job's rendered mix at the job's duration setting. When the
  job duration is 20 min, this file is the 10-min take looped twice (Fair Wind's is 1175 s). It is NOT a
  20-minute generation. Earlier sessions misread this file as "a 20-minute take".
- `<job>_stream_x2.mp3` is what the phone player streams: the loop cell doubled, so the seam lands in the
  middle and can be heard.
- **Export Looped** (Listen tab, with the 1 hour dropdown) → `POST /api/export-extended/<job>` tiles the
  loop cell to the target length with a short crossfade per repeat.

## Model

Cole's last three releases used **music_v2**. The UI default label says "Music v1 (tuned default)", and
the agent scripts `_gen_dusk_music.py`, `_gen_hm_music.py`, `_gen_hm_previews.py` hardcoded music_v1.
Match the model Cole uses unless he says otherwise.

## Where Cole listens

In the app, on any device: **http://ambientizer-mac.tail07d072.ts.net:5050** (Tailscale). Takes appear at
the top of the history; the bottom player's search box finds them by title. Never send audio as file
attachments.

## Rules for agent sessions

1. Generate candidates the way Cole does: **text mode, 10 min, one take each, `planner_mode: "raw"`**, his model. Not stitch,
   not 1-minute sketches (a 1-minute clip cannot show whether the loop holds, which is the whole
   question), not 30-minute assemblies.
2. The music is Cole's pick. Put 2-3 candidate takes in the app, tell him (via Chief) the titles, stop.
3. The released hour is the chosen take's loop cell repeated. If a build script makes the master (for
   the sting, the cards, and the Seedance video), it takes that one loop cell as its audio input.
4. Prompts: Cole's prompts are long and specific (key, tempo, harmonic motion, named instruments and
   what each does, what must never happen). Write candidates at that level, and never put "deep sub
   drone" or "never resolves" on a piece meant to feel hopeful; that is where Tau Ceti Vigil went dark.

## Two traps found 2026-09-26

- **Raw mode is `"planner_mode": "raw"`** in the `/api/generate` body (the UI's "Raw (no interpretation)"
  checkbox sends exactly that). A `"raw": true` field is ignored, and then the interpreter rewrites the
  prompt: it turned "D major, hopeful" into "Eb minor" on the first Three Knocks attempt. Fair Wind's
  take was raw (its layer is named "Raw prompt"). Send candidates raw unless Cole wants interpretation.
- **ElevenLabs sometimes returns less than asked.** The log line `PCM: ... (expected ~600s)` shows it:
  the non-raw attempts that day came back 60 s, 405 s, 408 s. Check the generated length before
  showing Cole a take, and regenerate if it is short.

## What Cole's 3-star prompts have in common (read before writing one)

From every job he rated 3 (Calypso a38b5c83, Dawn 10919aaa, observatory 94b60fc9, Fair Wind 324a1f7b and
1af58c0f, Sirens eec20d97):

- **A known world and a specific moment in it** (Calypso's shore, dawn over Arrakis, the ship heading
  home, the sirens' strait).
- **A pulse.** Most have a soft frame drum "like a distant heartbeat" or oars keeping rowing time. That
  pulse is what makes a track feel like it is going somewhere. Agent prompts banned all percussion; that
  is a large part of why they were boring.
- **A hook.** Sirens: "a wordless female vocal carries an achingly sweet three-note descending call."
  Fair Wind: a lyre tracing "slow yearning figures", flute "homeward phrases". One recognizable idea.
- **A journey across the 10 minutes**, written out: "opens with wind, heartbeat pulse and pedal; strings
  and horns gradually fill like the day turning gold; at its fullest the music becomes closer and
  warmer", or "the call grows slowly nearer, peaks past the midpoint, then recedes as the ship passes."
- **Named parts** (THE WIND / THE SHIP / HOME AHEAD; THE LURE / THE PERIL / THE SHIP), each with a job.
- **Diegetic sound** from the scene: rope and hull creaks, waves at the bow, wind in a sail.
- Specific harmony (a named progression over a pedal), and specific bans only where a real problem was
  heard (no cymbals, no electric guitar).

What agent prompts did instead, and must stop doing: "nothing resolves", "no builds", "no percussion",
"keep it gentle the whole way through". Those instructions produce exactly what Cole called boring
tracks that go nowhere.
- **Music v2.5 returns about 6 minutes, not 10** (asked 600 s, got 348 s and 375 s on 2026-09-26; the docs
  now say a 5-minute max). On v2.5 the loop is ~6 min; on v2 it is the full 10.
- **Channel detection bug, fixed 2026-09-26.** `_save_pcm_to_wav` used to pick mono vs stereo by whichever
  reading landed nearer the REQUESTED length. A short v2.5 return made the mono reading win, and the take
  was saved as garbled half-speed noise. It now decides from the samples (`_detect_pcm_channels`). The same
  day's first "v2.5" Three Knocks was a cache hit on the v2 file because the model was not in the cache
  key; it is now.
