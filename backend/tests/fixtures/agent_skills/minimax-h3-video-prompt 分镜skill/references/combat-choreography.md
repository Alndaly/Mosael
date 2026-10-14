# Combat choreography compiler

Use this reference for any action scene. Create the beat card internally, then convert it to ordinary English inside H3's `integrated_multimodal_description` or `detailed_description`. Do not paste this card's headings into the final H3 prompt.

## Beat-card method

For each combat shot, plan one to three readable exchanges. An exchange contains:

```text
opening geometry: who is where, facing which direction, distance, height, guard, weapon/prop state
intent and trigger: what each fighter reads, feints, protects, or tries to gain
attack path: limb/weapon/technique, start point, trajectory, level, target
defense: block, parry, deflection, slip, step, redirect, barrier, or sacrifice
result: hit, graze, miss, clash, or interruption; precise force and environment response
new geometry: footing, distance, facing, weapon condition, injury, exposed opening
camera and sound: viewpoint that proves the action, plus synchronized impact and motion sound
```

Make each exchange change the next one. A feint must create a defense; a defense must create or deny an opening; a hit must alter balance, position, equipment, stamina, or terrain. Preserve left/right screen direction and handedness.

## Anti-generic rules

- Limit a short clip to the number of exchanges the viewer can actually read. Prefer one well-described exchange over an unbroken flurry.
- Name the concrete action, not a category: `a low left-to-right cut toward the lead thigh` is stronger than `sword attack`.
- Name the result, not only the intention: `the blade catches the scabbard mouth and throws sparks` is stronger than `they clash`.
- Give every strong impact a consequence: a half-step slide, bent guard, dropped elevation, shifted camera framing, torn sleeve, displaced rubble, breath break, or altered weapon line.
- Let camera movement reveal rather than obscure. Use a medium/wide view to establish geometry; use a close detail only for a decisive grip, impact, eye line, seal, or weapon interaction; use shake only at a meaningful impact.
- Do not put several unrelated acrobatics, weapon changes, transformations, and large effects into one short exchange.

## Style selection

Select one primary movement language and one secondary accent. Do not blend all of them by default.

- **Grounded martial arts:** footwork, weight transfer, clinch range, guard recovery, joint line, and impact recoil.
- **Wuxia:** wire-like leaps remain tied to momentum, terrain, weapon reach, and landing; use flowing sleeve, scabbard, or lightness skills sparingly.
- **Xianxia:** use the dedicated rules below.
- **Weapon duel:** establish reach, edge alignment, bind/parry point, grip, and recovery line.
- **Creature or giant fight:** give scale through terrain displacement and a clear target body part; avoid human-speed multi-hit flurries.

## Chinese xianxia combat

Treat xianxia as a rule-bound duel, not generic glowing effects. Before the beat card, establish one technique identity for each combatant:

```text
combatant: cultivation expression / signature implement / tactical preference / visible limitation
```

Examples of distinct technique identities: a narrow, precise flying-sword thread; talismans that require a placed seal; water ribbon control that needs an existing water source; a heavy mountain-style seal with a slow wind-up; a short-range thunder step with a recovery pause. Do not give both fighters unlimited flight, shields, teleportation, and explosions.

For each cultivation exchange, specify this causal chain:

```text
setup or hand seal → energy/implement path → target and countermeasure → visible contact rule → cost, disruption, or changed battlefield state
```

### Spatial rules

- Establish altitude, horizontal separation, and terrain relation before airborne action: for example, one fighter stands on a bridge deck while the other hovers one body length above the riverbank.
- Give flight an entry, direction, stop, and landing/recovery. “Flies around rapidly” is not choreography.
- A flying sword needs a launch point, path, target, deflection or dodge, and where it ends. A talisman needs a throw/placement surface, activation gesture, and readable area of effect.
- Make formations and barriers bounded: state the visible boundary, anchor, weak point, or duration cue. Let a counter exploit one of these constraints.

### Material and force rules

- Describe spiritual power through a specific material behavior: thin frost racing along stone, gold threads tightening around a wrist, ember particles drawn into a seal, rain lifted by sword pressure. Avoid featureless “energy blasts.”
- Give magical clashes a physical outcome: a sword is knocked off-line, a seal cracks, a robe sleeve scorches, a cliff face sheds gravel, a character loses altitude, or a formation ring dims.
- Keep the decisive technique legible: set-up, release, resistance, and aftermath. Reserve large-scale environmental transformation for a climax that the previous beats earn.

### Xianxia camera and sound

- Begin a major aerial or formation exchange with a wide shot that establishes the vertical geography.
- Track a single implement during its decisive path; do not orbit two fast-moving fighters continuously.
- Use a brief slow-motion or close detail only on the seal closing, blade contact, or decisive expression, then return to a view that shows the consequence.
- Describe diegetic sound concretely: silk and robe snap, sword ring, talisman paper crackle, formation hum, stone fracture, wind pressure, breath, and landing impact.

## Final combat review

Before output, verify:

- Every action has a subject, trajectory, target, response, and consequence.
- The final state can become the next clip's opening state.
- The chosen style governs movement and effects.
- The camera can show the spatial relationship at the key moment.
- No generic “fierce battle,” unexplained barrage, or effect-only climax remains.
