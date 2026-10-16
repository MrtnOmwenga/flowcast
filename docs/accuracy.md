# Accuracy report

How well Flowcast's predictions match the simulations they stand in for, how well those
simulations match a real experiment, and how often a recommended fan setting is truly safe.
Figures measured 13 to 16 October 2026.

## 1. The model against simulation

Each room design has its own models. Every figure is measured on test rooms the models never
saw during training. Rooms go to the training, validation or test set by a hash of their name,
so the split is fixed and repeatable.

- **Random layouts** place items anywhere.
- **Realistic layouts** put machines against walls, people at the machines they work at, and cabinet components in rows.

| Design | Layouts | Test rooms | Models in ensemble | Worst point: median / 90th percentile error | Air velocity: median error | Age of air: median error | Same within-limit verdict as the simulation | Prediction time |
|---|---|---|---|---|---|---|---|---|
| Cleanroom, ceiling panels | random | 267 | 4 | 8.9% / 25.6% | 13.7% | 6.3% | 92% | 105 ms |
| Cleanroom, ceiling panels | realistic | 105 | 4 | 13.1% / 39.2% | 14.8% | 7.3% | 98% | 129 ms |
| Cleanroom, filter ceiling | random | 194 | 2 | 4.2% / 13.7% | 3.3% | 5.3% | 98% | 53 ms |
| Cleanroom, cross-flow | random | 226 | 2 | 5.8% / 19.0% | 6.3% | 10.0% | 94% | 53 ms |
| Control cabinet | random | 240 | 2 | 9.8% / 23.2% | 12.0% | 9.5% | 94% | 44 ms |
| Control cabinet | realistic | 68 | 2 | 13.0% / 36.7% | 14.7% | 15.3% | 94% | 44 ms |

How the figures are measured:
- **Worst point:** the highest particle level (or temperature rise, in the cabinet) in the zone the limit applies to. This is the number recommendations depend on.
- **Velocity and age of air:** the size of the error over the whole room, relative to the size of the true field.
- **Prediction times:** both networks and every ensemble member, on an AMD Radeon RX 6600 with ROCm.

### Realistic layouts: a weakness found and mostly fixed

The first models were trained on random layouts only. Asked about realistic rooms, they were
about twice as wrong at the worst point:

| Design, realistic test rooms | Worst point, median / 90th percentile | Air velocity | Same verdict |
|---|---|---|---|
| Ceiling panels, before | 17.2% / 38.7% | 16.2% | 95% |
| Ceiling panels, after adding 600 realistic rooms to training | **13.1% / 39.2%** | **14.8%** | **98%** |
| Control cabinet, before | 17.3% / 43.5% | 21.3% | 87% |
| Control cabinet, after adding 400 realistic cabinets to training | **13.0% / 36.7%** | **14.7%** | **94%** |

Accuracy on random rooms did not suffer. Realistic rooms remain harder than random ones, and
the filter-ceiling and cross-flow models have not yet been retrained this way.

## 2. The simulation against a real experiment

The simulation set-up was run on the IEA Annex 20 two-dimensional test room (Nielsen, 1990):
9 m long, 3 m high, air supplied through a slot under the ceiling, with air velocity measured
by laser-Doppler anemometry along four lines. Below is the mean difference from the
measurements, as a share of the supply velocity, along all four lines.

| Cell size | Cells | Mean difference |
|---|---|---|
| 20 cm (the grid Flowcast's training data uses) | 2,700 | 10.0% |
| 10 cm | 10,800 | 7.9% |
| 5 cm | 43,200 | 6.1% |
| 2.4 cm (slots reproduced exactly) | 187,500 | 4.5% |
| 1.2 cm (slots reproduced exactly) | 750,000 | 4.3% |

The difference levels off at about 4%: beyond 2.4 cm the grid no longer matters, and what
remains is the limit of the standard turbulence model. The training grid's 10% is mostly in
the jet under the ceiling, which one cell cannot resolve. Results, chart and measurements are
in `validation/`.

A separate study of 16 rooms simulated at both 20 cm and 10 cm found the two grids differ by
a median of 26% in air velocity and 33% in particle level across the occupied zone, but only
6% in the room's average level. The coarse grid, not the model, is the larger source of error.
A finer training set is the obvious next step.

## 3. Is a recommended setting truly safe?

For 100 unseen layouts, the true lowest safe fan setting was found by real simulation and
compared with the model's recommendation at several safety margins. The model recommends a
setting only if its predicted worst point is at least that margin under the limit.

| Safety margin | Cleanroom: confirmed safe | Cleanroom: no recommendation | Cabinet: confirmed safe | Cabinet: no recommendation |
|---|---|---|---|---|
| 0% | 39% | 0% | 54% | 0% |
| 10% | 70% | 4% | 77% | 0% |
| **15% (used)** | **81%** | **6%** | **86%** | **0%** |
| 20% | 84% | 7% | 92% | 0% |
| 30% | 90% | 12% | 100% | 1% |

These studies used the models in service before the realistic-layout retraining.

Picking the lowest passing setting favours settings where the model happens to be optimistic,
so a margin alone cannot make a recommendation safe at a sensible cost. That is why Flowcast
confirms its answer: the model proposes a setting, a real simulation checks it, and the fan
steps up until a simulation passes.

## 4. What these figures do not cover

- Everything above is measured against simulation, and the simulation against one published experiment, not against a real cleanroom or cabinet.
- Release rates for machines and people, and heat for cabinet components, are assumptions stated on the site. They scale the results but do not affect the figures above.
- People are fixed blocks, the cleanroom has no heat, and the cabinet ignores warm air rising, which is fair only when a fan drives the air.
