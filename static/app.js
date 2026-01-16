document.addEventListener("DOMContentLoaded", () => {
  const form = document.getElementById("ticket-form");
  const resultSection = document.getElementById("triage-result");
  const resultPre = document.getElementById("triage-json");

  if (!form) {
    return;
  }

  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    const title = form.title.value.trim();
    const description = form.description.value.trim();

    const response = await fetch("/api/triage", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ title, description }),
    });

    const data = await response.json();
    if (!response.ok) {
      alert(data.error || "Request failed");
      return;
    }

    resultPre.textContent = JSON.stringify(data.triage, null, 2);
    resultSection.hidden = false;
  });
});
