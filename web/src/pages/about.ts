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

    <h2>Who it is for</h2>
    <p>The process or facilities engineer responsible for a room, who needs to know before making a change whether the room stays within its limit and what the fans can drop to. The buyer is whoever pays the energy bill and carries the compliance risk.</p>

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
    <p>Measured on ${FACTS.testRooms} simulated rooms the model never saw during training:</p>
    <ul>
      <li>It gives the same within-limit verdict as the simulation in <b>${FACTS.sameVerdict}</b> of rooms.</li>
      <li>Its particle level at the worst point is within <b>${FACTS.worstPointError}</b> of the simulation in the median room.</li>
      <li>Its air velocity field is within <b>${FACTS.velocityError}</b> in the median room.</li>
    </ul>
    <p>Where the independently trained models disagree most, the error roughly doubles. Those are the rooms the interface marks as low confidence.</p>

    <h2>What it is not</h2>
    <ul>
      <li>It is a screening and planning tool. It does not replace the physical tests a regulated room must pass.</li>
      <li>It is validated against simulation, not against a real cleanroom.</li>
      <li>It is valid only for the kind of room it was trained on. A new kind of room needs new simulations and training.</li>
      <li>The demonstration room is simplified, and its simulations use a coarse grid of 0.2 metre cells.</li>
      <li>Fan power uses the standard cube law, which is an idealisation of real fans.</li>
    </ul>

    <h2>Where it goes next</h2>
    <p>The same method applies to any enclosed space where fans move air past obstacles to keep one quantity under a limit: hospital operating theatres and isolation rooms, laboratories, welding bays, battery dry rooms and poultry houses. Adding heat to the model opens data halls, factory control cabinets and electronics enclosures.</p>

    <p class="cta"><a class="button" href="#/demos/cleanroom">Open the cleanroom demo</a> <a class="button secondary" href="#/architecture">How it is built</a></p>
  </article>`;
}
