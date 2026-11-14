# Telegram approvals

Every human gate (audit scenarios / datasets, public dataset pick, regulation change, a chat agent's tool
approval) is also sent to Telegram with **Approve / Reject / Open in app**. Pressing a button records the
decision exactly like the UI (`decided_by: telegram:<username>`) and resumes the agent. How it works:
[backend § Telegram approvals](../services/backend-systems.md#telegram-approvals).

## Setup (5 minutes)

1. **Create the bot.** In Telegram, open [@BotFather](https://t.me/BotFather), send `/newbot`, pick a name and a
   username ending in `bot`. BotFather answers with a token like `123456789:AA...`.
2. **Get your chat id.** Either:
   - message [@userinfobot](https://t.me/userinfobot): it answers your numeric id (= the chat id of your private
     chat with the bot); or
   - start the stack with the token set (step 3), open your bot, send `/chatid`: it answers the chat id; or
   - send the bot any message, then open `https://api.telegram.org/bot<token>/getUpdates` and read
     `message.chat.id` (only while the backend is not polling).

   For a team group, add the bot to the group and use the group's id (negative, e.g. `-100...`).
3. **Configure** the root `.env` (never commit it):

   ```dotenv
   TELEGRAM_BOT_TOKEN=123456789:AA...
   # comma-separated: every chat that receives gates and may decide them
   TELEGRAM_CHAT_ID=111111111,-1002222222222
   # where "Open in app" links point (a public URL also gets a link button)
   APP_PUBLIC_URL=http://localhost:8080
   ```

4. **Restart the backend:** `docker compose --env-file .env -f mnamon/docker-compose.yaml up -d backend`.
   The log shows `telegram_polling_started`. Press **Start** in the bot's chat once (bots cannot message a user
   first).

## Use

- A gate arrives as one compact message: system, gate, 2-3 key numbers, the link to the audit step.
- **Approve** records the approval; the message changes to "✅ Approved by @you".
- **Reject** asks for a reason category (buttons), then for a comment (reply to the bot's message; `-` skips).
- A gate already decided (in the app or by a teammate) answers "Already decided by X".
- Only the chats in `TELEGRAM_CHAT_ID` can decide; buttons pressed anywhere else are refused.

## Modes

- **Long polling** (default): the backend calls `getUpdates`; no public URL needed.
- **Webhook** (optional): set `TELEGRAM_WEBHOOK_URL` to the public https URL of the backend's
  `/telegram/webhook` and `TELEGRAM_WEBHOOK_SECRET` (any random string); the backend registers it at start.

No token = Telegram is off and everything else works as before.

## After the event

Revoke the token (`/revoke` in @BotFather) or delete the bot, and clear `TELEGRAM_*` from `.env` on a borrowed
machine.
