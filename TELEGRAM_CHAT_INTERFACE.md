# 💬 Telegram Chat Interface Module

## Overview
Advanced chat interface allowing AI to have natural conversations with users in Telegram groups. Includes message sending, conversation management, and AI-powered responses.

## 🛠️ Available Functions

### 💬 Basic Messaging

#### 1. send_message
```python
send_message(chat_id: str, text: str, reply_to_message_id: Optional[int] = None,
             parse_mode: Optional[str] = None, use_ops_bot: bool = False)
```
- **Purpose**: Send a message to chat
- **Parameters**:
  - `chat_id`: Telegram chat ID
  - `text`: Message text
  - `reply_to_message_id`: Reply to specific message
  - `parse_mode`: HTML/Markdown formatting
  - `use_ops_bot`: Use OPS bot instead of main bot (default: False)
- **Returns**: Message sending result

#### 2. send_reply
```python
send_reply(chat_id: str, reply_to_message_id: int, text: str, use_ops_bot: bool = False)
```
- **Purpose**: Reply to a specific message
- **Parameters**:
  - `chat_id`: Telegram chat ID
  - `reply_to_message_id`: Message ID to reply to
  - `text`: Reply text
  - `use_ops_bot`: Use OPS bot instead of main bot (default: False)
- **Returns**: Reply result

#### 3. send_inline_keyboard
```python
send_inline_keyboard(chat_id: str, text: str, buttons: List[List[Dict[str, str]]],
                    use_ops_bot: bool = False)
```
- **Purpose**: Send message with inline keyboard buttons
- **Parameters**:
  - `chat_id`: Telegram chat ID
  - `text`: Message text
  - `buttons`: List of button rows [[{text: "Button1", callback_data: "data1"}]]
  - `use_ops_bot`: Use OPS bot instead of main bot (default: False)
- **Returns**: Message result

### 🔄 Message Management

#### 4. forward_message
```python
forward_message(from_chat_id: str, to_chat_id: str, message_id: int, use_ops_bot: bool = False)
```
- **Purpose**: Forward a message from one chat to another
- **Parameters**:
  - `from_chat_id`: Source chat ID
  - `to_chat_id`: Destination chat ID
  - `message_id`: Message ID to forward
  - `use_ops_bot`: Use OPS bot instead of main bot (default: False)
- **Returns**: Forward result

#### 5. edit_message
```python
edit_message(chat_id: str, message_id: int, text: str, use_ops_bot: bool = False)
```
- **Purpose**: Edit an existing message
- **Parameters**:
  - `chat_id`: Telegram chat ID
  - `message_id`: Message ID to edit
  - `text`: New message text
  - `use_ops_bot`: Use OPS bot instead of main bot (default: False)
- **Returns**: Edit result

#### 6. delete_message
```python
delete_message(chat_id: str, message_id: int, use_ops_bot: bool = False)
```
- **Purpose**: Delete a message
- **Parameters**:
  - `chat_id`: Telegram chat ID
  - `message_id`: Message ID to delete
  - `use_ops_bot`: Use OPS bot instead of main bot (default: False)
- **Returns**: Delete result

### 📚 Chat History & Context

#### 7. get_chat_history
```python
get_chat_history(chat_id: str, limit: int = 50, use_ops_bot: bool = False)
```
- **Purpose**: Get recent chat history
- **Parameters**:
  - `chat_id`: Telegram chat ID
  - `limit`: Number of messages to retrieve (default: 50)
  - `use_ops_bot`: Use OPS bot instead of main bot (default: False)
- **Returns**: Chat history

#### 8. analyze_user_message
```python
analyze_user_message(chat_id: str, user_id: int, message_text: str, use_ops_bot: bool = False)
```
- **Purpose**: Analyze user message and generate AI response
- **Parameters**:
  - `chat_id`: Telegram chat ID
  - `user_id`: User ID who sent message
  - `message_text`: The message text
  - `use_ops_bot`: Use OPS bot instead of main bot (default: False)
- **Returns**: AI analysis and response

### 🗣️ Conversation Management

#### 9. start_conversation
```python
start_conversation(chat_id: str, greeting: str = None, use_ops_bot: bool = False)
```
- **Purpose**: Start a conversation with the chat
- **Parameters**:
  - `chat_id`: Telegram chat ID
  - `greeting`: Custom greeting message
  - `use_ops_bot`: Use OPS bot instead of main bot (default: False)
- **Returns**: Conversation start result

#### 10. end_conversation
```python
end_conversation(chat_id: str, farewell: str = None, use_ops_bot: bool = False)
```
- **Purpose**: End a conversation with the chat
- **Parameters**:
  - `chat_id`: Telegram chat ID
  - `farewell`: Custom farewell message
  - `use_ops_bot`: Use OPS bot instead of main bot (default: False)
- **Returns**: Conversation end result

## 🤖 AI Integration

All functions are available through MCP bridge for AI agents:

