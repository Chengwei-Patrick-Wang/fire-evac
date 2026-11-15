## AI summary (Claude)

Across 54 simulated fires in this two-floor office, most people escaped, but some were trapped in 14 fires. The worst queue formed at the Door between Lobby and Corridor 1, with 23 people at peak. It is the single link funnelling Corridor 1 toward the main entrance, so most of that wait was spent in smoke. Fires starting in Lobby (L1) trapped 16.7 people on average because they cut off that main route. A likely fix to check is a second exit from Corridor 1 that bypasses the Lobby.

### Report card: Example office (synthetic, 2 floors)

**With the Main entrance blocked, smoke exposure rose 201% and 90% of people got out 53.3 s later on average.**

54 fires simulated (18 rooms × 3 seeds). Smoke: 1,128 person-seconds in smoke per fire on average; 2.7 people per fire at an illustrative smoke dose of 1 (in 25 of 54 fires). 90% out: median 124 s; not reached within 400 s in 2 of 54 fires. People trapped in 14 of 54 fires. Fire spread at illustrative drywall speeds: 11.0 other rooms per fire on average by 400 s, at most 11 rooms (fire in Kitchen (R101)).

#### Top weak spots

1. **Door between Lobby and Corridor 1** · F1
   - Door between Lobby and Corridor 1: 23 people queued at peak; 107 person-seconds of waiting on average, 90 of them in smoke, across 54 fires.
   - **Fix:** Replace the Door between Lobby and Corridor 1 with a wider double door so the corridor drains into the Lobby faster.
2. **Fires starting in Lobby (L1)** · F1
   - Fire in Lobby (L1): 16.7 people trapped on average; 90% out after 323 s (3 fires).
   - **Fix:** Add a direct exit from Corridor 1 to outside that avoids the Lobby, and install early smoke detection in the Lobby.
3. **Exit East stair exit** · from Stair B (SB1) to outside, F1
   - Exit East stair exit: 13 people queued at peak; 96 person-seconds of waiting on average, 5 of them in smoke, across 54 fires.
   - **Fix:** Widen the East stair exit door from Stair B to outside, and add signs pointing occupants to alternative exits when it is busy.

Queues mark where the building runs short of capacity, not how people behave.

#### What-ifs

- **Stair doors propped open:** smoke exposure +31% (+443 person-seconds in smoke per fire); +0.5 people per fire at an illustrative smoke dose of 1; 90% out 0.2 s sooner on average (slower in 3 of 36 fires); trapped +0.0 per fire.
- **Exit Main entrance blocked:** smoke exposure +201% (+2,851 person-seconds in smoke per fire); +9.2 people per fire at an illustrative smoke dose of 1; 90% out 53.3 s later on average (slower in 34 of 36 fires); trapped +2.6 per fire.
- **Sprinklers on:** 1.8 fewer people trapped per fire; 90% out 14.6 s sooner on average (slower in 0 of 36 fires); smoke time is not compared: people who become trapped drop out of the frames.

---

*Numbers come from the simulation, not the model. Illustrative fire model; rule-based agents; fixes are ideas to check with a fire protection engineer, not a compliance result.*

*Written by Claude*
