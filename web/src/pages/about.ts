import { FACTS } from "../facts";

export function about(): string {
  return `
  <article class="prose">
    <p class="eyebrow">About</p>
    <h1>Flowcast predicts how air moves through a ventilated room, and tells the operator the lowest fan setting that keeps it safe.</h1>

    <h2>The problem</h2>
    <p>Many industrial spaces move air for one reason: to keep something under a limit. In a cleanroom it is airborne particles. In a paint booth it is overspray. In a welding bay it is fume.</p>
    <ul>
      <li><b>The fans are set once, for the worst case, and left there.</b> Nobody on site can predict what happens if they are turned down, so they stay high around the clock.</li>
      <li><b>That is expensive.</b> Air handling is roughly half of a cleanroom facility's energy use, and fan power falls with the cube of airflow: 10% less air is about 28% less fan power.</li>
      <li><b>The tool that could answer the question is out of reach.</b> A flow simulation predicts the air, but each run needs a specialist. So it is done once, at design time, by a consultant.</li>
      <li><b>Then the room changes.</b> Equipment is moved, a machine is added, a shift pattern changes. The original study no longer describes the room, and nobody commissions a new one.</li>
    </ul>
    <p>In software terms this is over-provisioning. The room runs at peak capacity all the time because there is no way to predict the load, like servers before autoscaling.</p>

    <h2>What Flowcast does</h2>
    <ol>
      <li><b>Simulates once, in bulk.</b> ${FACTS.rooms} rooms were simulated in OpenFOAM, each with a different layout and fan setting.</li>
      <li><b>Trains a fast model on the results.</b> Two 3D neural networks learn to predict the airflow, and then each machine's particle field, from the layout. Several copies are trained on an AMD GPU; where the copies disagree, the model is unsure.</li>
      <li><b>Predicts instantly.</b> For a new layout the model answers in a fraction of a second, where the simulation takes ${FACTS.simulationSeconds}.</li>
      <li><b>Searches.</b> Because each answer is instant, it can test every fan setting and report the lowest that keeps the room under its limit.</li>
      <li><b>Checks itself.</b> On request it runs a real simulation of the room as set and compares the result with its own prediction.</li>
    </ol>

    <h2>What the room must meet</h2>
    <p>A room is not judged against a number we chose. It is held to a published standard, and Flowcast works to whichever one you select.</p>
    <table>
      <thead><tr><th>Standard</th><th>Limit in operation</th><th>Limit at rest</th></tr></thead>
      <tbody>
        <tr><td>EU GMP grade C</td><td>3,520,000</td><td>352,000</td></tr>
        <tr><td>EU GMP grade B</td><td>352,000</td><td>3,520</td></tr>
        <tr><td>ISO class 8</td><td colspan="2">3,520,000</td></tr>
        <tr><td>ISO class 7</td><td colspan="2">352,000</td></tr>
        <tr><td>ISO class 6</td><td colspan="2">35,200</td></tr>
      </tbody>
    </table>
    <p>Figures are particles of 0.5 micrometres and larger per cubic metre, from EU GMP Annex 1 (2022), Table 1, and ISO 14644-1. A room is "in operation" while anything is running or anyone is in it, and "at rest" otherwise.</p>
    <ul>
      <li><b>The limit follows the state of the room.</b> A pharmaceutical grade has a looser limit while people are working and a stricter one when the room is empty, and Flowcast applies the right one to each part of the day.</li>
      <li><b>The site sets a floor.</b> No search goes below the site's minimum fan setting.</li>
      <li><b>The fans lead and lag the work.</b> In a day's schedule they come up 20 minutes before staff arrive and stay up for a 20-minute clean-up afterwards, the guidance value Annex 1 gives for returning a room to its at-rest state.</li>
      <li><b>What is not covered:</b> the pressure a room must hold against its neighbours, temperature and humidity, and microbial limits. Flowcast is about airborne particles and the air that carries them.</li>
    </ul>

    <h2>Who it is for</h2>
    <p>The process or facilities engineer responsible for a room, who needs to know before making a change whether the room stays within its limit and what the fans can drop to. The buyer is whoever pays the energy bill and carries the compliance risk.</p>

    <h2>The business case</h2>
    <ul>
      <li><b>A measured saving.</b> In the demo cleanroom, held to EU GMP grade C while staffed, Flowcast recommends 20.25 air changes an hour instead of 30, and a real CFD simulation confirms the room stays within its limit: 64% less fan power. In the demo cabinet the fan can drop from 1,000 to 400 m³/h with every component under its rating: 86% less fan power.</li>
      <li><b>Proven demand.</b> Industry already pays to cut cleanroom air: Roche/Genentech runs an air-change-reduction programme, vendors sell airflow-reduction systems, ISO 14644-16 covers cleanroom energy efficiency, and Lawrence Berkeley National Laboratory measured 60 to 80% fan-energy savings from demand-controlled filtration.</li>
      <li><b>Customers.</b> Pharmaceutical and biotech manufacturing, electronics, hospital pharmacies and laboratories; with the heat version, panel builders and equipment rooms.</li>
      <li><b>Revenue.</b> A subscription per room for daily use: change planning, night setback and fan schedules. Each new room design is set up once, and every design widens the library of rooms Flowcast can model.</li>
    </ul>

    <h2>How it differs from what exists</h2>
    <table>
      <thead><tr><th>Today</th><th>What it does</th><th>What it leaves open</th></tr></thead>
      <tbody>
        <tr><td>Reactive control</td><td>Particle counters in the room drive the fan speed</td><td>Sees only where the counters are, learns a setting is bad after the fact, and needs new hardware</td></tr>
        <tr><td>A consulting study</td><td>A specialist simulates the room once</td><td>One answer for one layout, in weeks, out of date after the next change</td></tr>
        <tr><td>Flowcast</td><td>Predicts the whole room for any layout, before the change is made</td><td>It advises; it does not replace the room's physical tests</td></tr>
      </tbody>
    </table>
    <p>The two approaches fit together. Flowcast marks the worst point in the room for any layout, which is where a reactive system's particle counter belongs.</p>

    <h2>Why it is built this way</h2>
    <table>
      <thead><tr><th>Choice</th><th>Reason</th></tr></thead>
      <tbody>
        <tr><td>A learned model, not a simulation per question</td><td>The engineer needs the answer while deciding, not next week</td></tr>
        <tr><td>Trained on simulations, not plant data</td><td>A simulation can show every layout, including ones that would be unsafe to try in a real room</td></tr>
        <tr><td>Equipment as blocks on a regular grid</td><td>Moving a machine becomes a change of input, so one model covers every layout</td></tr>
        <tr><td>Two networks: airflow first, then particles</td><td>Particles are carried by the air; giving the second network the airflow leaves it a far easier problem</td></tr>
        <tr><td>One particle field per machine</td><td>Particles do not change the airflow, so fields add up exactly and switching a machine needs no new prediction</td></tr>
        <tr><td>Several models, not one</td><td>A wrong answer has consequences, so the tool must show when it is unsure</td></tr>
        <tr><td>It advises and does not control the fans</td><td>A person stays responsible, and no control retrofit is needed</td></tr>
        <tr><td>Open source, on AMD GPUs with ROCm</td><td>A plant can run it on its own hardware and keep its data</td></tr>
      </tbody>
    </table>

    <h2>How accurate it is</h2>
    <p>Measured on ${FACTS.testRooms} simulated cleanrooms the model never saw during training, some laid out at random and some the way real rooms are, with machines against walls and people working at them:</p>
    <ul>
      <li>It gives the same within-limit verdict as the simulation in <b>${FACTS.sameVerdict}</b> of random rooms and <b>${FACTS.sameVerdictRealistic}</b> of realistic ones.</li>
      <li>Its particle level at the worst point is within <b>${FACTS.worstPointError}</b> of the simulation in the median random room, and <b>${FACTS.worstPointErrorRealistic}</b> in the median realistic one.</li>
      <li>Its air velocity field is within <b>${FACTS.velocityError}</b> in the median room.</li>
    </ul>
    <p>The first models were trained on random layouts only, and on realistic rooms they were about twice as wrong at the worst point. Realistic layouts were then simulated and added to training, which closed most of that gap. Where the independently trained models disagree most, the error roughly doubles; those are the rooms the interface marks as low confidence.</p>

    <h2>Checked against a real experiment</h2>
    <p>The model is only as good as the simulations it learns from, so the simulation set-up itself was checked against measurements. The test is the room experiment that the International Energy Agency's Annex 20 adopted as a benchmark in 1990: a room 9 metres long and 3 metres high, with air blown in through a slot under the ceiling and leaving at the floor of the far wall, its air velocity measured by laser along four lines. The same solver, turbulence model and settings that produce Flowcast's training data were run on that room.</p>
    <ul>
      <li>With cells of 2.4 cm, fine enough to resolve the slots, the simulated air velocity differs from the measurements by <b>4.5% of the supply velocity</b> on average along the four lines.</li>
      <li>On 20 cm cells, the grid Flowcast's demonstration rooms are simulated on, the average difference is <b>10%</b>, most of it in the jet under the ceiling, which a single cell cannot resolve.</li>
      <li>The difference falls steadily as the cells get smaller: 10%, 7.9%, 6.1% and 4.5% for 20, 10, 5 and 2.4 cm. Halving the cells once more, to 1.2 cm, gives 4.3%: the grid no longer matters, and what remains is the limit of the turbulence model, the standard one for room airflow.</li>
    </ul>
    <figure class="figure"><img src="/validation-annex20.svg" alt="Measured and simulated air velocity along four lines in the IEA Annex 20 test room, for four grid sizes" loading="lazy" /><figcaption>Red points: laser-Doppler measurements (Nielsen, 1990, published by Aalborg University). Lines: Flowcast's simulation set-up on five grids.</figcaption></figure>
    <p>So the set-up reproduces a real room well when the grid is fine, and the coarse demonstration grid is the larger source of error, as the grid study also found. A finer training set is the obvious next step.</p>

    <h2>What it is not</h2>
    <ul>
      <li>It is a screening and planning tool. It does not replace the physical tests a regulated room must pass.</li>
      <li>The model is validated against simulation, and the simulation set-up against a published room experiment, not against a real cleanroom.</li>
      <li>It is valid only for the kind of room it was trained on. Each room design shown has its own trained models; a new kind of room needs new simulations and training.</li>
      <li>The demonstration room is simplified, and its simulations use a coarse grid of 0.2 metre cells.</li>
      <li>Fan power uses the standard cube law, which is an idealisation of real fans.</li>
    </ul>

    <h2>The second demo: a control cabinet</h2>
    <p>A fan-cooled control cabinet is the same problem with heat in place of particles. A filter fan blows air in at the bottom, drives, power supplies and transformers give off their losses as heat, and the air around every component must stay under the temperature the components are rated for. The question is again the lowest fan setting that keeps everything within the limit, and where each component should go.</p>
    <ul>
      <li><b>The same pipeline, a different room.</b> The cabinet was simulated with the same OpenFOAM set-up and the same two networks were trained on it; only the room, the openings and the readouts changed.</li>
      <li><b>Heat travels like particles here.</b> The fan moves heat much faster than warm air rises, so each component's heat is carried as a tracer and the temperatures add up, exactly as particle levels do. This holds for fan-cooled cabinets, not for cabinets cooled by natural draught.</li>
      <li><b>The heat figures are typical losses, not measurements.</b> A 4 kW drive is taken to give off 120 W, a 15 kW drive 400 W, and so on; the page lists them. A datasheet would replace them.</li>
      <li><b>How accurate it is.</b> On cabinets it never saw, the hottest air is within 10% of the simulation in the median cabinet laid out at random, and within 13% in the median cabinet laid out the way panel builders do. It gives the same verdict on the rating in 94% of both. A prediction takes about a tenth of a second.</li>
      <li><b>Why it matters.</b> A cabinet fan that runs slower draws less dust through its filter, makes less noise and lasts longer. Placement matters more: a drive mounted below another heats the air the second one breathes.</li>
    </ul>

    <h2>Where it goes next</h2>
    <p>The same method applies to any enclosed space where fans move air past obstacles to keep one quantity under a limit: hospital operating theatres and isolation rooms, laboratories, welding bays, battery dry rooms and poultry houses. With heat carried as in the cabinet, it extends to server chassis, PC cases and other electronics enclosures; data halls and cold stores, where warm air rising matters, need the heat to drive the air as well.</p>

    <p class="cta"><a class="button" href="#/demos/cleanroom">Open the cleanroom demo</a> <a class="button" href="#/demos/cabinet">Open the cabinet demo</a> <a class="button secondary" href="#/architecture">How it is built</a></p>
  </article>`;
}
