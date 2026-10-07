const proto = location.protocol === "https:" ? "wss:" : "ws:";
const socketUrl = `${proto}//${location.host}/ws`;
const pending = {};

function handleMessage(msg) {
  const t = msg.type;
  if (t === "authed" && pending.auth) {
    const done = pending.auth;
    pending.auth = null;
    done(msg);
  }
  if (t === "toast") toast(msg.text);
  if (t === "loggedOut") showGate();
  if (t === "kicked") {
    clearSession();
    state.username = null;
    toast(msg.text || "Logged out.");
    showGate();
  }
  if (t === "created" && pending.create) pending.create(msg);
  if (t === "joined" && pending.join) pending.join(msg);
  if (t === "room") {
    state.room = msg.room;
    if (msg.room.state === "lobby") showLobby();
    else if (state.screen === "game") refreshChatOnly();
  }
  if (t === "matchStart") {
    state.frame = null;
    state.results = null;
    showGame();
  }
  if (t === "frame") {
    state.frame = msg;
    absorbFrame(msg);
    if (state.screen !== "game") showGame();
    updateHud();
  }
  if (t === "results") {
    state.results = msg;
    showResults();
  }
  if (t === "profile") {
    state.profile = msg.profile;
    if (state.screen === "home") showHome();
    if (state.screen === "lobby") showLobby();
  }
  if (t === "leaderboard") state.leaderboard = msg.leaderboard || [];
  if (t === "renamed" && pending.rename) pending.rename(msg);
  if (t === "directory") {
    state.directory = { online: msg.online || [], taken: msg.taken || [], ranks: msg.ranks || (state.directory && state.directory.ranks) || [] };
    const lists = document.getElementById("playerLists");
    if (lists && state.screen === "home") {
      const online = document.getElementById("onlineList");
      const taken = document.getElementById("takenList");
      if (online) online.innerHTML = peopleList(state.directory.online, "Nobody is online yet.");
      if (taken) taken.innerHTML = peopleList(state.directory.taken, "No accounts yet.");
    }
  }
  if (t === "admin" && pending.admin) pending.admin(msg);
}

function makeSock() {
  const ws = new WebSocket(socketUrl);
  ws.onmessage = (ev) => {
    try {
      handleMessage(JSON.parse(ev.data));
    } catch {
      /* ignore */
    }
  };
  ws.onopen = () => {
    if (state.token && state.username && state.screen !== "gate") {
      socket.send({ type: "resume", username: state.username, token: state.token });
    } else {
      tryAutoLogin();
    }
  };
  ws.onclose = () => setTimeout(() => socket._reconnect(), 1200);
  return ws;
}

const socket = {
  ws: null,
  send(obj) {
    if (this.ws && this.ws.readyState === 1) this.ws.send(JSON.stringify(obj));
  },
  emit(type, a, b) {
    if (type === "signup" || type === "login" || type === "resume") {
      pending.auth = b;
      this.send({ type, username: a.username, password: a.password || "", token: a.token || "" });
    } else if (type === "logout") this.send({ type: "logout" });
    else if (type === "createRoom") {
      pending.create = a;
      this.send({ type: "createRoom" });
    } else if (type === "joinRoom") {
      pending.join = b;
      this.send({ type: "joinRoom", code: a });
    } else if (type === "leaveRoom") this.send({ type: "leaveRoom" });
    else if (type === "chat") this.send({ type: "chat", text: a, adminToken: state.adminToken || "" });
    else if (type === "ready") this.send({ type: "ready", ready: a });
    else if (type === "startGame") this.send({ type: "startGame" });
    else if (type === "friendRequest") this.send({ type: "friendRequest", target: a });
    else if (type === "acceptFriend") this.send({ type: "acceptFriend", target: a });
    else if (type === "declineFriend") this.send({ type: "declineFriend", target: a });
    else if (type === "getLeaderboard") this.send({ type: "getLeaderboard" });
    else if (type === "changeName") {
      pending.rename = b;
      this.send({ type: "changeName", username: a });
    } else if (type === "adminLogin") {
      pending.admin = b;
      this.send({ type: "adminLogin", password: a });
    } else if (type === "adminSetRank") {
      pending.admin = b;
      this.send({ type: "adminSetRank", username: a.username, rank: a.rank, adminToken: a.adminToken });
    }
  },
  _reconnect() {
    this.ws = makeSock();
  },
};
socket.ws = makeSock();

