window.addEventListener("DOMContentLoaded", () => {
  const text = "./mixerbee";
  const el = document.getElementById("typed-text");

  if (!el) return;

  let i = 0;
  const speed = 100;

  function typeChar() {
    if (i < text.length) {
      el.textContent += text.charAt(i);
      i++;
      setTimeout(typeChar, speed);
    } else {
      setTimeout(() => {
        el.parentElement.classList.add("typing-done");
      }, 300);

      setTimeout(() => {
        const wrapper = el.closest(".typewriter-wrapper");
        if (wrapper) wrapper.classList.add("fade-out");

  // Stop cursor blinking after fade-out starts
      setTimeout(() => {
        el.classList.add("cursor-done");
     }, 1000); // match fadeOutAndCollapse duration
   }, 5000);
      setTimeout(() => {
        const wrapper = el.closest(".typewriter-wrapper");
        if (wrapper) wrapper.classList.add("fade-out");
      }, 5000);
    }
  }

  typeChar();
});

