#!/usr/bin/env python3
"""AuraQuest — multiplayer arena. Collect orbs with friends."""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import math
import os
import random
import re
import secrets
from pathlib import Path

import websockets

ROOT = Path(__file__).resolve().parent


def find_public():
    candidates = [
        ROOT / "public",
        ROOT / "aura-quest-upload" / "public",
        ROOT / "aura-quest" / "public",
    ]
    if ROOT.is_dir():
        for folder in ROOT.iterdir():
            if folder.is_dir() and (folder / "public" / "index.html").is_file():
                candidates.append(folder / "public")
    for path in candidates:
        if (path / "index.html").is_file():
            return path
    if (ROOT / "index.html").is_file():
        return ROOT
    return ROOT / "public"


PUBLIC = find_public()
DATA_FILE = ROOT / "data.json"
HTTP_PORT = int(os.environ.get("PORT", "3000"))
print("AuraQuest files:", ROOT)
print("AuraQuest public:", PUBLIC, "index.html exists:", (PUBLIC / "index.html").is_file())

W, H = 1200, 700
SPEED = 280
PLAYER_R = 18
ROUND_SEC = 75
COLORS = ["#8b7cff", "#3ee0c8", "#ffd166", "#ff6b8a", "#7cdcfe", "#c4f25a", "#ff9f6b", "#f0abfc"]


def load_data():
    try:
        raw = json.loads(DATA_FILE.read_text())
    except Exception:
        raw = {"profiles": {}, "leaderboard": [], "authVersion": 2}
    # Old name-only accounts locked usernames. Version 2 is real login, so those names are free again.
    if raw.get("authVersion") != 2:
        raw = {"profiles": {}, "leaderboard": [], "authVersion": 2}
        try:
            DATA_FILE.write_text(json.dumps(raw, indent=2))
        except Exception:
            pass
        print("Cleared old taken usernames. Players must create accounts again.")
    raw.setdefault("profiles", {})
    raw.setdefault("leaderboard", [])
    raw.setdefault("adminTokens", [])
    return raw


data = load_data()
online_names = set()
clients = {}
rooms = {}


def save_data():
    try:
        DATA_FILE.write_text(json.dumps(data, indent=2))
    except Exception as e:
        print("save_data failed:", e)


ADMIN_PASSWORD = "AuraNandu_67_"
RANKS = ["Player", "Helper", "Builder", "VIP", "Star", "Moderator", "Admin", "Owner"]


def ensure_profile(username):
    if username not in data["profiles"]:
        data["profiles"][username] = {
            "friends": [],
            "requestsIn": [],
            "requestsOut": [],
            "totalScore": 0,
            "gamesPlayed": 0,
            "bestScore": 0,
            "passwordHash": "",
            "salt": "",
            "token": "",
        }
    p = data["profiles"][username]
    p.setdefault("passwordHash", "")
    p.setdefault("salt", "")
    p.setdefault("token", "")
    p.setdefault("rank", "Player")
    if p.get("rank") not in RANKS:
        p["rank"] = "Player"
    return p


def hash_password(password, salt):
    return hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt.encode("utf-8"), 120_000).hex()


def valid_name(username):
    return bool(re.match(r"^[A-Za-z0-9_]{3,16}$", username))


def find_profile_name(username):
    return next((n for n in data["profiles"] if n.lower() == username.lower()), None)


def issue_session(username):
    p = ensure_profile(username)
    p["token"] = secrets.token_urlsafe(24)
    save_data()
    return p["token"]


def auth_ok(username, token):
    name = find_profile_name(username)
    if not name:
        return None
    p = data["profiles"][name]
    if not token or not p.get("token") or not hmac.compare_digest(p["token"], token):
        return None
    return name


def user_card(name):
    p = data["profiles"].get(name, {})
    return {
        "username": name,
        "rank": p.get("rank") or "Player",
        "online": name.lower() in online_names,
    }


def directory_public():
    taken = [user_card(n) for n in sorted(data["profiles"], key=str.lower)]
    online = [c for c in taken if c["online"]]
    return {"online": online, "taken": taken, "ranks": RANKS}