const app = document.getElementById("app");
const topUser = document.getElementById("topUser");
const topName = document.getElementById("topName");

const state = {
  username: null,
  profile: null,
  leaderboard: [],
  room: null,
  screen: "gate",
  frame: null,
  results: null,
  keys: { u: false, d: false, l: false, r: false },
  token: null,
  adminToken: null,
  view: {},
  directory: { online: [], taken: [], ranks: ["Player", "Helper", "Builder", "VIP", "Star", "Moderator", "Admin", "Owner"] },
};
try {
  state.adminToken = localStorage.getItem("auraquest_admin") || null;
} catch {
  state.adminToken = null;
}

document.getElementById("btnHome").onclick = () => {
  if (state.room) socket.emit("leaveRoom");
  state.room = null;
  state.frame = null;
  state.results = null;
  showHome();
};

window.addEventListener("keydown", (e) => {
  if (state.screen !== "game") return;
  const map = { ArrowUp: "u", KeyW: "u", ArrowDown: "d", KeyS: "d", ArrowLeft: "l", KeyA: "l", ArrowRight: "r", KeyD: "r" };
  if (map[e.code]) {
    e.preventDefault();
    state.keys[map[e.code]] = true;
    socket.send({ type: "input", keys: state.keys });
  }
});
window.addEventListener("keyup", (e) => {
  const map = { ArrowUp: "u", KeyW: "u", ArrowDown: "d", KeyS: "d", ArrowLeft: "l", KeyA: "l", ArrowRight: "r", KeyD: "r" };
  if (map[e.code]) {
    state.keys[map[e.code]] = false;
    if (state.screen === "game") socket.send({ type: "input", keys: state.keys });
  }
});

function toast(text) {
  const el = document.createElement("div");
  el.className = "toast";
  el.textContent = text;
  document.getElementById("toasts").appendChild(el);
  setTimeout(() => el.remove(), 3200);
}

