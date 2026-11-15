## AI summary (Claude)

Across 54 simulated fires in this two-floor office, no one was trapped and 90% of people were out in a median of 113 s. The longest queue formed at the Exit East stair exit, where everyone coming down Stair B funnels through a single outdoor door, with 25 people queued at peak. The Door between Lobby and Corridor 1 also backed up, because Corridor 1 traffic must squeeze through it toward the Main entrance. A likely fix to check is widening the Exit East stair exit or adding a second door there.

### Report card: Example office (synthetic, 2 floors)

**Blocking the Main entrance raised smoke exposure by 315% and delayed 90% evacuation by 71.3 s, trapping 3.4 more people per fire.**

54 fires simulated (18 rooms × 3 seeds). Smoke: 637 person-seconds in smoke per fire on average; 0.4 people per fire at an illustrative smoke dose of 1 (in 10 of 54 fires). 90% out: median 113 s, worst 143 s. No one trapped in any fire. Fire spread at illustrative drywall speeds: 11.0 other rooms per fire on average by 400 s, at most 11 rooms (fire in Kitchen (R101)).

#### Top weak spots

1. **Exit East stair exit** · from Stair B (SB1) to outside, F1
   - Exit East stair exit: 25 people queued at peak; 197 person-seconds of waiting on average, 26 of them in smoke, across 54 fires.
   - **Fix:** Replace the Exit East stair exit with a wider double door, or add a second outdoor door at the foot of Stair B.
2. **Fires starting in Lobby (L1)** · F1
   - Fire in Lobby (L1): 0.0 people trapped on average; 90% out after 136 s (3 fires).
   - **Fix:** Extend smoke detection and alarm coverage in the Lobby so a Lobby fire is detected early, and add a route bypassing the Lobby.
3. **Door between Lobby and Corridor 1** · F1
   - Door between Lobby and Corridor 1: 16 people queued at peak; 48 person-seconds of waiting on average, 21 of them in smoke, across 54 fires.
   - **Fix:** Widen the Door between Lobby and Corridor 1 to a double door and add signs steering Corridor 1 occupants toward the east stair.

Queues mark where the building runs short of capacity, not how people behave.

#### What-ifs

- **Stair doors propped open:** smoke exposure +65% (+584 person-seconds in smoke per fire); +0.2 people per fire at an illustrative smoke dose of 1; 90% out 0.3 s sooner on average (slower in 1 of 36 fires); trapped +0.0 per fire.
- **Exit Main entrance blocked:** smoke exposure +315% (+2,822 person-seconds in smoke per fire); +11.0 people per fire at an illustrative smoke dose of 1; 90% out 71.3 s later on average (slower in 36 of 36 fires); trapped +3.4 per fire.
- **Sprinklers on:** no change in people trapped; 90% out 0.9 s sooner on average (slower in 0 of 36 fires); smoke time is not compared: people who become trapped drop out of the frames.

---

*Numbers come from the simulation, not the model. Illustrative fire model; rule-based agents; fixes are ideas to check with a fire protection engineer, not a compliance result.*

*Written by Claude*
