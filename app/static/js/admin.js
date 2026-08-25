/* Админка. Тоже только вызовы /api/v1/admin/*. */

(function () {
  "use strict";

  const API = "/api/v1";

  function cookie(name) {
    const found = document.cookie.split("; ").find((c) => c.startsWith(name + "="));
    return found ? decodeURIComponent(found.slice(name.length + 1)) : "";
  }

  async function api(method, path, payload) {
    const options = {
      method,
      headers: { "X-CSRF-Token": cookie("chitkod_csrf") },
      credentials: "same-origin",
    };
    if (payload !== undefined) {
      options.headers["Content-Type"] = "application/json";
      options.body = JSON.stringify(payload);
    }
    const response = await fetch(API + path, options);
    const data = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error((data.error && data.error.message) || "Ошибка");
    return data;
  }

  function note(message, kind) {
    const box = document.getElementById("toasts");
    const node = document.createElement("div");
    node.className = "toast toast--" + (kind || "info");
    node.textContent = message;
    box.appendChild(node);
    setTimeout(() => node.remove(), 6000);
  }

  const escape = (text) =>
    String(text == null ? "" : text).replace(/[&<>"']/g, (ch) =>
      ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[ch])
    );

  async function loadMembers() {
    const box = document.getElementById("admin-members");
    const data = await api("GET", "/admin/members");
    box.innerHTML = data.members
      .map(
        (m) => `
      <div class="admin__item">
        <span>${escape(m.full_name)}${m.role === "admin" ? " · админ" : ""}
          ${m.is_active ? "" : " · выключен"}${m.pin_is_set ? "" : " · PIN не задан"}</span>
        <span class="admin__actions">
          <button class="btn btn--small" data-admin="link" data-id="${m.id}">Выдать ссылку</button>
          <button class="btn btn--small" data-admin="toggle" data-id="${m.id}"
                  data-active="${m.is_active ? 0 : 1}">${m.is_active ? "Выключить" : "Включить"}</button>
        </span>
      </div>`
      )
      .join("");
  }

  async function loadFlagged() {
    const box = document.getElementById("admin-flagged");
    const data = await api("GET", "/admin/entries/flagged");
    if (!data.entries.length) {
      box.innerHTML = '<p class="empty">Ничего на проверку нет.</p>';
      return;
    }
    box.innerHTML = data.entries
      .map(
        (e) => `
      <div class="admin__item">
        <span><b>${escape(e.member_name)}</b> — ${e.pages} стр. ${escape(e.entry_date)}
          ${e.book ? "· " + escape(e.book) : ""}<br><small>${escape(e.flag_reason || "")}</small></span>
        <span class="admin__actions">
          <button class="btn btn--small" data-admin="approve" data-id="${e.id}">Всё верно</button>
          <button class="btn btn--small" data-admin="drop-entry" data-id="${e.id}">Удалить</button>
        </span>
      </div>`
      )
      .join("");
  }

  async function loadChallenges() {
    const data = await api("GET", "/admin/challenges");

    const pending = document.getElementById("admin-pending");
    pending.innerHTML = data.pending.length
      ? "<h3 class='section__title'>Ждут подтверждения</h3>" +
        data.pending
          .map(
            (p) => `
        <div class="admin__item">
          <span><b>${escape(p.member_name)}</b> — «${escape(p.challenge_title)}»</span>
          <span class="admin__actions">
            <button class="btn btn--small" data-admin="confirm" data-id="${p.id}" data-ok="1">Засчитать</button>
            <button class="btn btn--small" data-admin="confirm" data-id="${p.id}" data-ok="0">Отклонить</button>
          </span>
        </div>`
          )
          .join("")
      : "";

    const box = document.getElementById("admin-challenges");
    box.innerHTML = data.challenges
      .map(
        (c) => `
      <div class="admin__item">
        <span><b>${escape(c.week_start)}</b> — ${escape(c.title)}
          <small>${escape(c.type)}${c.target_value ? " · цель " + c.target_value : ""}
          · выполнили: ${c.winners_count}</small></span>
        <span class="admin__actions">
          <button class="btn btn--small" data-admin="drop-challenge" data-id="${c.id}">Удалить</button>
        </span>
      </div>`
      )
      .join("");
  }

  async function refresh() {
    await Promise.all([loadMembers(), loadFlagged(), loadChallenges()]);
  }

  document.addEventListener("submit", async (event) => {
    const form = event.target.closest("[data-form]");
    if (!form) return;
    event.preventDefault();
    try {
      if (form.dataset.form === "add-member") {
        const input = document.getElementById("new-member-name");
        const data = await api("POST", "/admin/members", { full_name: input.value.trim() });
        input.value = "";
        note("Ссылка для «" + data.full_name + "»: " + data.link, "ok");
        await navigator.clipboard.writeText(data.link).catch(() => {});
        await loadMembers();
      }
      if (form.dataset.form === "add-challenge") {
        await api("POST", "/admin/challenges", {
          week_start: document.getElementById("ch-week").value,
          title: document.getElementById("ch-title").value.trim(),
          type: document.getElementById("ch-type").value,
          target_value: document.getElementById("ch-target").value || null,
          genre: document.getElementById("ch-genre").value.trim(),
          description: document.getElementById("ch-desc").value.trim(),
        });
        document.getElementById("ch-title").value = "";
        note("Челлендж добавлен", "ok");
        await loadChallenges();
      }
    } catch (err) {
      note(err.message, "error");
    }
  });

  document.addEventListener("click", async (event) => {
    const button = event.target.closest("[data-admin]");
    if (button) {
      event.preventDefault();
      const id = button.dataset.id;
      try {
        switch (button.dataset.admin) {
          case "link": {
            const data = await api("POST", "/admin/members/" + id + "/link");
            note("Новая ссылка: " + data.link + " (старая больше не работает)", "ok");
            await navigator.clipboard.writeText(data.link).catch(() => {});
            await loadMembers();
            break;
          }
          case "toggle":
            await api("PATCH", "/admin/members/" + id, { is_active: button.dataset.active });
            await loadMembers();
            break;
          case "approve":
            await api("POST", "/admin/entries/" + id + "/approve");
            await loadFlagged();
            break;
          case "drop-entry":
            if (!confirm("Удалить запись?")) return;
            await api("DELETE", "/entries/" + id);
            await loadFlagged();
            break;
          case "confirm":
            await api("POST", "/admin/challenge-results/" + id + "/confirm", {
              approve: button.dataset.ok,
            });
            await loadChallenges();
            break;
          case "drop-challenge":
            if (!confirm("Удалить челлендж?")) return;
            await api("DELETE", "/admin/challenges/" + id);
            await loadChallenges();
            break;
        }
      } catch (err) {
        note(err.message, "error");
      }
      return;
    }

    const recompute = event.target.closest('[data-action="recompute"]');
    if (recompute) {
      event.preventDefault();
      try {
        const data = await api("POST", "/admin/recompute");
        note("Пересчитано. Новых выполнивших: " + data.newly_completed.length, "ok");
        await loadChallenges();
      } catch (err) {
        note(err.message, "error");
      }
    }
  });

  refresh().catch((err) => note(err.message, "error"));
})();
