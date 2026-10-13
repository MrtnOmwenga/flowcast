import "./style.css";
import { FACTS, LOGO } from "./facts";
import { about } from "./pages/about";
import { architecture } from "./pages/architecture";
import { home, stopHome } from "./pages/home";

type Demo = typeof import("./demo");

const header = document.querySelector<HTMLElement>("#header")!;
const main = document.querySelector<HTMLElement>("#main")!;
const page = document.createElement("div");
page.id = "page";
const demoRoot = document.createElement("div");
demoRoot.id = "demo";
demoRoot.hidden = true;
main.append(page, demoRoot);

const DEMOS = [
  { route: "#/demos/cleanroom", name: "Cleanroom", note: "Particle control in a small cleanroom" },
  { route: "#/demos/cabinet", name: "Control cabinet", note: "Component temperatures in a fan-cooled cabinet" },
];
let demo: Demo | null = null;

header.innerHTML = `
  <a class="brand" href="#/">${LOGO}<span>Flowcast</span></a>
  <nav>
    <div class="menu">
      <button class="navlink" id="demos-button" aria-haspopup="true" aria-expanded="false">Demos <span class="caret">▾</span></button>
      <div class="dropdown" id="demos-menu" hidden>
        ${DEMOS.map((d) => `<a href="${d.route}"><b>${d.name}</b><small>${d.note}</small></a>`).join("")}
      </div>
    </div>
    <a class="navlink" href="#/architecture">Architecture</a>
    <a class="navlink" href="#/about">About</a>
  </nav>
  <a class="navlink source" href="${FACTS.repository}" target="_blank" rel="noopener">GitHub</a>`;

const button = header.querySelector<HTMLButtonElement>("#demos-button")!;
const menu = header.querySelector<HTMLElement>("#demos-menu")!;
function setMenu(open: boolean): void {
  menu.hidden = !open;
  button.setAttribute("aria-expanded", String(open));
}
button.addEventListener("click", (event) => {
  event.stopPropagation();
  setMenu(menu.hidden);
});
document.addEventListener("click", () => setMenu(false));
document.addEventListener("keydown", (event) => {
  if (event.key === "Escape") setMenu(false);
});

async function route(): Promise<void> {
  const hash = location.hash || "#/";
  setMenu(false);
  const isDemo = hash.startsWith("#/demos");
  stopHome();
  page.hidden = isDemo;
  demoRoot.hidden = !isDemo;
  header.querySelectorAll<HTMLElement>(".navlink").forEach((link) => {
    const target = link.getAttribute("href") ?? (link.id === "demos-button" ? "#/demos" : "");
    link.classList.toggle("active", target !== "" && target !== FACTS.repository && hash.startsWith(target));
  });
  if (isDemo) {
    demo ??= await import("./demo");
    demo.mount(demoRoot, hash.startsWith("#/demos/cabinet") ? "cabinet" : "cleanroom");
    demo.setActive(true);
    return;
  }
  demo?.setActive(false);
  window.scrollTo(0, 0);
  if (hash.startsWith("#/architecture")) page.innerHTML = architecture();
  else if (hash.startsWith("#/about")) page.innerHTML = about();
  else home(page);
}

window.addEventListener("hashchange", () => void route());
void route();
