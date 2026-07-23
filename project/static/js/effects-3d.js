(function () {
  "use strict";

  const prefersReducedMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  const isTouchOrSmall = window.matchMedia("(hover: none), (max-width: 720px)").matches;
  const tiltDisabled = prefersReducedMotion || isTouchOrSmall;

  // ---------------- mouse-move card tilt ----------------
  // Skips anything marked .no-tilt (generic opt-out, unused today) and is
  // disabled entirely on touch devices / small screens / reduced-motion.
  function initCardTilt() {
    if (tiltDisabled) return;

    const selector = ".glass.card:not(.no-tilt), .stat-card:not(.no-tilt), .form-card:not(.no-tilt), .chat-shell:not(.no-tilt)";
    const cards = Array.from(document.querySelectorAll(selector));

    cards.forEach((card) => {
      let frame = null;

      card.addEventListener("mousemove", (e) => {
        if (frame) cancelAnimationFrame(frame);
        frame = requestAnimationFrame(() => {
          const rect = card.getBoundingClientRect();
          const px = (e.clientX - rect.left) / rect.width; // 0..1
          const py = (e.clientY - rect.top) / rect.height;  // 0..1
          const maxDeg = 8;
          const rotateY = (px - 0.5) * maxDeg * 2;
          const rotateX = (0.5 - py) * maxDeg * 2;
          card.style.transform =
            `perspective(900px) rotateX(${rotateX.toFixed(2)}deg) rotateY(${rotateY.toFixed(2)}deg) translateZ(10px)`;
        });
      });

      card.addEventListener("mouseleave", () => {
        if (frame) cancelAnimationFrame(frame);
        card.style.transform = "";
      });
    });
  }

  // ---------------- modal 3D pop-in ----------------
  // Wraps the existing show/hide pattern (inline style.display toggling)
  // used by settings.html's delete-account modal, without changing that
  // behavior — just adds the entrance animation class at the same time.
  window.open3DModal = function (id) {
    const el = document.getElementById(id);
    if (!el) return;
    el.style.display = "flex";
    const card = el.querySelector(".glass");
    if (card && !tiltDisabled) {
      card.classList.remove("modal-3d-open");
      // force reflow so the animation restarts if reopened
      void card.offsetWidth;
      card.classList.add("modal-3d-open");
    }
  };

  window.close3DModal = function (id) {
    const el = document.getElementById(id);
    if (!el) return;
    el.style.display = "none";
  };

  // ---------------- page-enter depth transition ----------------
  function initPageTransition() {
    if (prefersReducedMotion) return;
    document.body.classList.add("page-enter");
    // Only needed once on load — remove after the animation would have
    // finished so it doesn't replay on unrelated later DOM changes.
    window.setTimeout(() => document.body.classList.remove("page-enter"), 700);
  }

  document.addEventListener("DOMContentLoaded", () => {
    initCardTilt();
    initPageTransition();
  });
})();
