window.addEventListener("DOMContentLoaded", () => {
  const overlay = document.getElementById("typewriter-overlay");

  if (localStorage.getItem('mixerbeeIntroSeen')) {
    if (overlay) {
      overlay.remove();
    }
    return; // Stop execution if intro has been seen
  }

  const text = "./mixerbee";
  const el = document.getElementById("typed-text");

  if (!el || !overlay) {
    if (overlay) overlay.remove();
    return;
  }

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

        setTimeout(() => {
          overlay.addEventListener('transitionend', () => {
            localStorage.setItem('mixerbeeIntroSeen', 'true');
            overlay.remove();
          }, { once: true });

          overlay.classList.add("fade-out-overlay");

        }, 1200);

      }, 100);
    }
  }

  typeChar();
});
