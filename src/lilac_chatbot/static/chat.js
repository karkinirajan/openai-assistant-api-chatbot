// The chat page. The reply is asked for at once; the page then waits the pause set in the configuration,
// shows "Typing..." and holds the answer back for a time proportional to its length (the brief of the
// original project: an assistant that answers like a person types).
(() => {
  const form = document.getElementById("chatForm");
  if (!form) return;
  const box = document.getElementById("chatBox");
  const input = document.getElementById("user_query");
  const button = form.querySelector("button");
  const ms = (name) => {
    const value = Number(form.dataset[name]);
    return Number.isFinite(value) && value >= 0 ? value : 0;
  };
  const pauseMs = ms("pauseMs");
  const msPerWord = ms("msPerWord");
  const maxTypingMs = ms("maxTypingMs");
  const sleep = (time) => new Promise((resolve) => setTimeout(resolve, time));

  function add(text, kind) {
    const div = document.createElement("div");
    div.className = kind + "-message";
    div.textContent = text; // never innerHTML: the text comes from users and from a model
    box.appendChild(div);
    box.scrollTop = box.scrollHeight;
    return div;
  }

  async function ask(question) {
    const body = new FormData();
    body.append("user_query", question);
    const response = await fetch(form.dataset.url, {
      method: "POST",
      body,
      headers: { "X-CSRF-Token": form.dataset.csrf },
    });
    const data = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(data.error || "There was an error processing your request.");
    return data.assistant_response;
  }

  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    const question = input.value.trim();
    if (!question || button.disabled) return;
    input.value = "";
    button.disabled = true;
    add(question, "user");
    const answer = ask(question);
    answer.catch(() => {}); // handled below; keeps the browser from reporting it while the pause runs
    let typing = null;
    try {
      await sleep(pauseMs);
      typing = add("Typing...", "typing");
      const text = await answer;
      const words = text.split(/\s+/).filter(Boolean).length;
      await sleep(Math.min(words * msPerWord, maxTypingMs));
      typing.remove();
      typing = null;
      add(text, "assistant");
    } catch (error) {
      if (typing) typing.remove();
      add(error.message, "error");
    } finally {
      button.disabled = false;
      input.focus();
    }
  });
  box.scrollTop = box.scrollHeight;
})();
