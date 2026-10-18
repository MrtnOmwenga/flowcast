/**
 * The demo picker: each demo as a row, and under it a card for every room design, with a
 * picture of that design. Designs still being built are shown greyed out as "soon".
 */

interface Card { id: string; name: string; note: string; image: string; soon?: boolean }
interface Group { name: string; about: string; route: string; cards: Card[] }

const GROUPS: Group[] = [
  {
    name: "Cleanroom",
    about: "Particles from machines and people, held to EU GMP or ISO cleanliness limits.",
    route: "#/demos/cleanroom",
    cards: [
      { id: "panels", name: "Ceiling panels", note: "Four supply panels, one return wall", image: "/previews/panels.jpg" },
      { id: "ceiling", name: "Filter ceiling", note: "Air moves straight down, out at both ends", image: "/previews/ceiling.jpg" },
      { id: "cross", name: "Cross-flow", note: "Filter wall to return wall", image: "/previews/cross.jpg" },
    ],
  },
  {
    name: "Control cabinet",
    about: "Heat from drives and power supplies, held under the components' temperature rating.",
    route: "#/demos/cabinet",
    cards: [
      { id: "cabinet", name: "Filter fan", note: "In at the bottom, out at the top", image: "/previews/cabinet.jpg" },
      { id: "roof", name: "Roof fan", note: "Drawn out through the roof", image: "/previews/cabinet.jpg", soon: true },
      { id: "side", name: "Side to side", note: "In one side wall, out the other", image: "/previews/cabinet.jpg", soon: true },
    ],
  },
];

let overlay: HTMLElement | null = null;

export function openDemoPicker(): void {
  if (overlay) return;
  overlay = document.createElement("div");
  overlay.className = "picker-overlay";
  overlay.innerHTML = `
    <div class="picker" role="dialog" aria-modal="true" aria-label="Choose a demo">
      <div class="picker-head">
        <h2>Choose a demo</h2>
        <button class="picker-close" aria-label="Close">×</button>
      </div>
      ${GROUPS.map((g) => `
        <section class="picker-group">
          <h3>${g.name}</h3>
          <p class="muted small">${g.about}</p>
          <div class="picker-cards">
            ${g.cards.map((c) => `
              <a class="picker-card ${c.soon ? "is-soon" : ""}" ${c.soon ? 'aria-disabled="true"' : `href="${g.route}/${c.id}"`}>
                <img src="${c.image}" alt="" loading="lazy" />
                <b>${c.name}${c.soon ? ' <span class="soon">soon</span>' : ""}</b>
                <small>${c.note}</small>
              </a>`).join("")}
          </div>
        </section>`).join("")}
    </div>`;
  document.body.appendChild(overlay);
  overlay.addEventListener("click", (event) => {
    const target = event.target as HTMLElement;
    if (target === overlay || target.closest(".picker-close") || target.closest("a.picker-card[href]")) closeDemoPicker();
  });
  document.addEventListener("keydown", onKey);
}

export function closeDemoPicker(): void {
  overlay?.remove();
  overlay = null;
  document.removeEventListener("keydown", onKey);
}

function onKey(event: KeyboardEvent): void {
  if (event.key === "Escape") closeDemoPicker();
}
