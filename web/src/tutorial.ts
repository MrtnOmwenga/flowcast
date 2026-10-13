/**
 * A short guided tour of the demo. Each step dims the page, leaves one control lit, and
 * puts a note beside it with an arrow pointing at it.
 */

interface Step {
  target: string; // "view" for the 3D room, otherwise a selector on the demo page
  task?: "explore" | "optimise" | "plan" | "confirm"; // the panel tab that must be open first
  title: string;
  body: string;
}

const STEPS: Step[] = [
  {
    target: "view",
    title: "The room",
    body: "You are looking into a small cleanroom. Clean air comes in through the four blue ceiling panels and leaves through the grey grille low on one end wall. The moving dots follow the predicted airflow and turn from blue to red where the particle level is high. Drag the background to orbit and scroll to zoom. Drag a machine or a person to move it: each move is sent to the model, which returns the whole room's air in about a tenth of a second.",
  },
  {
    target: '[data-tour="readouts"]',
    title: "The room now",
    body: "The headline says whether the worst point in the room is within its particle limit. Amber means too close to call. The saving is against the fan setting the room runs at today. Confidence drops when four independently trained models disagree about this layout.",
  },
  {
    target: '[data-tour="tasks"]',
    title: "Three ways to work",
    body: "Explore changes the room by hand. Optimise lets Flowcast search for the best setting or position. Plan a day turns a production plan into a fan schedule. Confirm checks an answer against a real simulation.",
  },
  {
    target: '[data-tour="fan"]',
    task: "explore",
    title: "The fan setting",
    body: "This is how much air the fans supply, in room volumes an hour. Fan power falls with roughly the cube of airflow, so a little less air saves a lot, but particles build up. Slide it down and watch the worst point climb towards the limit.",
  },
  {
    target: '[data-tour="equipment"]',
    task: "explore",
    title: "What is in the room",
    body: "Switch a machine off or send a person away and the picture updates at once, with nothing recomputed. Particles do not change the airflow, so each source's particle field is predicted separately and they are simply added up. Adding, turning or moving an item does change the airflow, so those ask the model again.",
  },
  {
    target: '[data-tour="optimise"]',
    task: "optimise",
    title: "Let it search",
    body: "Finding the lowest safe fan setting takes about eight predictions. Finding the best place for an item takes about sixty, one for each position tried. A flow simulation needs about a minute for each of those; the model does the whole search in seconds.",
  },
  {
    target: '[data-tour="plan"]',
    task: "plan",
    title: "Plan a day",
    body: "This is the everyday use. Paste the day's production plan as you would write it for a colleague. A language model on AMD GPUs works out who is in the room and what is running in each part of the day, and the airflow model finds the lowest safe fan setting for each. The result is a fan schedule and its energy against running flat out all day.",
  },
  {
    target: '[data-tour="verify"]',
    task: "confirm",
    title: "Check the model",
    body: "A prediction is a model's estimate. This runs a real OpenFOAM simulation of the room exactly as you have set it and compares the two. If they disagree, the page says so and withdraws the recommendation.",
  },
  {
    target: '[data-tour="ask"]',
    title: "Or just ask",
    body: "Describe what you want in plain words. A language model served on AMD GPUs plans the steps and carries them out with the same tools you have just seen, then reports what it did. Every figure in its answer comes from the airflow model, not from the language model.",
  },
];

let overlay: HTMLElement | null = null;

export function startTutorial(root: HTMLElement, view: HTMLElement, setTask: (task: "explore" | "optimise" | "plan" | "confirm") => void): void {
  stop();
  overlay = document.createElement("div");
  overlay.className = "tour";
  overlay.innerHTML = `<div class="tour-hole"></div><div class="tour-card"><div class="tour-arrow"></div><div class="tour-body"></div></div>`;
  document.body.appendChild(overlay);
  let index = 0;

  const show = (): void => {
    if (!overlay) return;
    const step = STEPS[index];
    if (step.task) setTask(step.task);
    const target = step.target === "view" ? view : root.querySelector<HTMLElement>(step.target);
    if (!target) return next();
    if (step.target !== "view") target.scrollIntoView({ block: "nearest" });
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