async def broadcast_directory():
    payload = {"type": "directory", **directory_public()}
    for ws in list(clients):
        await send(ws, payload)


def public_profile(username):
    p = ensure_profile(username)
    return {
        "username": username,
        "totalScore": p["totalScore"],
        "gamesPlayed": p["gamesPlayed"],
        "bestScore": p["bestScore"],
        "friends": list(p["friends"]),
        "requestsIn": list(p["requestsIn"]),
        "requestsOut": list(p["requestsOut"]),
        "rank": p.get("rank") or "Player",
    }


def rename_profile(old, new):
    p = ensure_profile(old)
    data["profiles"][new] = p
    if old in data["profiles"] and old != new:
        del data["profiles"][old]
    for name, prof in data["profiles"].items():
        for key in ("friends", "requestsIn", "requestsOut"):
            prof[key] = [new if n == old else n for n in prof[key]]
    for row in data["leaderboard"]:
        if row.get("username") == old:
            row["username"] = new
    save_data()


def make_code():
    chars = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
    while True:
        code = "".join(random.choice(chars) for _ in range(5))
        if code not in rooms:
            return code


def room_public(room):
    return {
        "code": room["code"],
        "host": room["host"],
        "players": [
            {
                "username": n,
                "score": room["scores"].get(n, 0),
                "ready": bool(room["ready"].get(n)),
            }
            for n in room["players"]
        ],
        "state": room["state"],
        "chat": room["chat"][-80:],
        "timeLeft": room.get("timeLeft", 0),
    }


async def send(ws, payload):
    try:
        await ws.send(json.dumps(payload))
    except Exception:
        pass


async def send_user(username, payload):
    for ws, u in list(clients.items()):
        if u.get("username") == username:
            await send(ws, payload)


async def emit_room(room, payload=None):
    msg = payload or {"type": "room", "room": room_public(room)}
    for ws, u in list(clients.items()):
        if u.get("room") == room["code"]:
            await send(ws, msg)


def update_leaderboard(username):
    p = ensure_profile(username)
    found = next((e for e in data["leaderboard"] if e["username"] == username), None)
    row = {
        "username": username,
        "totalScore": p["totalScore"],
        "bestScore": p["bestScore"],
        "gamesPlayed": p["gamesPlayed"],
    }
    if found:
        found.update(row)
    else:
        data["leaderboard"].append(row)
    data["leaderboard"].sort(key=lambda e: (-e["totalScore"], -e["bestScore"]))
    data["leaderboard"] = data["leaderboard"][:50]
    save_data()


def spawn_orb(orbs):
    kind = random.choices(["small", "mid", "rare"], weights=[70, 24, 6])[0]
    spec = {"small": (8, 1, "#9be7ff"), "mid": (12, 3, "#ffd166"), "rare": (16, 8, "#f0abfc")}
    r, val, color = spec[kind]
    orbs.append(
        {
            "id": random.randint(1, 1_000_000_000),
            "x": random.uniform(40, W - 40),
            "y": random.uniform(40, H - 40),
            "r": r,
            "val": val,
            "color": color,
        }
    )


