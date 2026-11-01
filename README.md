# wangp-showrunner

A modified copy of the **Showrunner** plugin bundled with [WanGP](https://github.com/deepbeepmeep/WanGP)
(`plugins/showrunner`, by deepbeepmeep). Experimental: these patches work on our machine and were tested on a few productions,
not widely. Offered as ideas for upstream; take what is useful.

**Modified by hoodtronik, 2026-11-01** (WanGP Community License 2.0, section 4.1(d)). Every changed spot is marked
`hoodtronik fork` in the code. Based on the Showrunner in WanGP commit `UPSTREAM_WANGP_COMMIT`; diff `showrunner/` against
that commit's `plugins/showrunner` to see every change. License: [LICENSE.txt](LICENSE.txt) (WanGP Community License 2.0, free use only).

## Install
Copy `showrunner/` over `WanGP/plugins/showrunner` (back the original up first), then restart WanGP.

## Patches
- **Finish**: a Finish button ("Finish at full resolution") re-renders the chosen MiniMax H3 Ref2VA take at 1080 with H3 Two
  Phases (8 steps, LoRA `minimax_h3_larryvrh_v4_step600_ema` at 1;0), using the take itself as the video reference, its frame 0
  as the start image, the same cast references and the same kept soundtrack. Tested: same take (framing, pose, timing,
  lip-sync), sharper detail. Endpoint `POST /api/productions/{id}/shots/{shot}/finish[?start_frame=false]`.
  Related: deepbeepmeep/WanGP#2577.
- **Sets (locations)**: `brief.locations` = named places, each with pictures, the scenes (sequences) it covers and a lip-sync
  opt-in. Render adds a shot's set pictures (first two) after the cast's, by the shot's `location` field, else its scene; never
  on lip-synced shots unless the set allows it (a set plate as a second H3 reference closed singers' mouths in our tests);
  `location: "none"` keeps a performance shot plate-free. The director is told the sets and the rule. UI: Sets panel in the
  brief, a Sets button in the left rail (below Cast), a Set picker in the shot panel. Related: deepbeepmeep/WanGP#2579.
- **Guides**: per-shot `start_frame`, `end_frame` and `previz` slots (shot panel "Guides", upload role `guide`, target
  `<shot>:start|end|previz`). Render wires them the same way every time on reference templates (`guides.py`): start/end anchors
  with `<Picture n>` renumbering, previz as a camera-only video guide padded to >= 2.5 s. In a 7-shot 480p A/B, start+end frames
  beat start+previz (previz leaked its grey mannequins and cost about 2x).
- **LoRA fix after 2 failed takes**: a director tool `lora_fix(shot, need)`, refused until the shot has 2 takes judged failed,
  picks a proven LoRA for the failure from an H3 LoRA registry JSON and adds it on top of the template's LoRAs. Needs your own
  registry: set `SHOWRUNNER_H3_REGISTRY` or `"h3_registry_path"` in `settings/showrunner/config.json`; without one the tool
  just reports that it is not configured.
