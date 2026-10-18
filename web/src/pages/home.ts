import { openDemoPicker } from "../picker";
import { FACTS } from "../facts";

let frame = 0;

export function stopHome(): void {
  cancelAnimationFrame(frame);
}

export function home(root: HTMLElement): void {
  root.innerHTML = `
    <section class="hero">
      <canvas id="flow" aria-hidden="true"></canvas>
      <div class="hero-text">
        <h1>Cut ventilation energy by up to half.</h1>
        <p class="tagline">A neural CFD surrogate predicts airflow in real time on a digital twin of your room, powered by AMD.</p>
        <p class="lead">Cleanrooms and control cabinets run their fans at worst case because predicting what a lower setting does takes a specialist and a CFD study. Flowcast, trained on 7,500 OpenFOAM simulations, finds the lowest fan setting that still keeps the room within its limit, in seconds, and checks its answer with a real simulation.</p>
        <div class="cta">
          <button class="button" id="see-demos">See the demos</button>
          <a class="button secondary" href="#/about">What it is and why</a>
        </div>
      </div>
    </section>

    <section class="band">
      <div class="stats">
        <div><b>64%</b><span>less fan power in the demo cleanroom, with the recommended setting confirmed by a real CFD simulation</span></div>
        <div><b>92–98%</b><span>of unseen rooms get the same within-limit verdict as a full simulation</span></div>
        <div><b>4.3%</b><span>from laser-measured air velocity in a published laboratory experiment (IEA Annex 20)</span></div>
      </div>
    </section>

    <section class="section-head">
      <p class="eyebrow">Intelligent Industry</p>
      <h2>Built for the plant floor</h2>
      <p>The people who run cleanrooms and control panels get answers that used to need a CFD specialist, from data they already have: the layout, the equipment, the production plan and the standard the room must meet.</p>
    </section>
    <section class="cards cards-4">
      <article>
        <h3>Use energy efficiently</h3>
        <p>Find the lowest fan setting that still meets the limit. Fan power falls with the cube of airflow: 20% less air, about half the power.</p>
      </article>
      <article>
        <h3>Protect product quality</h3>
        <p>Hold the room to EU GMP Annex 1 or ISO 14644-1, staffed and empty, and see where particles gather before a machine is moved.</p>
      </article>
      <article>
        <h3>Prevent downtime</h3>
        <p>In a control cabinet, keep every drive and power supply under its temperature rating, and place components so none breathes another's heat.</p>
      </article>
      <article>
        <h3>Alert, explain, recommend, act</h3>
        <p>Over-limit alerts, a plain-language explanation from Gemma 4, a recommended setting or position, and a day's fan schedule from the production plan.</p>
      </article>
    </section>

    <section class="cards">
      <article>
        <h3>Predict</h3>
        <p>Drag a machine across the room and the airflow and particle levels redraw as you move it. A flow simulation of the same change takes ${FACTS.simulationSeconds}; a study by a consultant takes weeks.</p>
      </article>
      <article>
        <h3>Recommend</h3>
        <p>One button searches the fan settings for the lowest that keeps the worst point in the room under its limit, and shows the energy and money that saves.</p>
      </article>
      <article>
        <h3>Verify</h3>
        <p>Every answer comes with a confidence reading. When it matters, the page runs a real simulation of the room as you set it and tells you plainly if the model was wrong.</p>
      </article>
    </section>

    <section class="section-head">
      <p class="eyebrow">Powered by AMD</p>
      <h2>AMD hardware at every step</h2>
    </section>
    <section class="cards">
      <article>
        <h3>AMD Radeon GPU with ROCm</h3>
        <p>Trains every neural network on ${FACTS.rooms} OpenFOAM simulations, and answers each prediction in about a tenth of a second.</p>
      </article>
      <article>
        <h3>AMD Instinct via Token Factory</h3>
        <p>Runs Gemma 4, the agent that turns plain-language requests and production plans into actions Flowcast carries out.</p>
      </article>
      <article>
        <h3>AMD EPYC in the cloud</h3>
        <p>Serves the public demo around the clock. Every prediction on the page names the hardware that answered it.</p>
      </article>
    </section>

    <section class="closing">
      <h2>If you have tuned the fans in a PC case, you already know the problem.</h2>
      <p>Move one fan and every temperature changes, and you only find out by trying. A factory room is the same problem at a larger scale, with a compliance limit attached and a five-figure energy bill. Flowcast is the tool that lets you try the change on screen first.</p>
      <div class="cta">
        <button class="button" id="see-demos-2">See the demos</button>
        <a class="button secondary" href="#/architecture">How it is built</a>
        <a class="button secondary" href="#/about">Accuracy and evidence</a>
      </div>
    </section>`;
  root.querySelectorAll<HTMLButtonElement>("#see-demos, #see-demos-2").forEach((button) => button.addEventListener("click", () => openDemoPicker()));
  animate(root.querySelector<HTMLCanvasElement>("#flow")!);
}

/** Streaks drifting along a smooth, swirling flow: decoration only, not a simulation. */
function animate(canvas: HTMLCanvasElement): void {
  const context = canvas.getContext("2d")!;
  const count = 900;
  const points = new Float32Array(count * 3);
  let width = 0;
  let height = 0;
  const resize = (): void => {
    const ratio = Math.min(window.devicePixelRatio, 2);
    width = canvas.clientWidth;
    height = canvas.clientHeight;
    canvas.width = width * ratio;
    canvas.height = height * ratio;
    context.setTransform(ratio, 0, 0, ratio, 0, 0);
  };
  const reset = (i: number, anywhere: boolean): void => {
    points[i * 3] = anywhere ? Math.random() * width : -10;
    points[i * 3 + 1] = Math.random() * height;
    points[i * 3 + 2] = Math.random();
  };
  resize();
  for (let i = 0; i < count; i++) reset(i, true);
  new ResizeObserver(resize).observe(canvas);

  let time = 0;
  const step = (): void => {
    if (!canvas.isConnected) return;
    time += 0.004;
    context.fillStyle = "rgba(244, 247, 250, 0.12)";
    context.fillRect(0, 0, width, height);
    context.lineWidth = 1.3;
    for (let i = 0; i < count; i++) {
      const x = points[i * 3];
      const y = points[i * 3 + 1];
      const tone = points[i * 3 + 2];
      const angle =
        0.9 * Math.sin(x * 0.006 + time) * Math.cos(y * 0.008 - time * 0.7) + 0.5 * Math.sin((x + y) * 0.004 + time * 1.3);
      const speed = 1.2 + tone * 1.6;
      const nx = x + Math.cos(angle) * speed;
      const ny = y + Math.sin(angle) * speed;
      context.strokeStyle = tone > 0.5 ? "rgba(31, 122, 224, 0.5)" : "rgba(18, 160, 106, 0.45)";
      context.beginPath();
      context.moveTo(x, y);
      context.lineTo(nx, ny);
      context.stroke();
      points[i * 3] = nx;
      points[i * 3 + 1] = ny;
      if (nx > width + 10 || ny < -10 || ny > height + 10) reset(i, false);
    }
    frame = requestAnimationFrame(step);
  };
  frame = requestAnimationFrame(step);
}