def spawn_player(room, name, index):
    room["bodies"][name] = {
        "x": 80 + (index % 4) * 140,
        "y": 80 + (index // 4) * 140,
        "keys": {"u": False, "d": False, "l": False, "r": False},
        "color": COLORS[index % len(COLORS)],
        "vx": 0,
        "vy": 0,
    }
    room["scores"][name] = 0


async def leave_room(ws):
    u = clients.get(ws)
    if not u or not u.get("room"):
        return
    code = u["room"]
    room = rooms.get(code)
    u["room"] = None
    if not room:
        return
    if u["username"] in room["players"]:
        room["players"].remove(u["username"])
    room["ready"].pop(u["username"], None)
    room["bodies"].pop(u["username"], None)
    room["chat"].append({"from": "System", "text": f"{u['username']} left the room.", "ts": 0})
    if not room["players"]:
        room["alive"] = False
        rooms.pop(code, None)
        return
    if room["host"] == u["username"]:
        room["host"] = room["players"][0]
    await emit_room(room)


def accept_friend(a, b):
    pa, pb = ensure_profile(a), ensure_profile(b)
    pa["requestsIn"] = [n for n in pa["requestsIn"] if n != b]
    pa["requestsOut"] = [n for n in pa["requestsOut"] if n != b]
    pb["requestsIn"] = [n for n in pb["requestsIn"] if n != a]
    pb["requestsOut"] = [n for n in pb["requestsOut"] if n != a]
    if b not in pa["friends"]:
        pa["friends"].append(b)
    if a not in pb["friends"]:
        pb["friends"].append(a)
    save_data()


async def game_loop(room):
    dt = 1 / 30
    while room.get("alive") and room["state"] == "playing":
        for name, body in list(room["bodies"].items()):
            dx = (1 if body["keys"].get("r") else 0) - (1 if body["keys"].get("l") else 0)
            dy = (1 if body["keys"].get("d") else 0) - (1 if body["keys"].get("u") else 0)
            if dx or dy:
                mag = math.hypot(dx, dy)
                body["vx"] = SPEED * dx / mag
                body["vy"] = SPEED * dy / mag
            else:
                body["vx"] = 0
                body["vy"] = 0
            body["x"] += body["vx"] * dt
            body["y"] += body["vy"] * dt
            body["x"] = max(PLAYER_R, min(W - PLAYER_R, body["x"]))
            body["y"] = max(PLAYER_R, min(H - PLAYER_R, body["y"]))
        kept = []
        for orb in room["orbs"]:
            taken = False
            for name, body in room["bodies"].items():
                if math.hypot(body["x"] - orb["x"], body["y"] - orb["y"]) < PLAYER_R + orb["r"]:
                    room["scores"][name] = room["scores"].get(name, 0) + orb["val"]
                    taken = True
                    break
            if not taken:
                kept.append(orb)
        room["orbs"] = kept
        while len(room["orbs"]) < 18:
            spawn_orb(room["orbs"])
        room["timeLeft"] = max(0, room["endsAt"] - asyncio.get_event_loop().time())
        await emit_room(
            room,
            {
                "type": "frame",
                "w": W,
                "h": H,
                "timeLeft": room["timeLeft"],
                "players": [
                    {
                        "username": n,
                        "x": round(room["bodies"][n]["x"], 1),
                        "y": round(room["bodies"][n]["y"], 1),
                        "vx": round(room["bodies"][n].get("vx", 0), 1),
                        "vy": round(room["bodies"][n].get("vy", 0), 1),
                        "color": room["bodies"][n]["color"],
                        "score": room["scores"].get(n, 0),
                    }
                    for n in room["players"]
                    if n in room["bodies"]
                ],
                "orbs": room["orbs"],
            },
        )
        if room["timeLeft"] <= 0:
            await finish_game(room)
            return
        await asyncio.sleep(dt)


async def start_round(room):
    room["state"] = "playing"
    room["scores"] = {n: 0 for n in room["players"]}
    room["bodies"] = {}
    room["orbs"] = []
    for i, n in enumerate(room["players"]):
        spawn_player(room, n, i)
    while len(room["orbs"]) < 18:
        spawn_orb(room["orbs"])
    room["endsAt"] = asyncio.get_event_loop().time() + ROUND_SEC
    room["timeLeft"] = ROUND_SEC
    room["chat"].append({"from": "System", "text": "Go! Grab orbs. WASD or arrows to move.", "ts": 0})
    await emit_room(room, {"type": "matchStart", "seconds": ROUND_SEC})
    await emit_room(room)
    room["task"] = asyncio.create_task(game_loop(room))


async def finish_game(room):
    if room["state"] != "playing":
        return
    room["state"] = "results"
    ranking = sorted(
        [{"username": n, "score": room["scores"].get(n, 0)} for n in room["players"]],
        key=lambda x: -x["score"],
    )
    for n in room["players"]:
        p = ensure_profile(n)
        s = room["scores"].get(n, 0)
        p["totalScore"] += s
        p["gamesPlayed"] += 1
        if s > p["bestScore"]:
            p["bestScore"] = s
        update_leaderboard(n)
    save_data()
    room["chat"].append({"from": "System", "text": "Time! Check the results.", "ts": 0})
    await emit_room(room, {"type": "results", "ranking": ranking, "scores": room["scores"]})
    await emit_room(room)
    await asyncio.sleep(10)
    if rooms.get(room["code"]) is room:
        room["state"] = "lobby"
        room["ready"] = {}
        await emit_room(room)


async def release_name(username, except_ws=None):
    for sock, u in list(clients.items()):
        if sock is except_ws:
            continue
        if u.get("username") == username:
            if u.get("room"):
                await leave_room(sock)
            u["username"] = None
            await send(sock, {"type": "kicked", "text": "This account logged in somewhere else."})
    online_names.discard(username.lower())


async def set_rank(target, rank):
    ensure_profile(target)["rank"] = rank
    save_data()
    await send_user(target, {"type": "profile", "profile": public_profile(target)})
    await send_user(target, {"type": "toast", "text": f"Your rank is now {rank}."})
    await broadcast_directory()


def is_staff(username):
    return (ensure_profile(username).get("rank") or "Player") in ("Admin", "Owner")


async def run_command(ws, username, text, admin_ok=False):
    parts = text.strip().split()
    if not parts:
        return
    cmd = parts[0].lower()
    if cmd in ("/help", "/commands"):
        return await send(ws, {"type": "toast", "text": "Commands: /rank Name Rank, /players, /taken, /kick Name"})
    if cmd == "/players":
        names = ", ".join(sorted(n for n in {u.get("username") for u in clients.values()} if n)) or "none"
        return await send(ws, {"type": "toast", "text": "Online: " + names})
    if cmd == "/taken":
        names = ", ".join(sorted(data["profiles"], key=str.lower)) or "none"
        return await send(ws, {"type": "toast", "text": "Taken: " + names})
    if not admin_ok and not is_staff(username):
        return await send(ws, {"type": "toast", "text": "That command needs Admin or Owner rank, or the admin panel."})
    if cmd == "/rank" and len(parts) >= 3:
        target = find_profile_name(parts[1])
        rank = parts[2].capitalize()
        if rank.lower() == "mod":
            rank = "Moderator"
        if not target:
            return await send(ws, {"type": "toast", "text": "No account with that name."})
        if rank not in RANKS:
            return await send(ws, {"type": "toast", "text": "Ranks: " + ", ".join(RANKS)})
        await set_rank(target, rank)
        return await send(ws, {"type": "toast", "text": f"{target} is now {rank}."})
    if cmd == "/kick" and len(parts) >= 2:
        target = find_profile_name(parts[1])
        if not target:
            return await send(ws, {"type": "toast", "text": "No account with that name."})
        await release_name(target)
        await broadcast_directory()
        return await send(ws, {"type": "toast", "text": f"Kicked {target}."})
    return await send(ws, {"type": "toast", "text": "Unknown command. Try /help"})


async def handle_msg(ws, msg):
    u = clients.get(ws)
    typ = msg.get("type")

    if typ in ("signup", "login", "resume", "register"):
        if typ == "register":
            typ = "signup"
        try:
            username = str(msg.get("username") or "").strip()
            password = str(msg.get("password") or "")
            token = str(msg.get("token") or "")
            if typ == "resume":
                name = auth_ok(username, token)
                if not name:
                    return await send(ws, {"type": "authed", "ok": False, "error": "Please log in again."})
                username = name
            else:
                if not valid_name(username):
                    return await send(ws, {"type": "authed", "ok": False, "error": "Username must be 3–16 letters, numbers, or _ . No spaces."})
                if len(password) < 4 or len(password) > 32:
                    return await send(ws, {"type": "authed", "ok": False, "error": "Password must be 4–32 characters."})
                existing = find_profile_name(username)
                if typ == "signup":
                    if existing:
                        return await send(ws, {"type": "authed", "ok": False, "error": "That username is taken. Log in, or pick another."})
                    salt = secrets.token_hex(16)
                    p = ensure_profile(username)
                    p["passwordHash"] = hash_password(password, salt)
                    p["salt"] = salt
                    p["rank"] = "Player"
                else:
                    if not existing:
                        return await send(ws, {"type": "authed", "ok": False, "error": "No account with that name. Tap Create account."})
                    username = existing
                    p = data["profiles"][username]
                    if not p.get("passwordHash") or not hmac.compare_digest(p["passwordHash"], hash_password(password, p.get("salt") or "")):
                        return await send(ws, {"type": "authed", "ok": False, "error": "Wrong password."})
            await release_name(username, except_ws=ws)
            online_names.add(username.lower())
            clients[ws] = {"username": username, "room": None}
            token = issue_session(username)
            await broadcast_directory()
            return await send(
                ws,
                {
                    "type": "authed",
                    "ok": True,
                    "token": token,
                    "profile": public_profile(username),
                    "leaderboard": data["leaderboard"],
                    "directory": directory_public(),
                },
            )
        except Exception as e:
            print("auth error:", e)
            return await send(ws, {"type": "authed", "ok": False, "error": "Account could not be saved. Try again."})

    if typ == "register":
        return await send(ws, {"type": "authed", "ok": False, "error": "Please create an account or log in."})

    if not u or not u.get("username"):
        return await send(ws, {"type": "error", "error": "Register first"})

    if typ == "logout":
        name = u["username"]
        p = ensure_profile(name)
        p["token"] = ""
        save_data()
        await leave_room(ws)
        online_names.discard(name.lower())
        u["username"] = None
        await broadcast_directory()
        return await send(ws, {"type": "loggedOut"})

    if typ == "changeName":
        new = str(msg.get("username") or "").strip()
        old = u["username"]
        if not re.match(r"^[A-Za-z0-9 _]{3,16}$", new) or len(new.strip()) < 3:
            return await send(ws, {"type": "renamed", "ok": False, "error": "Username must be 3–16 letters, numbers, spaces or _"})
        if new == old:
            return await send(ws, {"type": "renamed", "ok": True, "profile": public_profile(old), "leaderboard": data["leaderboard"]})
        if new.lower() in online_names:
            return await send(ws, {"type": "renamed", "ok": False, "error": "That username is already being used right now."})
        taken = next((n for n in data["profiles"] if n.lower() == new.lower() and n != old), None)
        if taken:
            return await send(ws, {"type": "renamed", "ok": False, "error": "That username is already taken. Pick another."})
        rename_profile(old, new)
        online_names.discard(old.lower())
        online_names.add(new.lower())
        u["username"] = new
        if u.get("room") and rooms.get(u["room"]):
            room = rooms[u["room"]]
            room["players"] = [new if n == old else n for n in room["players"]]
            if room.get("host") == old:
                room["host"] = new
            if old in room.get("ready", {}):
                room["ready"][new] = room["ready"].pop(old)
            if old in room.get("scores", {}):
                room["scores"][new] = room["scores"].pop(old)
            if old in room.get("bodies", {}):
                room["bodies"][new] = room["bodies"].pop(old)
            room["chat"].append({"from": "System", "text": f"{old} is now {new}.", "ts": 0})
            await emit_room(room)
        await broadcast_directory()
        return await send(
            ws,
            {"type": "renamed", "ok": True, "profile": public_profile(new), "leaderboard": data["leaderboard"]},
        )

    if typ == "createRoom":
        if u["room"]:
            return await send(ws, {"type": "created", "ok": False, "error": "Leave your current room first"})
        code = make_code()
        room = {
            "code": code,
            "host": u["username"],
            "players": [u["username"]],
            "ready": {},
            "scores": {},
            "bodies": {},
            "orbs": [],
            "chat": [{"from": "System", "text": f"{u['username']} created the room. Share code {code}!", "ts": 0}],
            "state": "lobby",
            "alive": True,
            "task": None,
        }
        rooms[code] = room
        u["room"] = code
        return await send(ws, {"type": "created", "ok": True, "room": room_public(room)})

    if typ == "joinRoom":
        code = str(msg.get("code") or "").upper().strip()
        room = rooms.get(code)
        if not room:
            return await send(ws, {"type": "joined", "ok": False, "error": "Room not found"})
        if room["state"] != "lobby":
            return await send(ws, {"type": "joined", "ok": False, "error": "Match already in progress"})
        if u["username"] in room["players"]:
            return await send(ws, {"type": "joined", "ok": False, "error": "Already in room"})
        if len(room["players"]) >= 8:
            return await send(ws, {"type": "joined", "ok": False, "error": "Room is full (max 8)"})
        if u["room"]:
            return await send(ws, {"type": "joined", "ok": False, "error": "Leave your current room first"})
        room["players"].append(u["username"])
        room["chat"].append({"from": "System", "text": f"{u['username']} joined!", "ts": 0})
        u["room"] = code
        await emit_room(room)
        return await send(ws, {"type": "joined", "ok": True, "room": room_public(room)})

    if typ == "leaveRoom":
        await leave_room(ws)
        return

    if typ == "chat":
        if not u.get("room"):
            return
        room = rooms.get(u["room"])
        if not room:
            return
        text = str(msg.get("text") or "").strip()[:200]
        if not text:
            return
        if text.startswith("/"):
            token = str(msg.get("adminToken") or "")
            admin_ok = token in data.get("adminTokens", [])
            await run_command(ws, u["username"], text, admin_ok)
            return
        room["chat"].append({"from": u["username"], "text": text, "ts": 0})
        await emit_room(room)
        return

    if typ == "ready":
        if not u.get("room"):
            return
        room = rooms.get(u["room"])
        if not room or room["state"] != "lobby":
            return
        room["ready"][u["username"]] = bool(msg.get("ready"))
        await emit_room(room)
        return

    if typ == "startGame":
        if not u.get("room"):
            return
        room = rooms.get(u["room"])
        if not room or room["host"] != u["username"] or room["state"] != "lobby":
            return
        await start_round(room)
        return

    if typ == "input":
        if not u.get("room"):
            return
        room = rooms.get(u["room"])
        if not room or room["state"] != "playing":
            return
        body = room["bodies"].get(u["username"])
        if not body:
            return
        keys = msg.get("keys") or {}
        body["keys"] = {
            "u": bool(keys.get("u")),
            "d": bool(keys.get("d")),
            "l": bool(keys.get("l")),
            "r": bool(keys.get("r")),
        }
        return

    if typ == "friendRequest":
        target = str(msg.get("target") or "").strip()
        if not target or target == u["username"]:
            return
        if target not in data["profiles"]:
            return await send(ws, {"type": "toast", "text": "That player hasn't played yet."})
        me = ensure_profile(u["username"])
        them = ensure_profile(target)
        if target in me["friends"]:
            return await send(ws, {"type": "toast", "text": "You're already friends!"})
        if u["username"] in them["requestsIn"] or target in me["requestsOut"]:
            return await send(ws, {"type": "toast", "text": "Request already sent."})
        if target in me["requestsIn"]:
            accept_friend(u["username"], target)
            await send(ws, {"type": "profile", "profile": public_profile(u["username"])})
            await send_user(target, {"type": "profile", "profile": public_profile(target)})
            await send_user(target, {"type": "toast", "text": f"{u['username']} accepted your friend request!"})
            await send(ws, {"type": "toast", "text": f"You and {target} are now friends!"})
            return
        me["requestsOut"].append(target)
        them["requestsIn"].append(u["username"])
        save_data()
        await send(ws, {"type": "profile", "profile": public_profile(u["username"])})
        await send_user(target, {"type": "profile", "profile": public_profile(target)})
        await send_user(target, {"type": "toast", "text": f"{u['username']} sent you a friend request!"})
        await send(ws, {"type": "toast", "text": f"Friend request sent to {target}"})
        return

    if typ == "acceptFriend":
        target = str(msg.get("target") or "").strip()
        accept_friend(u["username"], target)
        await send(ws, {"type": "profile", "profile": public_profile(u["username"])})
        await send_user(target, {"type": "profile", "profile": public_profile(target)})
        await send_user(target, {"type": "toast", "text": f"{u['username']} accepted your friend request!"})
        await send(ws, {"type": "toast", "text": f"You and {target} are now friends!"})
        return

    if typ == "declineFriend":
        target = str(msg.get("target") or "").strip()
        me = ensure_profile(u["username"])
        them = ensure_profile(target)
        me["requestsIn"] = [n for n in me["requestsIn"] if n != target]
        them["requestsOut"] = [n for n in them["requestsOut"] if n != u["username"]]
        save_data()
        await send(ws, {"type": "profile", "profile": public_profile(u["username"])})
        await send_user(target, {"type": "profile", "profile": public_profile(target)})
        return

    if typ == "getLeaderboard":
        await send(ws, {"type": "leaderboard", "leaderboard": data["leaderboard"]})
        return

    if typ == "adminLogin":
        password = str(msg.get("password") or "")
        if not hmac.compare_digest(password, ADMIN_PASSWORD):
            return await send(ws, {"type": "admin", "ok": False, "error": "Wrong admin password."})
        token = secrets.token_urlsafe(24)
        data.setdefault("adminTokens", [])
        data["adminTokens"] = (data["adminTokens"] + [token])[-8:]
        save_data()
        return await send(ws, {"type": "admin", "ok": True, "adminToken": token, "directory": directory_public()})

    if typ == "adminSetRank":
        token = str(msg.get("adminToken") or "")
        if token not in data.get("adminTokens", []):
            return await send(ws, {"type": "admin", "ok": False, "error": "Admin panel locked. Enter the password again."})
        target = find_profile_name(str(msg.get("username") or "").strip())
        rank = str(msg.get("rank") or "")
        if not target:
            return await send(ws, {"type": "admin", "ok": False, "error": "That account does not exist."})
        if rank not in RANKS:
            return await send(ws, {"type": "admin", "ok": False, "error": "Pick a rank from the list."})
        ensure_profile(target)["rank"] = rank
        save_data()
        await set_rank(target, rank)
        return await send(ws, {"type": "admin", "ok": True, "directory": directory_public(), "text": f"{target} is now {rank}."})


async def handler(ws):
    clients[ws] = {}
    try:
        async for raw in ws:
            try:
                msg = json.loads(raw)
            except Exception:
                continue
            try:
                await handle_msg(ws, msg)
            except Exception as e:
                import traceback
                traceback.print_exc()
                await send(ws, {"type": "toast", "text": "Something went wrong."})
                print("handler error:", e)
    finally:
        u = clients.get(ws)
        if u:
            await leave_room(ws)
            if u.get("username"):
                online_names.discard(u["username"].lower())
        clients.pop(ws, None)
        await broadcast_directory()


MIME = {
    ".html": "text/html; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".js": "text/javascript; charset=utf-8",
    ".json": "application/json",
    ".svg": "image/svg+xml",
    ".png": "image/png",
    ".ico": "image/x-icon",
}


def file_response(path: Path, status=200, reason="OK"):
    from websockets.datastructures import Headers
    from websockets.http11 import Response

    body = path.read_bytes() if path.is_file() else b"Not found"
    ctype = MIME.get(path.suffix.lower(), "application/octet-stream") if path.is_file() else "text/plain"
    headers = Headers(
        {
            "Content-Type": ctype,
            "Content-Length": str(len(body)),
            "Cache-Control": "no-store",
            "Connection": "close",
        }
    )
    return Response(status, reason, headers, body)


async def process_request(connection, request):
    path = request.path.split("?", 1)[0]
    if path in ("/healthz", "/health"):
        from websockets.datastructures import Headers
        from websockets.http11 import Response

        body = b"ok"
        return Response(200, "OK", Headers({"Content-Type": "text/plain", "Content-Length": str(len(body))}), body)
    if path in ("/ws", "/socket"):
        return None
    if path == "/":
        path = "/index.html"
    rel = path.lstrip("/")
    target = (PUBLIC / rel).resolve()
    try:
        target.relative_to(PUBLIC.resolve())
    except ValueError:
        return file_response(PUBLIC / "index.html", 404, "Not Found")
    if target.is_file():
        return file_response(target)
    return file_response(PUBLIC / "index.html", 404, "Not Found")


async def main():
    print(f"AuraQuest → http://localhost:{HTTP_PORT}")
    async with websockets.serve(
        handler,
        "0.0.0.0",
        HTTP_PORT,
        process_request=process_request,
        ping_interval=20,
        ping_timeout=20,
    ):
        await asyncio.Future()


if __name__ == "__main__":
    asyncio.run(main())
