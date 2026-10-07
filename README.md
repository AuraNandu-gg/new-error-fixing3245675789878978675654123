# AuraQuest

Modern multiplayer trivia. No login — pick a unique username, invite friends with a room code, chat, add friends, and climb the leaderboard.

**Creator : AuraNandu**

## How to run

You need Python 3.8+ and the `websockets` package.

```bash
cd aura-quest
python3 server.py
```

Then open **http://localhost:3000** on every player's device.

Players on the same Wi-Fi can use your computer's local IP, for example `http://192.168.1.20:3000`.

To play with friends over the internet, share that address with a tunnel such as ngrok, or host the project on a VPS.

## How to play

1. Enter a username (3–16 characters). Two people cannot use the same name at the same time.
2. **Create room** and share the 5-letter code, or **Join** with a friend's code.
3. Chat in the lobby, add friends, tap **I'm ready**.
4. The host taps **Start quest**.
5. 8 multiple-choice questions, 15 seconds each. Faster correct answers score more.
6. Scores save to the global leaderboard.

## Features

- Unique usernames (no account / no password)
- Invite rooms (up to 8 players)
- Live chat
- Friend requests
- Persistent leaderboard and profiles (`data.json`)
- Modern dark UI
- Family-friendly general-knowledge questions