function esc(s) {
  return String(s ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;");
}

const SAVE_KEY = "auraquest_session";

function savedSession() {
  try {
    return JSON.parse(localStorage.getItem(SAVE_KEY) || "null");
  } catch {
    return null;
  }
}

function rememberSession(username, token) {
  try {
    localStorage.setItem(SAVE_KEY, JSON.stringify({ username, token }));
  } catch {
    /* ignore */
  }
}

function clearSession() {
  state.token = null;
  try {
    localStorage.removeItem(SAVE_KEY);
    localStorage.removeItem("auraquest_username");
  } catch {
    /* ignore */
  }
  document.cookie = "auraquest_username=; max-age=0; path=/";
}

function finishAuth(res) {
  state.username = res.profile.username;
  state.token = res.token;
  state.profile = res.profile;
  state.leaderboard = res.leaderboard || [];
  if (res.directory) state.directory = res.directory;
  rememberSession(state.username, state.token);
  topName.textContent = state.username;
  topUser.hidden = false;
  showHome();
}

function tryAutoLogin() {
  const saved = savedSession();
  if (!saved || !saved.token || state.username) return;
  if (!socket.ws || socket.ws.readyState !== 1) return;
  socket.emit("resume", saved, (res) => {
    if (!res.ok) return;
    finishAuth(res);
  });
}

showGate();

function showGate() {
  state.screen = "gate";
  topUser.hidden = true;
  app.innerHTML = `
    <section class="hero">
      <h1>Dash. Grab orbs.<br/><span>Beat your friends.</span></h1>
      <p class="lead">Create an account once. Old taken names were cleared, so you can pick again.</p>
    </section>
    <div class="card gate">
      <h2>Create account or log in</h2>
      <input id="nameIn" maxlength="16" placeholder="Username" autocomplete="username" />
      <input id="passIn" class="mt" maxlength="32" type="password" placeholder="Password" autocomplete="current-password" />
      <p class="hint">Username: 3–16 letters, numbers, or _. Password: 4–32 characters. No spaces.</p>
      <div class="error" id="gateErr"></div>
      <div class="row mt">
        <button class="primary" id="signupBtn" style="flex:1">Create account</button>
        <button class="teal" id="loginBtn" style="flex:1">Log in</button>
      </div>
    </div>
  `;
  const nameIn = document.getElementById("nameIn");
  const passIn = document.getElementById("passIn");
  const go = (mode) => {
    const err = document.getElementById("gateErr");
    err.textContent = "";
    if (!socket.ws || socket.ws.readyState !== 1) {
      err.textContent = "Not connected yet. Wait one second and try again.";
      return;
    }
    socket.emit(mode, { username: nameIn.value.trim(), password: passIn.value }, (res) => {
      if (!res || !res.ok) {
        err.textContent = (res && res.error) || "Could not create the account. Try again.";
        return;
      }
      finishAuth(res);
    });
  };
  document.getElementById("signupBtn").onclick = () => go("signup");
  document.getElementById("loginBtn").onclick = () => go("login");
  passIn.addEventListener("keydown", (e) => {
    if (e.key === "Enter") go("signup");
  });
  nameIn.focus();
}

function rankBadge(rank) {
  const r = rank || "Player";
  return `<span class="badge rank-${esc(r).toLowerCase()}">${esc(r)}</span>`;
}

function peopleList(rows, empty) {
  if (!rows || !rows.length) return `<p class="hint">${empty}</p>`;
  return rows
    .map(
      (p) => `<div class="item"><span class="who">${esc(p.username)}</span><span>${rankBadge(p.rank)}${p.online ? ` <span class="badge ready">Online</span>` : ""}</span></div>`
    )
    .join("");
}

function showHome() {
  state.screen = "home";
  const p = state.profile || { totalScore: 0, gamesPlayed: 0, bestScore: 0, friends: [], requestsIn: [] };
  const lb = state.leaderboard || [];
  app.innerHTML = `
    <section class="hero" style="padding-top:12px">
      <h1>Welcome, <span>${esc(state.username)}</span> ${rankBadge(p.rank)}</h1>
      <p class="lead">75-second orb rush. Move with WASD or arrow keys. Biggest haul wins.</p>
    </section>
    <div class="stat-row">
      <div class="stat"><b>${p.totalScore}</b><span>Total points</span></div>
      <div class="stat"><b>${p.bestScore}</b><span>Best match</span></div>
      <div class="stat"><b>${p.gamesPlayed}</b><span>Matches</span></div>
    </div>
    <div class="card mb">
      <h2>Your name</h2>
      <p class="hint mb">Logged in on this device. You can change the name; your password stays the same.</p>
      <div class="row">
        <input id="renameIn" maxlength="16" value="${esc(state.username)}" />
        <button class="ghost" id="renameBtn">Save name</button>
        <button class="danger" id="logoutBtn">Log out</button>
      </div>
      <div class="error" id="renameErr"></div>
    </div>
    <div class="grid grid-2">
      <div class="card">
        <h2>Play together</h2>
        <div class="row">
          <button class="primary" id="createBtn">Create room</button>
        </div>
        <p class="hint mt">Or join a friend's room</p>
        <div class="row mt">
          <input id="codeIn" maxlength="5" placeholder="ROOM CODE" style="text-transform:uppercase;flex:1" />
          <button class="teal" id="joinBtn">Join</button>
        </div>
        <div class="error" id="homeErr"></div>
      </div>
      <div class="card">
        <h2>Friends</h2>
        ${p.requestsIn && p.requestsIn.length ? `<p class="hint mb">${p.requestsIn.length} pending request(s)</p>` : ""}
        <div class="list">
          ${
            p.friends && p.friends.length
              ? p.friends.map((f) => `<div class="item"><span class="who">${esc(f)}</span><span class="badge">Friend</span></div>`).join("")
              : `<p class="hint">No friends yet. Add players from a room.</p>`
          }
        </div>
        ${(p.requestsIn || [])
          .map(
            (n) => `
          <div class="item mt">
            <span class="who">${esc(n)}</span>
            <div class="row">
              <button class="teal" data-accept="${esc(n)}">Accept</button>
              <button class="ghost" data-decline="${esc(n)}">No</button>
            </div>
          </div>`
          )
          .join("")}
        <div class="row mt">
          <input id="friendIn" placeholder="Add by username" />
          <button class="ghost" id="addFriendBtn">Add</button>
        </div>
      </div>
    </div>
    <div class="grid grid-2 mt" id="playerLists">
      <div class="card">
        <h2>Current players</h2>
        <p class="hint mb">Who is online right now.</p>
        <div class="list" id="onlineList">${peopleList(state.directory.online, "Nobody is online yet.")}</div>
      </div>
      <div class="card">
        <h2>Taken usernames</h2>
        <p class="hint mb">Accounts that already exist. Ranks stay saved.</p>
        <div class="list" id="takenList">${peopleList(state.directory.taken, "No accounts yet.")}</div>
      </div>
    </div>
    <div class="card mt" id="adminCard">
      <h2>Admin panel</h2>
      <p class="hint mb">Ranks are permanent. Only the admin password opens this.</p>
      <div id="adminLock" ${state.adminToken ? "hidden" : ""}>
        <div class="row">
          <input id="adminPass" type="password" placeholder="Admin password" />
          <button class="primary" id="adminBtn">Unlock</button>
        </div>
        <div class="error" id="adminErr"></div>
      </div>
      <div id="adminOpen" ${state.adminToken ? "" : "hidden"}>
        <div class="row">
          <input id="adminUser" placeholder="Username" />
          <select id="adminRank">
            ${(state.directory.ranks || []).map((r) => `<option>${esc(r)}</option>`).join("")}
          </select>
          <button class="teal" id="setRankBtn">Set rank</button>
        </div>
        <p class="hint mb">Commands: /rank Name Owner · /players · /taken · /kick Name · /help</p>
      </div>
    </div>
    <div class="card mt">
      <h2>Leaderboard</h2>
      <div class="list">
        ${
          lb.length
            ? lb
                .slice(0, 10)
                .map(
                  (e, i) => `
                  <div class="item rank ${i === 0 ? "gold" : i === 1 ? "silver" : i === 2 ? "bronze" : ""}">
                    <div style="display:flex;align-items:center;gap:12px">
                      <span class="pos">${i + 1}</span>
                      <span class="who">${esc(e.username)}</span>
                    </div>
                    <span>${e.totalScore} pts · best ${e.bestScore}</span>
                  </div>`
                )
                .join("")
            : `<p class="hint">Play a match to appear here.</p>`
        }
      </div>
    </div>
  `;
  document.getElementById("createBtn").onclick = () => {
    socket.emit("createRoom", (res) => {
      if (!res.ok) return (document.getElementById("homeErr").textContent = res.error);
      state.room = res.room;
      showLobby();
    });
  };
  document.getElementById("joinBtn").onclick = joinCode;
  document.getElementById("codeIn").addEventListener("keydown", (e) => e.key === "Enter" && joinCode());
  document.getElementById("addFriendBtn").onclick = () => {
    const n = document.getElementById("friendIn").value.trim();
    if (n) socket.emit("friendRequest", n);
  };
  app.querySelectorAll("[data-accept]").forEach((b) => (b.onclick = () => socket.emit("acceptFriend", b.dataset.accept)));
  app.querySelectorAll("[data-decline]").forEach((b) => (b.onclick = () => socket.emit("declineFriend", b.dataset.decline)));
  document.getElementById("renameBtn").onclick = () => {
    const n = document.getElementById("renameIn").value.trim();
    document.getElementById("renameErr").textContent = "";
    socket.emit("changeName", n, (res) => {
      if (!res.ok) {
        document.getElementById("renameErr").textContent = res.error;
        return;
      }
      state.username = res.profile.username;
      state.profile = res.profile;
      state.leaderboard = res.leaderboard || state.leaderboard;
      rememberSession(state.username, state.token);
      topName.textContent = state.username;
      toast("Name saved: " + state.username);
      showHome();
    });
  };
  document.getElementById("logoutBtn").onclick = () => {
    socket.emit("logout");
    clearSession();
    state.username = null;
    state.profile = null;
    showGate();
  };
  const adminBtn = document.getElementById("adminBtn");
  if (adminBtn) {
    adminBtn.onclick = () => {
      document.getElementById("adminErr").textContent = "";
      socket.emit("adminLogin", document.getElementById("adminPass").value, (res) => {
        if (!res.ok) {
          document.getElementById("adminErr").textContent = res.error;
          return;
        }
        state.adminToken = res.adminToken;
        try { localStorage.setItem("auraquest_admin", res.adminToken); } catch { /* ignore */ }
        if (res.directory) state.directory = res.directory;
        toast("Admin panel unlocked");
        showHome();
      });
    };
  }
  const setRankBtn = document.getElementById("setRankBtn");
  if (setRankBtn) {
    setRankBtn.onclick = () => {
      document.getElementById("adminSetErr").textContent = "";
      socket.emit(
        "adminSetRank",
        {
          username: document.getElementById("adminUser").value.trim(),
          rank: document.getElementById("adminRank").value,
          adminToken: state.adminToken,
        },
        (res) => {
          if (!res.ok) {
            document.getElementById("adminSetErr").textContent = res.error;
            return;
          }
          if (res.directory) state.directory = res.directory;
          toast(res.text || "Rank saved");
          showHome();
        }
      );
    };
  }
}

function joinCode() {
  const code = document.getElementById("codeIn").value;
  socket.emit("joinRoom", code, (res) => {
    if (!res.ok) return (document.getElementById("homeErr").textContent = res.error);
    state.room = res.room;
    showLobby();
  });
}

function showLobby() {
  state.screen = "lobby";
  const r = state.room;
  if (!r) return showHome();
  const p = state.profile || { friends: [] };
  const isHost = r.host === state.username;
  app.innerHTML = `
    <div class="grid grid-2">
      <div class="card">
        <h2>Room ${esc(r.code)}</h2>
        <p class="hint mb">Share this code. Host starts the rush when everyone is in.</p>
        <div class="row mb">
          <button class="teal" id="copyBtn">Copy invite code</button>
          <button class="ghost" id="leaveBtn">Leave</button>
        </div>
        <div class="list">
          ${r.players
            .map((pl) => {
              const mine = pl.username === state.username;
              const friend = (p.friends || []).includes(pl.username);
              return `<div class="item">
                <div>
                  <span class="who">${esc(pl.username)}</span>
                  ${pl.username === r.host ? `<span class="badge host">Host</span>` : ""}
                  ${pl.ready ? `<span class="badge ready">Ready</span>` : ""}
                </div>
                <div class="row">
                  ${mine ? "" : friend ? `<span class="badge">Friend</span>` : `<button class="ghost" data-add="${esc(pl.username)}">Add friend</button>`}
                </div>
              </div>`;
            })
            .join("")}
        </div>
        <div class="row mt">
          <button class="ghost" id="readyBtn">${r.players.find((x) => x.username === state.username)?.ready ? "Unready" : "I'm ready"}</button>
          ${isHost ? `<button class="primary" id="startBtn">Start rush</button>` : `<span class="hint">Waiting for host…</span>`}
        </div>
      </div>
      ${chatBox(r)}
    </div>
  `;
  bindChat();
  document.getElementById("copyBtn").onclick = async () => {
    try {
      await navigator.clipboard.writeText(r.code);
      toast("Code copied: " + r.code);
    } catch {
      toast("Code: " + r.code);
    }
  };
  document.getElementById("leaveBtn").onclick = () => {
    socket.emit("leaveRoom");
    state.room = null;
    socket.emit("getLeaderboard");
    setTimeout(showHome, 150);
  };
  document.getElementById("readyBtn").onclick = () => {
    const me = r.players.find((x) => x.username === state.username);
    socket.emit("ready", !(me && me.ready));
  };
  const start = document.getElementById("startBtn");
  if (start) start.onclick = () => socket.emit("startGame");
  app.querySelectorAll("[data-add]").forEach((b) => (b.onclick = () => socket.emit("friendRequest", b.dataset.add)));
}

function chatBox(r) {
  return `
    <div class="card">
      <h2>Chat</h2>
      <div class="chat">
        <div class="chat-log" id="chatLog">
          ${(r.chat || [])
            .map((m) =>
              m.from === "System"
                ? `<div class="msg system">${esc(m.text)}</div>`
                : `<div class="msg"><span class="from">${esc(m.from)}</span>${esc(m.text)}</div>`
            )
            .join("")}
        </div>
        <form class="chat-form" id="chatForm">
          <input id="chatIn" maxlength="200" placeholder="Say something…" autocomplete="off" />
          <button class="primary" type="submit">Send</button>
        </form>
      </div>
    </div>`;
}

function bindChat() {
  const log = document.getElementById("chatLog");
  if (log) log.scrollTop = log.scrollHeight;
  const form = document.getElementById("chatForm");
  if (form) {
    form.onsubmit = (e) => {
      e.preventDefault();
      const input = document.getElementById("chatIn");
      const t = input.value.trim();
      if (t) socket.emit("chat", t);
      input.value = "";
    };
  }
}

function refreshChatOnly() {
  const log = document.getElementById("chatLog");
  if (!log || !state.room) return;
  log.innerHTML = (state.room.chat || [])
    .map((m) =>
      m.from === "System"
        ? `<div class="msg system">${esc(m.text)}</div>`
        : `<div class="msg"><span class="from">${esc(m.from)}</span>${esc(m.text)}</div>`
    )
    .join("");
  log.scrollTop = log.scrollHeight;
}

function showGame() {
  if (state.screen === "game" && document.getElementById("arena")) return;
  state.screen = "game";
  const r = state.room;
  app.innerHTML = `
    <div class="arena-wrap card">
      <div class="arena-hud">
        <div id="hudTime">0:75</div>
        <div id="hudScores"></div>
        <div class="hint">WASD or arrows</div>
      </div>
      <canvas id="arena" width="1200" height="700"></canvas>
      <div class="pad">
        <button data-k="u">▲</button>
        <div class="pad-mid">
          <button data-k="l">◀</button>
          <button data-k="d">▼</button>
          <button data-k="r">▶</button>
        </div>
      </div>
    </div>
    ${r ? `<div class="mt">${chatBox(r)}</div>` : ""}
  `;
  bindChat();
  bindPad();
  drawGame();
}

function bindPad() {
  app.querySelectorAll(".pad button").forEach((b) => {
    const k = b.dataset.k;
    const down = (e) => {
      e.preventDefault();
      state.keys[k] = true;
      socket.send({ type: "input", keys: state.keys });
    };
    const up = (e) => {
      e.preventDefault();
      state.keys[k] = false;
      socket.send({ type: "input", keys: state.keys });
    };
    b.addEventListener("mousedown", down);
    b.addEventListener("mouseup", up);
    b.addEventListener("mouseleave", up);
    b.addEventListener("touchstart", down, { passive: false });
    b.addEventListener("touchend", up);
  });
}

function updateHud() {
  const f = state.frame;
  if (!f) return;
  const t = document.getElementById("hudTime");
  const s = document.getElementById("hudScores");
  if (t) {
    const sec = Math.max(0, Math.ceil(f.timeLeft || 0));
    t.textContent = `${Math.floor(sec / 60)}:${String(sec % 60).padStart(2, "0")}`;
  }
  if (s) {
    s.innerHTML = (f.players || [])
      .slice()
      .sort((a, b) => b.score - a.score)
      .map((p) => `<span class="who">${esc(p.username)} <b>${p.score}</b></span>`)
      .join(" · ");
  }
}

function absorbFrame(f) {
  const now = performance.now();
  (f.players || []).forEach((p) => {
    const prev = state.view[p.username] || { x: p.x, y: p.y };
    state.view[p.username] = {
      x: prev.x,
      y: prev.y,
      tx: p.x,
      ty: p.y,
      vx: p.vx || 0,
      vy: p.vy || 0,
      color: p.color,
      score: p.score,
      at: now,
    };
  });
}

function tickView() {
  const now = performance.now();
  Object.values(state.view).forEach((v) => {
    const dt = Math.min(0.05, (now - (v.at || now)) / 1000);
    v.at = now;
    const nx = v.x + (v.vx || 0) * dt;
    const ny = v.y + (v.vy || 0) * dt;
    v.x = nx + (v.tx - nx) * 0.35;
    v.y = ny + (v.ty - ny) * 0.35;
  });
  if (state.screen === "game") drawGame();
  requestAnimationFrame(tickView);
}
requestAnimationFrame(tickView);

function drawGame() {
  const canvas = document.getElementById("arena");
  if (!canvas) return;
  const ctx = canvas.getContext("2d");
  const f = state.frame;
  const w = canvas.width;
  const h = canvas.height;
  ctx.fillStyle = "#0b1020";
  ctx.fillRect(0, 0, w, h);
  ctx.strokeStyle = "rgba(139,124,255,0.12)";
  ctx.lineWidth = 1;
  for (let x = 0; x < w; x += 50) {
    ctx.beginPath();
    ctx.moveTo(x, 0);
    ctx.lineTo(x, h);
    ctx.stroke();
  }
  for (let y = 0; y < h; y += 50) {
    ctx.beginPath();
    ctx.moveTo(0, y);
    ctx.lineTo(w, y);
    ctx.stroke();
  }
  if (!f) {
    ctx.fillStyle = "#a9a3c7";
    ctx.font = "20px Outfit, sans-serif";
    ctx.textAlign = "center";
    ctx.fillText("Get ready…", w / 2, h / 2);
    return;
  }
  (f.orbs || []).forEach((o) => {
    ctx.beginPath();
    ctx.fillStyle = o.color;
    ctx.shadowColor = o.color;
    ctx.shadowBlur = 16;
    ctx.arc(o.x, o.y, o.r, 0, Math.PI * 2);
    ctx.fill();
    ctx.shadowBlur = 0;
  });
  (f.players || []).forEach((p) => {
    const v = state.view[p.username] || p;
    const x = v.x;
    const y = v.y;
    ctx.beginPath();
    ctx.fillStyle = p.color;
    ctx.shadowColor = p.color;
    ctx.shadowBlur = 18;
    ctx.arc(x, y, 18, 0, Math.PI * 2);
    ctx.fill();
    ctx.shadowBlur = 0;
    ctx.fillStyle = "#fff";
    ctx.font = "12px Outfit, sans-serif";
    ctx.textAlign = "center";
    ctx.fillText(p.username, x, y - 26);
    ctx.fillText(String(p.score), x, y + 4);
  });
}

function showResults() {
  state.screen = "results";
  const ranking = state.results?.ranking || [];
  app.innerHTML = `
    <section class="hero">
      <h1>Time's <span>up</span></h1>
      <p class="lead">Back to the lobby in a few seconds for a rematch.</p>
    </section>
    <div class="card">
      <h2>Final standings</h2>
      <div class="list">
        ${ranking
          .map(
            (e, i) => `
          <div class="item rank ${i === 0 ? "gold" : i === 1 ? "silver" : i === 2 ? "bronze" : ""}">
            <div style="display:flex;align-items:center;gap:12px">
              <span class="pos">${i + 1}</span>
              <span class="who">${esc(e.username)}${e.username === state.username ? " (you)" : ""}</span>
            </div>
            <b>${e.score} pts</b>
          </div>`
          )
          .join("")}
      </div>
    </div>
  `;
}
