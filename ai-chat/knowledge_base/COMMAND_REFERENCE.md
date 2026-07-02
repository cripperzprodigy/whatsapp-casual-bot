# Command Reference

This document outlines the commands available to users, administrators, and the bot owner. Commands are dynamically filtered in the !help menu based on the user's role.

## Common Commands (All Users)
| Command | Role | Description | Example |
|---|---|---|---|
| !a <text> | User | Ask the AI a question. | !a What is the capital of France? |
| !search <query> | User | Quick search the web for information. | !search current weather in Tokyo |
| !s <query> | User | Search the web with iterative AI refinement. | !s deep dive into quantum computing |
| !summary | User | Summarize replied text or recent chat history. | !summary |
| !ping | User | Check bot status. | !ping |
| !help | User | Show the dynamic command menu. | !help |
| !t <lang> <text> | User | Translate text. | !t es Hello world |
| !t auto <text> | User | Translate to default language. | !t auto Hola |
| !lang set <code> | User | (DM Only) Set preferred language. | !lang set fr |
| !lang reset | User | (DM Only) Revert preferred language. | !lang reset |
| !task add <desc> | User | Add a task. | !task add Buy groceries |
| !sc <query> | User | 🕷️ Deep Crawl Search (if enabled by admin). | !sc current AI news |
| !task list | User | List tasks. | !task list |
| !task done <id> | User | Complete a task. | !task done 1 |
| !note add <text> | User | Add a note. | !note add Wifi pass: 1234 |
| !note list | User | List notes. | !note list |

## Admin Commands
| Command | Role | Description | Example |
|---|---|---|---|
| !chatty <on|off> | Admin | Toggle continuous AI conversation in the current group. | !chatty on |
| !chatty_freq <val> | Admin | Set AI response frequency. | !chatty_freq 5 |
| !chatty_burst <val> | Admin | Set AI burst count. | !chatty_burst 2 |
| !chatty_delay <min> <max> | Admin | Set human-like delay for AI responses. | !chatty_delay 2 5 |
| !chatty_mode <mode> | Admin | Set delay strategy (debounce or throttle). | !chatty_mode debounce |
| !chatty_status | Admin | View current AI chatter settings for the group. | !chatty_status |
| !auto <on|off> | Admin | Toggle auto-translate for this chat. | !auto on |
| !auto global | Admin | Reset auto-translate for this chat to global defaults. | !auto global |
| !target <lang> | Admin | Set target language for translation. | !target es |
| !ignore <add|remove> <lang> | Admin | Manage translation ignore list. | !ignore add id |
| !ignore global | Admin | Reset translation ignore list to defaults. | !ignore global |
| !contacts list | Admin | View group contacts. | !contacts list |
| !pm group <text> | Admin | Send a direct message to the current group. | !pm group Hello everyone |
| !pm @user <text> | Admin | Send a direct message to a specific user. | !pm @1234567890 Hello |
| !broadcast <msg> | Admin | Send a message to all chats. | !broadcast System maintenance at 12AM |
| !stats | Admin | View system statistics. | !stats |
| !botid | Admin | Show bot identity status. | !botid |

## Owner Commands
| Command | Role | Description | Example |
|---|---|---|---|
| !search_toggle <type> <status> | Owner | 🔒 Unified search feature toggle (Primary command). Types: `agentic`, `deep`. Status: `on`, `off`. | !search_toggle agentic off |
| !sc_toggle <on|off> | Owner | (Legacy) Toggle Deep Crawl feature. Use `!search_toggle deep <on|off>` instead. | !sc_toggle on |
| `!contacts global` | Owner | View all contacts globally. | `!contacts global` |
| `!contacts export` | Owner | Export global contact ledger. | `!contacts export` |
| `!resolve <@mention|group|global>` | Owner | Force resolve a user's phone number, scan the current group, or scan globally. | `!resolve @user` |
| `!pm global <text>` | Owner | DM all groups. | `!pm global Maintenance at midnight` |
| !pm flood <limit|interval> <val> | Owner | Configure PM flood settings. | !pm flood limit 10 |
| !owner <grant|revoke> <jid> | Owner | Manage bot Owners. | !owner grant 123@s.whatsapp.net |
| !admin <grant|revoke> <jid> | Owner | Manage bot Admins. | !admin grant 123@s.whatsapp.net |
| !owner\|admin list | Owner | List privileged users. | !owner list |
| !owner transfer <jid> | Owner | Transfer ownership of the bot. | !owner transfer 123@s.whatsapp.net |
| !whoami | Owner | Registers the bot's current WhatsApp LID (Required for @mentions to work). | !whoami |
| !forget-me | Owner | Clears the bot's known LIDs. | !forget-me |
| !globaltrans <on|off> | Owner | Toggle global auto-translate defaults. | !globaltrans on |
| !shutdown \| !restart | Owner | Bot lifecycle controls. | !shutdown |

---

## Unified Search Feature Toggles (CMD-HELP-SYNC-001)

The `!search_toggle` command provides a unified interface for controlling individual search features without restarting the bot.

### Command Syntax
```
!search_toggle <type> <status>
```

### Parameters
| Parameter | Valid Values | Description |
|-----------|--------------|-------------|
| `type` | `agentic`, `deep` | `agentic` = Agentic Search (!s), `deep` = Deep Crawl Search (!sc) |
| `status` | `on`, `off` | Enable or disable the specified search type |

### Examples

**Disable Agentic Search while keeping Deep Crawl enabled:**
```
!search_toggle agentic off
```
Response: `Agentic Search (!s) is now 🔴 DISABLED ❌`

**Re-enable Deep Crawl Search:**
```
!search_toggle deep on
```
Response: `Deep Crawl Search (!sc) is now 🟢 ENABLED ✅`

**View current status (no arguments):**
```
!search_toggle
```
Response:
```
Search Feature Status:
• Agentic Search (!s): 🟢 ON
• Deep Crawl Search (!sc): 🔴 OFF

Usage: !search_toggle <agentic|deep> <on|off>
```

### State Persistence & Precedence

1. **Environment Variable Override**: If `SEARCH_ENABLED=False` in `.env`, all search toggles are blocked (hard kill switch).
2. **Runtime Toggles**: When `SEARCH_ENABLED=True`, individual toggles control each search type.
3. **State File**: Toggles persist to `config_override.json` and survive bot restarts.

### Legacy Compatibility

- `!sc_toggle <on|off>`: Still works but maps to `!search_toggle deep <on|off>`
- `!admin toggle_agentic`: Still works but maps to `!search_toggle agentic on|off`
- `!admin toggle_crawl`: Still works but maps to `!search_toggle deep on|off`

Existing users should migrate to `!search_toggle` as the primary unified command.

### Security

- **Owner Only**: Only users listed in `OWNER_IDS` configuration can use this command.
- **Non-Owner Access**: Non-owners receive `🚫 Access Denied` and the state is NOT changed.
- **Visibility**: The command only appears in the Owner section of `!help` menu.

