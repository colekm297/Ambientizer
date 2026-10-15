> SNAPSHOT as of 2026-10-15 07:40. Anything newer — git commits, file mtimes, or your own conversation — outranks this file. Verify before acting.

# Thread tail — open with this

**Live item:** Frodo Sails West (job a083d482, "Lord of the Rings · Daily · Frodo Sails West") is waiting on Cole's rating. He played it at 06:57 on 2026-10-15. Ask how it landed, plainly, once.
**Open bug, owned by this workstream:** selecting job 32e87510 ("Three Knocks (misfire: rewritten, 1 min)") froze Chrome's renderer before any audio request. See the handoff's "Open bug" section for what the logs show.

---

**Cole:**
> run one please

**Me** (after a design panel of 4 designers and 3 judges, plus the judges' fixes):
> A new one is in your app now, at the top of the list:
>
> **LORD OF THE RINGS · Daily · Frodo Sails West**
>
> It's the very end of the story: Frodo, Gandalf and Bilbo sailing into the West as the grey veil opens onto a far green country at sunrise. It uses the shape of your two 3-star Fair Wind tracks: one soft heartbeat far back, rope and timber creaks, the bow through calm water, and cellos and horns that get closer and warmer past the middle and stay full to the last second. The hook is a soft, distant wordless voice singing a four-note call, answered by harp and low whistle. Full 10 minutes, clean stereo.
>
> [...] One caveat from the judges: it changes several things at once (new world, a voice as the hook, harp and whistle). A 3 tells us the recipe carries to new worlds; a low score won't say which change missed. The 7:30 run continues tomorrow as usual.

**Cole** (via Chief, 2026-10-15): when he plays a song in Ambientizer, the first play always takes 20 to 30 seconds to start.

**Me:**
> The first-play lag is fixed, Cole.
>
> **Cause:** the first time you played any song, the app built a 40-minute, 94 MB MP3 of it (the loop played twice, at high quality) and sent nothing until the whole file was done. On a 20-minute track that was 18 seconds of encoding before the first byte, then your phone's buffering on top. [...]
>
> | | Before | After |
> |---|---|---|
> | First play, cold song, time to first audio | **19.4 s** | **1.8 s** |
> | Audio already received 2.5 s into a cold play | 0 | 105 seconds' worth |
> | Any later play (with seeking) | 0.008 s | 0.016 s |
>
> One small trade: on a song's very first play the time display shows `--:--` and you can't seek until the file finishes, which is a few seconds behind playback. From the second play on, everything works as before.

*(No reply from Cole yet on either.)*
