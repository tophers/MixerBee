window.addEventListener("DOMContentLoaded", () => {
  const text = "./mixerbee";
  const el = document.getElementById("typed-text");
  const overlay = document.getElementById("typewriter-overlay");

  if (!el || !overlay) {
    // If the overlay doesn't exist for some reason, just remove it to be safe.
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
      // Exit sequence
      setTimeout(() => {
        el.parentElement.classList.add("typing-done");

        setTimeout(() => {
          // Add a one-time event listener for when the transition ends
          overlay.addEventListener('transitionend', () => {
            overlay.remove();
          }, { once: true }); // { once: true } automatically cleans up the listener

          // Start the fade-out
          overlay.classList.add("fade-out-overlay");

        }, 1200); // Pause before fading

      }, 100); // Pause after typing
    }
  }

  typeChar();
});
