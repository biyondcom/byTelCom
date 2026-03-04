import logging

from telegram import Update
from telegram.constants import ChatAction, ParseMode
from telegram.ext import Application, CommandHandler, MessageHandler, ContextTypes, filters

from bot.whitelist import WhitelistChecker
from claude.cli_bridge import ClaudeBridge
from storage.database import (
    init_db,
    get_or_create_session,
    create_new_session,
    save_message,
    get_recent_messages,
)

logger = logging.getLogger(__name__)


def split_message(text: str, max_len: int = 4096) -> list[str]:
    """Split text into chunks that fit within Telegram's message limit."""
    if len(text) <= max_len:
        return [text]

    chunks = []
    while text:
        if len(text) <= max_len:
            chunks.append(text)
            break
        # Try to split at last newline within limit
        split_at = text.rfind("\n", 0, max_len)
        if split_at == -1:
            split_at = max_len
        chunks.append(text[:split_at])
        text = text[split_at:].lstrip("\n")
    return chunks


class TelegramBot:
    def __init__(self, config: dict):
        self._config = config
        self._whitelist = WhitelistChecker(config["whitelist"])
        self._bridge = ClaudeBridge(
            cli_path=config["claude"].get("cli_path", ""),
            timeout=config["claude"].get("timeout", 300),
        )
        self._max_msg_len = config["telegram"].get("max_message_length", 4096)
        self._session_timeout = config["session"].get("timeout_minutes", 60)

    async def _check_auth(self, update: Update) -> bool:
        if self._whitelist.is_authorized(update.effective_user.id):
            return True
        await update.message.reply_text("You are not authorized to use this bot.")
        return False

    async def _cmd_start(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not await self._check_auth(update):
            return
        await update.message.reply_text(
            "Hello! I'm a bridge to Claude Code.\n"
            "Send me any message and I'll forward it to Claude.\n\n"
            "Commands:\n"
            "/new - Start a new conversation\n"
            "/history - Show recent messages"
        )

    async def _cmd_new(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not await self._check_auth(update):
            return
        user_id = update.effective_user.id
        _, session_id = await create_new_session(user_id)
        await update.message.reply_text(f"New conversation started (session: {session_id}).")

    async def _cmd_history(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not await self._check_auth(update):
            return
        messages = await get_recent_messages(update.effective_user.id, limit=10)
        if not messages:
            await update.message.reply_text("No message history yet.")
            return

        lines = []
        for msg in messages:
            role = "You" if msg["role"] == "user" else "Claude"
            preview = msg["content"][:200]
            if len(msg["content"]) > 200:
                preview += "..."
            lines.append(f"[{role}] {preview}")

        text = "\n\n".join(lines)
        for chunk in split_message(text, self._max_msg_len):
            await update.message.reply_text(chunk)

    async def _handle_message(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not await self._check_auth(update):
            return

        user_id = update.effective_user.id
        user_text = update.message.text

        # Get or create session
        conv_id, session_id = await get_or_create_session(user_id, self._session_timeout)

        # Save user message
        await save_message(conv_id, "user", user_text)

        # Send typing indicator
        await update.message.chat.send_action(ChatAction.TYPING)

        # Call Claude
        response = await self._bridge.send_prompt(user_text, session_id)

        # Save assistant response
        await save_message(conv_id, "assistant", response)

        # Send response back (split if needed)
        chunks = split_message(response, self._max_msg_len)
        for chunk in chunks:
            await update.message.reply_text(chunk)

    def run(self):
        app = Application.builder().token(self._config["telegram"]["bot_token"]).build()

        # Register handlers
        app.add_handler(CommandHandler("start", self._cmd_start))
        app.add_handler(CommandHandler("new", self._cmd_new))
        app.add_handler(CommandHandler("history", self._cmd_history))
        app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, self._handle_message))

        # Initialize database before polling
        import asyncio

        whitelist_ids = self._config["whitelist"]

        async def post_init(application):
            await init_db()
            for user_id in whitelist_ids:
                try:
                    await application.bot.send_message(
                        chat_id=user_id,
                        text="Bot ist gestartet und bereit, Aufgaben zu empfangen.",
                    )
                except Exception as e:
                    logger.warning("Could not send startup message to %d: %s", user_id, e)
            logger.info("Startup messages sent.")

        app.post_init = post_init

        logger.info("Bot starting...")
        app.run_polling()
