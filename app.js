const header = document.querySelector(".site-header");
const nav = document.querySelector("#site-nav");
const navToggle = document.querySelector(".nav-toggle");
const content = document.querySelector("#source-content");
const progressBar = document.querySelector(".reading-rail__bar");

async function loadContent() {
  try {
    const response = await fetch("content.html", { cache: "no-cache" });
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    content.innerHTML = await response.text();
    watchSections();
  } catch (error) {
    content.innerHTML = `
      <p class="error-message">
        The mirrored content could not be loaded. Please try again shortly.
      </p>`;
    console.error("Content load failed", error);
  }
}

function watchSections() {
  const navigationLinks = [...nav.querySelectorAll("a[href^='#']")];
  const sectionMap = new Map(
    navigationLinks.map((link) => [link.getAttribute("href").slice(1), link]),
  );
  const headings = [...content.querySelectorAll("h2[id]")].filter((heading) => sectionMap.has(heading.id));
  if (!("IntersectionObserver" in window)) return;

  const observer = new IntersectionObserver(
    (entries) => {
      const visible = entries.find((entry) => entry.isIntersecting);
      if (!visible) return;
      navigationLinks.forEach((link) => link.classList.remove("is-active"));
      sectionMap.get(visible.target.id)?.classList.add("is-active");
    },
    { rootMargin: "-20% 0px -70%", threshold: 0 },
  );
  headings.forEach((heading) => observer.observe(heading));
}

function updateScrollState() {
  header.classList.toggle("is-scrolled", window.scrollY > 8);
  const scrollable = document.documentElement.scrollHeight - window.innerHeight;
  const progress = scrollable > 0 ? (window.scrollY / scrollable) * 100 : 0;
  progressBar.style.height = `${Math.min(100, Math.max(0, progress))}%`;
}

navToggle.addEventListener("click", () => {
  const isOpen = nav.classList.toggle("is-open");
  navToggle.setAttribute("aria-expanded", String(isOpen));
});

nav.addEventListener("click", (event) => {
  if (event.target.closest("a")) {
    nav.classList.remove("is-open");
    navToggle.setAttribute("aria-expanded", "false");
  }
});

window.addEventListener("scroll", updateScrollState, { passive: true });
updateScrollState();
loadContent();
