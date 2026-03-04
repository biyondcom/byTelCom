# Telegram-Claude-Bridge (byTelCom)

A local Python framework that bridges Telegram and Claude Code CLI. Users send messages via Telegram, which are forwarded as prompts to Claude Code CLI. Responses and follow-up questions from Claude are sent back through Telegram. Only authorized users (whitelist) can communicate.

## Architecture

```
Telegram User → Telegram Bot API → Python Framework → Claude Code CLI (subprocess)
                                         ↕                    ↕
                                   SQLite DB            Local MCP Servers
                                (History/Whitelist)
```

## Project Structure

```
byTelCom/
├── config.yaml              # Configuration (bot token, whitelist, etc.)
├── main.py                  # Entry point
├── bot/
│   ├── telegram_handler.py  # Telegram bot logic, message handling
│   └── whitelist.py         # Whitelist authorization
├── claude/
│   └── cli_bridge.py        # Claude Code CLI subprocess management
├── storage/
│   └── database.py          # SQLite for history & sessions
├── requirements.txt
└── data/
    └── conversations.db     # SQLite DB (created automatically)
```

## Setup

### Prerequisites

- Python 3.11+
- [Claude Code CLI](https://docs.anthropic.com/en/docs/claude-code) installed and available in PATH
- A Telegram bot token from [@BotFather](https://t.me/BotFather)

### Installation

```bash
pip install -r requirements.txt
```

### Configuration

Edit `config.yaml`:

```yaml
telegram:
  bot_token: "YOUR_BOT_TOKEN_HERE"

whitelist:
  - 123456789  # Your Telegram user ID

claude:
  cli_path: ""       # Leave empty if claude is in PATH
  timeout: 300       # Seconds before timeout

session:
  timeout_minutes: 60  # Inactivity timeout before new session
```

To find your Telegram user ID, message [@userinfobot](https://t.me/userinfobot) on Telegram.

### Run

```bash
python main.py
```

## Bot Commands

| Command    | Description                        |
|------------|------------------------------------|
| `/start`   | Welcome message and help           |
| `/new`     | Start a new conversation           |
| `/history` | Show recent messages               |

## Features

- **Whitelist authorization** — only configured Telegram user IDs can interact
- **Session management** — conversations persist via Claude Code's built-in session system
- **Auto session expiry** — new session starts after configurable inactivity timeout
- **Message splitting** — long Claude responses are automatically split to fit Telegram's 4096-char limit
- **Persistent history** — all messages stored in SQLite for reference
- **Typing indicator** — shows "typing..." while Claude is processing

## License

MIT
