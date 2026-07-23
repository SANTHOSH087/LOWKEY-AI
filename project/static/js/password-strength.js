(function () {
  function scorePassword(pw) {
    if (!pw) return { score: 0, label: "" };
    const rules = [
      /.{8,}/,      // length
      /[A-Z]/,      // uppercase
      /[a-z]/,      // lowercase
      /\d/,         // number
      /[^A-Za-z0-9]/, // special char
    ];
    const passed = rules.filter((r) => r.test(pw)).length;
    const labels = ["Very weak", "Weak", "Fair", "Good", "Strong"];
    return { score: passed, label: labels[Math.max(passed - 1, 0)] };
  }

  function attach(input) {
    const bar = document.getElementById("pwStrengthBar");
    const fill = document.getElementById("pwStrengthFill");
    const label = document.getElementById("pwStrengthLabel");
    if (!bar || !fill || !label) return;

    input.addEventListener("input", () => {
      const pw = input.value;
      if (!pw) {
        bar.style.display = "none";
        label.textContent = "";
        return;
      }
      bar.style.display = "block";
      const { score, label: text } = scorePassword(pw);
      const pct = (score / 5) * 100;
      fill.style.width = pct + "%";
      const colors = ["#ef5675", "#ef5675", "#d79f2c", "#3fa3ff", "#26b285"];
      fill.style.background = colors[Math.max(score - 1, 0)];
      label.textContent = text;
      label.style.color = colors[Math.max(score - 1, 0)];
    });
  }

  document.addEventListener("DOMContentLoaded", () => {
    // Targets whichever password field is present on this page — register
    // form uses id="password", the profile change-password form uses
    // id="new_password", reset-password form uses id="password".
    const candidate = document.getElementById("password") || document.getElementById("new_password");
    if (candidate) attach(candidate);
  });
})();
