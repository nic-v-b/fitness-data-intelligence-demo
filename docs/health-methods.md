# Fictional health and training methods

Fitness Profile and Training Planner share the same 36-week fictional athlete history. The scenario control changes this history on both pages. The heavier scenario adds two completed sessions in the final week and shortens sleep over the final six mornings. Recorded private FIT activities do not enter this fixture.

| Indicator | Inputs and method |
| --- | --- |
| HRV and resting heart rate | Simulated daily morning RMSSD in milliseconds and resting heart rate in bpm. The status cards show the latest seven mornings' medians and their personal reference over the preceding 28 mornings. |
| Sleep | Simulated duration and a separate illustrative 1–5 quality rating. The status card shows seven-morning averages. |
| Estimated VO₂max | An illustrative estimate from each fictional 5 km benchmark. Speed in metres per minute supplies oxygen cost via `3.5 + 0.2 × speed`. Dividing by an assumed 0.90 of maximum effort yields the displayed estimate. Terrain, running economy and achieved effort can affect this estimate. |
| Training load | The sum of completed session minutes × fictional session RPE on a 0–10 scale. The latest seven and 28 complete days end before the scored morning. The 28-day sum divided by four supplies the weekly equivalent. |
| Readiness | An illustrative 0–100 composite using personal HRV and resting-heart-rate medians from the 28 preceding mornings, last night's sleep duration, and the completed load windows. The first score requires 28 prior mornings. |

For readiness, clamp each component to 0–100. The HRV component is `83 + 150 × (today / baseline − 1)`. The resting-rate component is `90 − 5 × (today − baseline)`. The sleep component is `100 × minutes / 480`. The load component is `91 − 95 × max(0, seven-day load / weekly equivalent − 1)`, with zero excess when the reference load is zero. Round components to one decimal, then weight them 30%, 15%, 30% and 25%, respectively. Sleep quality and estimated VO₂max appear as parallel context. These demo weights have no clinical validation.

The Planner's volume guard activates below 72 readiness or above 120% of the weekly load equivalent from the 28 days preceding the most recent seven days. It reduces the starting distance budgets by 20% and omits the controlled effort. The lighter option applies a further 25% reduction before rounding. Session distance and recent within-sport time per kilometre estimate planned duration. Assumed session RPE then supplies projected load. Changing a plan option affects proposed sessions and projected load. The morning observations and completed load belong to the selected scenario. [Semantic bands](semantic-methods.md)

The three key takeaways use deterministic text templates. Each exposes the evidence behind its statements. Profile and Planner health values are fictional in both preview modes. Explorer describes real activities only when the selected activity is a private FIT.
