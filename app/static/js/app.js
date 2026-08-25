/* «ЧитКод» — клиентская часть.
   Никакой бизнес-логики здесь нет: всё считает сервер, фронтенд только зовёт /api/v1/*
   и перерисовывает таблицу. Поэтому чат-бот и мобильное приложение получат ровно те же
   возможности, ничего не переписывая. */

(function () {
  "use strict";

  const API = "/api/v1";

  // --- мелкие помощники ------------------------------------------------------

  function cookie(name) {
    const found = document.cookie.split("; ").find((c) => c.startsWith(name + "="));
    return found ? decodeURIComponent(found.slice(name.length + 1)) : "";
  }

  function toast(message, kind) {
    const box = document.getElementById("toasts");
    if (!box) return;
    const node = document.createElement("div");
    node.className = "toast toast--" + (kind || "info");
    node.textContent = message;
    box.appendChild(node);
    setTimeout(() => node.remove(), 4200);
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
    let data = {};
    try {
      data = await response.json();
    } catch (err) {
      data = {};
    }
    if (!response.ok) {
      const message = (data.error && data.error.message) || "Что-то пошло не так";
      throw new Error(message);
    }
    return data;
  }

  // Тот же запасной путь, что и в админке: на HTTP и в части версий Safari
  // navigator.clipboard просто отсутствует.
  async function copyToClipboard(text) {
    if (navigator.clipboard && typeof navigator.clipboard.writeText === "function") {
      try {
        await navigator.clipboard.writeText(text);
        return true;
      } catch (_) {
        // ниже запасной способ
      }
    }
    const area = document.createElement("textarea");
    area.value = text;
    area.setAttribute("readonly", "");
    area.style.position = "fixed";
    area.style.left = "-9999px";
    document.body.appendChild(area);
    area.focus();
    area.select();
    area.setSelectionRange(0, area.value.length);
    try {
      return document.execCommand("copy");
    } catch (_) {
      return false;
    } finally {
      area.remove();
    }
  }

  const $ = (selector, root) => (root || document).querySelector(selector);
  const value = (id) => {
    const node = document.getElementById(id);
    return node ? node.value.trim() : "";
  };
  const numberOrNull = (id) => {
    const raw = value(id);
    return raw === "" ? null : Number(raw.replace(",", "."));
  };

  // --- перерисовка таблицы с анимацией перестановки --------------------------

  function rowPositions() {
    const map = new Map();
    document.querySelectorAll(".row[data-row-id]").forEach((row) => {
      map.set(row.dataset.rowId, row.getBoundingClientRect().top);
    });
    return map;
  }

  function animateFrom(previous) {
    document.querySelectorAll(".row[data-row-id]").forEach((row) => {
      const before = previous.get(row.dataset.rowId);
      if (before === undefined) return;
      const delta = before - row.getBoundingClientRect().top;
      if (Math.abs(delta) < 2) return;
      row.animate(
        [{ transform: "translateY(" + delta + "px)" }, { transform: "translateY(0)" }],
        { duration: 520, easing: "cubic-bezier(.2,.8,.2,1)" }
      );
    });
  }

  async function refreshBoard() {
    const board = document.getElementById("board");
    if (!board) return;
    const before = rowPositions();
    const response = await fetch("/board", { credentials: "same-origin" });
    const html = await response.text();
    const fresh = new DOMParser().parseFromString(html, "text/html").getElementById("board");
    if (!fresh) return;
    board.replaceWith(fresh);
    applySort();
    animateFrom(before);
  }

  // --- переключатель «за всё время / за неделю» ------------------------------

  let sortMode = "total";

  function applySort() {
    const board = document.getElementById("board");
    if (!board) return;
    const rows = Array.from(board.querySelectorAll(".row[data-row-id]"));
    if (!rows.length) return;

    if (sortMode === "week") {
      rows.sort((a, b) => Number(b.dataset.week) - Number(a.dataset.week));
    } else {
      rows.sort((a, b) => Number(a.dataset.rank) - Number(b.dataset.rank));
    }
    rows.forEach((row, index) => {
      board.appendChild(row);
      const num = row.querySelector(".rank__num");
      if (num) num.textContent = sortMode === "week" ? index + 1 : row.dataset.rank;
    });
  }

  // --- переход на новый уровень ---------------------------------------------

  function celebrate(levelUp) {
    const box = document.getElementById("celebrate");
    if (!box || !levelUp) return;
    $("#celebrate-avatar").src = levelUp.avatar || "";
    $("#celebrate-level").textContent = levelUp.level_name;
    $("#celebrate-total").textContent = levelUp.total_pages + " страниц за всё время";
    box.hidden = false;
  }

  // --- действия --------------------------------------------------------------

  async function saveEntry(pages, percent) {
    const bookSelect = document.getElementById("entry-book");
    const payload = {
      book_id: bookSelect && bookSelect.value ? Number(bookSelect.value) : null,
      note: value("entry-note") || null,
      entry_date: value("entry-date") || null,
    };
    if (percent !== undefined && percent !== null) payload.percent = percent;
    else payload.pages = pages;

    const data = await api("POST", "/entries", payload);
    const sheet = document.getElementById("entry-sheet");
    if (sheet && sheet.open) sheet.close();
    const added = data.entry.pages;
    toast("Записали " + added + " " + pagesWord(added), "ok");
    await refreshBoard();
    if (data.challenge_done) toast("Челлендж недели выполнен!", "ok");
    if (data.level_up) celebrate(data.level_up);
    const note = document.getElementById("entry-note");
    if (note) note.value = "";
    const custom = document.getElementById("entry-pages");
    if (custom) custom.value = "";
    const pct = document.getElementById("entry-percent");
    if (pct) pct.value = "";
  }

  function pagesWord(n) {
    const abs = Math.abs(n);
    if (abs % 10 === 1 && abs % 100 !== 11) return "страницу";
    if (abs % 10 >= 2 && abs % 10 <= 4 && !(abs % 100 >= 12 && abs % 100 <= 14)) return "страницы";
    return "страниц";
  }

  // --- цитаты: одна панель на добавление и на правку -------------------------

  let editingQuoteId = null;

  function openQuoteSheet(quote) {
    const sheet = document.getElementById("quote-sheet");
    if (!sheet) return;
    editingQuoteId = quote ? quote.id : null;

    const title = document.getElementById("quote-sheet-title");
    if (title) title.textContent = quote ? "Изменить цитату" : "Понравившаяся цитата";

    document.getElementById("quote-text").value = quote ? quote.text : "";
    const page = document.getElementById("quote-page");
    if (page) page.value = quote && quote.page ? quote.page : "";

    const bookSelect = document.getElementById("quote-book");
    if (bookSelect) {
      bookSelect.value = quote && quote.book_id ? String(quote.book_id) : bookSelect.value;
      if (quote && !quote.book_id) bookSelect.value = "";
    }
    const manualBox = document.getElementById("quote-book-manual");
    const manual = document.getElementById("quote-book-label");
    if (manual) manual.value = quote && !quote.book_id ? quote.book || "" : "";
    if (manualBox) manualBox.hidden = Boolean(bookSelect && bookSelect.value);

    sheet.showModal();
  }

  // На стене цитат перерисовывать нечего — проще перезагрузить страницу
  async function afterQuoteChange() {
    if (document.getElementById("board")) await refreshBoard();
    else location.reload();
  }

  const actions = {
    "open-entry": () => document.getElementById("entry-sheet").showModal(),

    "save-entry": async () => {
      const percent = numberOrNull("entry-percent");
      const pages = numberOrNull("entry-pages");
      if (percent) return saveEntry(null, percent);
      if (!pages) {
        toast("Введите число страниц", "error");
        return;
      }
      return saveEntry(pages);
    },

    "delete-entry": async (button) => {
      if (!confirm("Удалить запись?")) return;
      await api("DELETE", "/entries/" + button.dataset.id);
      button.closest("li").remove();
      toast("Запись удалена", "ok");
      await refreshBoard();
    },

    "edit-book": () => {
      const sheet = document.getElementById("entry-sheet");
      if (sheet && sheet.open) sheet.close();
      document.getElementById("book-sheet").showModal();
    },

    "save-book": async () => {
      const title = value("book-title");
      if (!title) {
        toast("Введите название книги", "error");
        return;
      }
      await api("POST", "/books", {
        author: value("book-author"),
        title,
        total_pages: numberOrNull("book-total"),
        format: value("book-format") || "paper",
      });
      toast("Книга сохранена", "ok");
      location.reload();
    },

    "finish-book": async () => {
      const select = document.getElementById("entry-book");
      if (!select || !select.value) {
        toast("Сначала выберите книгу", "error");
        return;
      }
      if (!confirm("Отметить книгу дочитанной?")) return;
      await api("POST", "/books/" + select.value + "/finish");
      toast("Книга на полке прочитанного", "ok");
      location.reload();
    },

    "add-quote": () => {
      const sheet = document.getElementById("entry-sheet");
      if (sheet && sheet.open) sheet.close();
      openQuoteSheet(null);
    },

    "edit-quote": async (button) => {
      const data = await api("GET", "/quotes/" + button.dataset.id);
      openQuoteSheet(data.quote);
    },

    "save-quote": async () => {
      const text = value("quote-text");
      if (!text) {
        toast("Цитата пустая", "error");
        return;
      }
      const bookSelect = document.getElementById("quote-book");
      const payload = {
        text,
        book_id: bookSelect && bookSelect.value ? Number(bookSelect.value) : null,
        book_label: value("quote-book-label"),
        page: numberOrNull("quote-page"),
      };

      if (editingQuoteId) {
        await api("PATCH", "/quotes/" + editingQuoteId, payload);
        toast("Цитата изменена", "ok");
      } else {
        await api("POST", "/quotes", payload);
        toast("Цитата на стене", "ok");
      }

      document.getElementById("quote-sheet").close();
      document.getElementById("quote-text").value = "";
      editingQuoteId = null;
      await afterQuoteChange();
    },

    "delete-quote": async (button) => {
      if (!confirm("Удалить цитату?")) return;
      await api("DELETE", "/quotes/" + button.dataset.id);
      toast("Цитата удалена", "ok");
      // На стене цитат карточку убираем на месте, в таблице перерисовываем строку
      const card = button.closest(".card");
      if (card) card.remove();
      else await refreshBoard();
    },

    "copy-join-link": async (button) => {
      const link = document.getElementById("join-link");
      const ok = await copyToClipboard(link ? link.textContent.trim() : "");
      toast(ok ? "Ссылка скопирована" : "Скопируйте ссылку вручную", ok ? "ok" : "info");
      if (ok) button.textContent = "Скопировано";
    },

    "edit-name": () => document.getElementById("name-sheet").showModal(),

    "save-name": async () => {
      const name = value("name-input");
      if (!name) {
        toast("Имя не может быть пустым", "error");
        return;
      }
      await api("PATCH", "/members/me", { full_name: name });
      location.reload();
    },

    "more-quotes": (button) => {
      const box = document.getElementById("quotes-" + button.dataset.member);
      if (box) box.hidden = !box.hidden;
    },

    "claim-challenge": async (button) => {
      await api("POST", "/challenges/" + button.dataset.id + "/claim");
      toast("Отметили — администратор подтвердит", "ok");
    },

    "logout": async () => {
      await api("POST", "/auth/logout");
      location.href = "/";
    },

    "close-celebrate": () => {
      document.getElementById("celebrate").hidden = true;
    },

    "toggle-theme": () => {
      const root = document.documentElement;
      const dark = root.getAttribute("data-theme") !== "dark";
      if (dark) root.setAttribute("data-theme", "dark");
      else root.removeAttribute("data-theme");
      try {
        // Явный выбор перебивает системную настройку и переживает перезаход
        localStorage.setItem("chitkod-theme", dark ? "dark" : "light");
      } catch (err) {
        // приватный режим: тема продержится до перезагрузки страницы
      }
    },
  };

  // --- привязка --------------------------------------------------------------

  document.addEventListener("click", async (event) => {
    const preset = event.target.closest(".preset");
    if (preset) {
      // Второе касание: пресет сразу сохраняет запись
      try {
        await saveEntry(Number(preset.dataset.pages));
      } catch (err) {
        toast(err.message, "error");
      }
      return;
    }

    const sortBtn = event.target.closest(".segmented__btn");
    if (sortBtn) {
      document
        .querySelectorAll(".segmented__btn")
        .forEach((btn) => btn.classList.toggle("is-active", btn === sortBtn));
      sortMode = sortBtn.dataset.sort;
      const before = rowPositions();
      applySort();
      animateFrom(before);
      return;
    }

    const button = event.target.closest("[data-action]");
    if (!button) return;
    const handler = actions[button.dataset.action];
    if (!handler) return;
    event.preventDefault();
    try {
      await handler(button);
    } catch (err) {
      toast(err.message, "error");
    }
  });

  // Ручная подпись книги в цитате — только когда книга не выбрана из списка
  document.addEventListener("change", (event) => {
    if (event.target.id === "quote-book") {
      const manual = document.getElementById("quote-book-manual");
      if (manual) manual.hidden = Boolean(event.target.value);
    }
  });

  // --- вход по персональной ссылке -------------------------------------------

  document.addEventListener("submit", async (event) => {
    const form = event.target.closest("[data-form]");
    if (!form) return;
    const kind = form.dataset.form;

    if (kind === "join") {
      event.preventDefault();
      const codeField = document.getElementById("join-code");
      try {
        const data = await api("POST", "/join", {
          code: (codeField ? codeField.value : form.dataset.code || "").trim().toUpperCase(),
          full_name: value("join-name"),
          pin: value("join-pin"),
          pin_repeat: value("join-pin2"),
        });
        document.getElementById("join-form-box").hidden = true;
        const done = document.getElementById("join-done");
        document.getElementById("join-link").textContent = data.link;
        done.hidden = false;
        // Ссылка показывается один раз — сразу кладём её в буфер обмена
        await copyToClipboard(data.link);
        window.scrollTo(0, 0);
      } catch (err) {
        toast(err.message, "error");
      }
      return;
    }

    if (kind !== "login" && kind !== "set-pin") return;

    event.preventDefault();
    const token = form.dataset.token;
    try {
      if (kind === "set-pin") {
        await api("POST", "/auth/set-pin", {
          token,
          pin: value("pin"),
          pin_repeat: value("pin2"),
        });
      } else {
        await api("POST", "/auth/login", { token, pin: value("pin") });
      }
      location.href = "/";
    } catch (err) {
      toast(err.message, "error");
    }
  });

  document.addEventListener("DOMContentLoaded", applySort);
})();
