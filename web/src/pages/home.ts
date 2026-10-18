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
        <div><b>${FACTS.rooms}</b><span>rooms simulated in OpenFOAM to train the models</span></div>
        <div><b>${FACTS.sameVerdict}</b><span>of unseen rooms get the same within-limit verdict as a full simulation</span></div>
        <div><b>28%</b><span>less fan power for every 10% less air: power falls with the cube of airflow</span></div>
      </div>
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

    <section class="closing">
      <h2>If you have tuned the fans in a PC case, you already know the problem.</h2>
      <p>Move one fan and every temperature changes, and you only find out by trying. A factory room is the same problem at a larger scale, with a compliance limit attached and a five-figure energy bill. Flowcast is the tool that lets you try the change on screen first.</p>
      <div class="cta">
        <a class="button" href="#/demos/cleanroom">Try the cleanroom</a>
        <a class="button" href="#/demos/cabinet">Try the control cabinet</a>
        <a class="button secondary" href="#/architecture">How it is built</a>
      </div>
    </section>`;
  root.querySelector<HTMLButtonElement>("#see-demos")?.addEventListener("click", () => openDemoPicker());
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
