gsap.registerPlugin(ScrollTrigger);

const revealTargets = gsap.utils.toArray(".reveal");

revealTargets.forEach((element) => {
  gsap.to(element, {
    opacity: 1,
    y: 0,
    duration: 0.9,
    ease: "power3.out",
    scrollTrigger: {
      trigger: element,
      start: "top 82%",
      once: true,
    },
  });
});

gsap.to(".hero-copy", {
  y: 0,
  opacity: 1,
  duration: 1,
  ease: "power3.out",
});

gsap.to(".hero-panel", {
  y: 0,
  opacity: 1,
  duration: 1,
  delay: 0.15,
  ease: "power3.out",
});

gsap.to(".page-progress", {
  width: "100%",
  ease: "none",
  scrollTrigger: {
    trigger: document.body,
    start: "top top",
    end: "bottom bottom",
    scrub: true,
  },
});

gsap.to(".hero-panel", {
  yPercent: -6,
  ease: "none",
  scrollTrigger: {
    trigger: ".hero",
    start: "top top",
    end: "bottom top",
    scrub: true,
  },
});
