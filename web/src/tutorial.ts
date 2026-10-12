/**
 * A short guided tour of the demo. Each step dims the page, leaves one control lit, and
 * puts a note beside it with an arrow pointing at it.
 */

interface Step {
  target: string; // "view" for the 3D room, otherwise a selector inside the panel
  title: string;
  body: string;
}

const STEPS: Step[] = [
  {
    target: "view",
    title: "The room",
    body: "You are looking into a small cleanroom. Clean air comes in through the four blue ceiling panels and leaves through the grey grille low on one end wall. The moving dots follow the predicted airflow and turn from blue to red where the particle level is high. Drag the background to orbit, scroll to zoom.",
  },
  {
    target: "view",
    title: "Move a machine",
    body: "Drag any machine across the floor. Each move sends the new layout to the model, which returns the whole room's airflow and particle field, so the picture follows your hand. A flow simulation of the same change takes about a minute.",
  },
  {
    target: '[data-tour="equipment"]',
    title: "Switch machines on and off",
    body: "A running machine releases particles; one that is off does not. Switching is instant because nothing is recomputed: particles do not change the airflow, so each machine's particle field is predicted separately and they are simply added up.",
  },
  {
    target: '[data-tour="fan"]',
    title: "The fan setting",
    body: "This is how much air the fans supply, in room volumes an hour. Less air costs far less to move, since fan power falls with the cube of airflow, but particles build up. The button searches the settings for the lowest one that keeps the room under its limit with a margin to spare.",
  },
  {
    target: '[data-tour="readouts"]',
    title: "The answer",
    body: "The headline says whether the worst point in the room is within the particle limit. Amber means the prediction is too close to the limit to call. Model confidence drops when several independently trained models disagree about this layout, which is the cue to check it.",
  },
  {
    target: '[data-tour="view"]',
    title: "What the slice shows",
    body: "The coloured sheet is a horizontal cut through the room. It can show the particle level or where the air is stagnant, and the slider moves it up and down. The red marker stays on the worst point, which is where a particle counter would be most useful.",
  },
  {
    target: '[data-tour="verify"]',
    title: "Check the model",
    body: "A prediction is a model's estimate. This button runs a real OpenFOAM simulation of the room exactly as you have set it and compares the two. If they disagree, the page says so and withdraws the recommendation.",
  },
];

let overlay: HTMLElement | null = null;

export function startTutorial(view: HTMLElement, panel: HTMLElement): void {
  stop();
  overlay = document.createElement("div");
  overlay.className = "tour";
  overlay.innerHTML = `<div class="tour-hole"></div><div class="tour-card"><div class="tour-arrow"></div><div class="tour-body"></div></div>`;
  document.body.appendChild(overlay);
  let index = 0;

  const show = (): void => {
    if (!overlay) return;
    const step = STEPS[index];
    const target = step.target === "view" ? view : panel.querySelector<HTMLElement>(step.target);
    if (!target) return next();
    if (step.target !== "view") target.scrollIntoView({ block: "center" });
    const rect = target.getBoundingClientRect();
    const inset = step.target === "view" ? 14 : -6;
    const hole = overlay.querySelector<HTMLElement>(".tour-hole")!;
    hole.style.left = `${rect.left + inset}px`;
    hole.style.top = `${rect.top + inset}px`;
    hole.style.width = `${rect.width - 2 * inset}px`;
    hole.style.height = `${rect.height - 2 * inset}px`;

    const card = overlay.querySelector<HTMLElement>(".tour-card")!;
    overlay.querySelector<HTMLElement>(".tour-body")!.innerHTML = `
      <div class="tour-count">${index + 1} of ${STEPS.length}</div>
      <h3>${step.title}</h3>
      <p>${step.body}</p>
      <div class="tour-actions">
        <button class="link" data-act="skip">Skip</button>
        <span>
          ${index > 0 ? `<button class="ghost" data-act="back">Back</button>` : ""}
          <button data-act="next">${index === STEPS.length - 1 ? "Done" : "Next"}</button>
        </span>
      </div>`;
    const width = Math.min(340, window.innerWidth - 24);
    card.style.width = `${width}px`;
    const arrow = overlay.querySelector<HTMLElement>(".tour-arrow")!;
    const height = card.offsetHeight;
    if (step.target === "view") {
      // Sit inside the room view, at its lower left, pointing up into it.
      card.style.left = `${rect.left + 32}px`;
      card.style.top = `${Math.max(rect.top + 32, rect.bottom - height - 32)}px`;
      arrow.className = "tour-arrow none";
    } else if (rect.left - width - 24 > 0) {
      // Sit to the left of the control, with the arrow pointing right at it.
      const top = Math.min(Math.max(12, rect.top + rect.height / 2 - height / 2), window.innerHeight - height - 12);
      card.style.left = `${rect.left - width - 22}px`;
      card.style.top = `${top}px`;
      arrow.className = "tour-arrow right";
      arrow.style.top = `${Math.min(Math.max(18, rect.top + rect.height / 2 - top - 9), height - 36)}px`;
    } else {
      // Narrow screens: sit above the control, pointing down.
      card.style.left = `${Math.max(12, (window.innerWidth - width) / 2)}px`;
      card.style.top = `${Math.max(12, rect.top - height - 18)}px`;
      arrow.className = "tour-arrow down";
      arrow.style.top = "";
    }
    card.querySelectorAll<HTMLButtonElement>("[data-act]").forEach((b) =>
      b.addEventListener("click", () => (b.dataset.act === "next" ? next() : b.dataset.act === "back" ? back() : stop())),
    );
  };
  const next = (): void => {
    index += 1;
    if (index >= STEPS.length) stop();
    else show();
  };
  const back = (): void => {
    index = Math.max(0, index - 1);
    show();
  };
  const onResize = (): void => show();
  const onKey = (event: KeyboardEvent): void => {
    if (event.key === "Escape") stop();
    if (event.key === "ArrowRight") next();
    if (event.key === "ArrowLeft") back();
  };
  window.addEventListener("resize", onResize);
  window.addEventListener("keydown", onKey);
  cleanup = () => {
    window.removeEventListener("resize", onResize);
    window.removeEventListener("keydown", onKey);
  };
  show();
}

let cleanup: (() => void) | null = null;

function stop(): void {
  cleanup?.();
  cleanup = null;
  overlay?.remove();
  overlay = null;
}
