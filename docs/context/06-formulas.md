# Formulas

## Fire growth (t-squared)

Heat release rate in kW at time $t$ (s) after ignition, and the time to reach 1 MW:

$$Q(t) = \alpha t^{2}, \qquad t_{1\,\text{MW}} = \sqrt{\frac{1000\ \text{kW}}{\alpha}}$$

| Growth class | $\alpha$ (kW/s²) | Time to 1 MW |
| --- | --- | --- |
| Slow | 0.00293 | about 584 s |
| Medium | 0.01172 | about 292 s |
| Fast | 0.04688 | about 146 s |
| Ultra-fast | 0.1876 | about 73 s |

Cap at the preset's peak or when sprinklers activate:

$$Q(t) = \min\left(\alpha t^{2},\ Q_{\text{cap}}\right)$$

Liquid pool fires reach peak almost at once (a step function).

## Visibility in smoke

$$S = \frac{C}{K}, \qquad K = K_m \, \rho_{\text{soot}}$$

- $S$: visibility in meters.
- $K$: light extinction coefficient (1/m).
- $C$: 3 for signs that reflect light, 8 for signs that emit light.
- $K_m$: mass extinction coefficient (FDS default 8,700 m²/kg).
- $\rho_{\text{soot}}$: soot density.

## Walking speed in smoke (Fridolf et al., 2018, as used by Cheong, FEMTC 2020)

$$v = \min\left(v_{0},\ \max\left(0.2,\ v_{0} - 0.34\,(3 - S)\right)\right)$$

Free speed while visibility is at least 3 m; then minus 0.34 m/s per meter of lost visibility; never below 0.2 m/s.

## Door, corridor and stair capacity

IMO simplified method:

$$F_c = F_s \, W_c, \qquad t_F = \frac{N}{F_c}$$

- $F_s$ = 1.3 persons/(m·s) for doors and corridors, 1.1 for stairs going down.
- $W_c$ is the clear width.

Hydraulic model effective width (150 mm boundary layer on each side of a door):

$$W_e = W_c - 2 \times 0.15\ \text{m}$$

For a 1 m door, that gives 1.3 persons/s on clear width, or 0.91 if 1.3 is applied to the 0.7 m effective width. Our default JuPedSim door passed 0.97.

Other published values vary. Dutch guidance has used 1.5–2.25 persons/(m·s), and NIST researchers warn that assuming flow grows linearly with width can be optimistic.

## Timeline check

$$\text{RSET} = t_{\text{detection}} + t_{\text{alarm}} + t_{\text{pre-movement}} + t_{\text{travel}}, \qquad \text{margin} = \text{ASET} - \text{RSET}$$

A negative margin in any area flags it.

## Chokepoints and critical exits

Waiting at door $d$, with $q_d(t)$ people queued:

$$W_d = \int_{0}^{T} q_d(t)\,dt \;\approx\; \sum_{k} q_d(t_k)\,\Delta t$$

Criticality of exit $e$:

$$\Delta_e = \text{RSET}_{e\ \text{blocked}} - \text{RSET}_{\text{all open}}$$

## LLM cost

$$\text{cost} = N_{\text{agents}} \times n_{\text{decisions}} \times T_{\text{tokens}} \times p_{\text{token}}$$

- **One call per agent per step:** 1,000 agents × 200 decisions × 1,000 tokens = 200 M tokens per run. That's about $20–60 at $0.10–0.30 per million input tokens (third-party price listings, approximate).
- **Targeted use:** 20 agents × 5 decisions × 1,000 tokens = 100k tokens, about 1–3 cents.

## Simulation speed

$$\text{real-time factor} = \frac{\text{simulated time}}{\text{computer time}}$$