### Example AI Commands:
- "Send message 'Hello everyone!' to the main group"
- "Reply to message 123 with 'Thanks for asking!'"
- "Start a conversation with greeting 'Hi, I'm here to help!'"
- "Analyze user message 'What's the market status?' and respond"
- "Get the last 20 messages from chat history"

### Conversation Examples:

#### Starting a Conversation:
```python
# AI can start conversations
await start_conversation("-1002209928687", "👋 Hello! I'm AI assistant. How can I help you today?")
```

#### Analyzing and Responding:
```python
# AI can analyze user messages and respond
result = await analyze_user_message(
    chat_id="-1002209928687",
    user_id=123456789,
    message_text="What's the current BTC price?"
)
```

#### Interactive Buttons:
```python
# AI can send interactive keyboards
buttons = [
    [{"text": "📊 Market Analysis", "callback_data": "market_analysis"}],
    [{"text": "💰 Trading Signals", "callback_data": "signals"}],
    [{"text": "❓ Help", "callback_data": "help"}]
]
await send_inline_keyboard("-1002209928687", "What would you like to know?", buttons)
```

## 🧠 AI Conversation Features

### Context Awareness:
- **Chat Memory**: Stores conversation history for context
- **User Context**: Remembers previous interactions
- **Thread Continuity**: Maintains conversation flow

### Intelligent Responses:
- **Natural Language**: Uses OpenRouter for intelligent responses
- **Context-Aware**: Considers recent messages in responses
- **Trading Knowledge**: Specialized for trading-related questions

### Memory Management:
- **Automatic Storage**: All messages stored in memory
- **Context Limits**: Configurable memory limits
- **Cleanup Options**: Clear chat memory when needed

## 📝 Usage Examples

### Basic Chat:
```python
from telegram_chat_interface import CHAT_INTERFACE

# Send a message
await CHAT_INTERFACE.send_message("-1002209928687", "Hello everyone!")

# Reply to a message
await CHAT_INTERFACE.send_reply("-1002209928687", 12345, "I agree!")

# Send with formatting
await CHAT_INTERFACE.send_message("-1002209928687", "*Bold text*", parse_mode="Markdown")
```

### Interactive Conversation:
```python
# Start conversation
await CHAT_INTERFACE.start_conversation("-1002209928687", "👋 How can I help?")

# Analyze and respond
result = await CHAT_INTERFACE.analyze_user_message(
    chat_id="-1002209928687",
    user_id=123456789,
    message_text="What's the market outlook?"
)
```

### Advanced Features:
```python
# Send interactive buttons
buttons = [
    [{"text": "📈 Bullish", "callback_data": "bullish"}],
    [{"text": "📉 Bearish", "callback_data": "bearish"}]
]
await CHAT_INTERFACE.send_inline_keyboard("-1002209928687", "Market sentiment?", buttons)

# Forward important messages
await CHAT_INTERFACE.forward_message("-1002209928687", "-1003706659588", 12345)

# Edit sent messages
await CHAT_INTERFACE.edit_message("-1002209928687", 12346, "Updated information")
```

## 🔐 Security & Privacy

### Message Privacy:
- **Local Storage**: Chat memory stored locally
- **No External Access**: Messages not shared externally
- **Cleanup Options**: Memory can be cleared

### Permission Checks:
- **Bot Verification**: Bot permissions checked before actions
- **Chat Access**: Only chats where bot is member
- **Rate Limiting**: Respects Telegram API limits

### Audit Logging:
- **Action Logging**: All chat actions logged
- **User Tracking**: User interactions recorded
- **Message History**: Complete conversation audit trail

## 🚀 Integration

The module is fully integrated with:
- **MCP Bridge**: All functions available to AI agents
- **Group Management**: Works with group management functions
- **Audit System**: All conversations logged
- **Auto-Healer**: Can trigger healing based on chat analysis

## 📋 Requirements

- Telegram Bot API access
- Bot must be member of target groups
- Valid bot tokens in environment variables
- OpenRouter API for AI responses

## ⚠️ Important Notes

1. **Bot Permissions**: Bot must have appropriate permissions
2. **API Limits**: Respect Telegram API rate limits
3. **Memory Usage**: Monitor chat memory usage
4. **Privacy**: Handle user data responsibly

## 🎯 Best Practices

1. **Context Management**: Keep conversation context relevant
2. **Response Quality**: Ensure helpful, accurate responses
3. **Memory Cleanup**: Clear old conversations periodically
4. **Rate Limits**: Be mindful of API usage
5. **User Privacy**: Handle sensitive information carefully

## 🔄 Advanced Features

### Conversation States:
- **Active**: Ongoing conversation with context
- **Inactive**: No recent activity
- **Ended**: Conversation formally closed

### Message Types:
- **User Messages**: Messages from users
- **AI Messages**: Responses from AI
- **System Messages**: Bot notifications

### Context Features:
- **Thread Awareness**: Maintains conversation threads
- **User Recognition**: Remembers user preferences
- **Topic Tracking**: Follows conversation topics
