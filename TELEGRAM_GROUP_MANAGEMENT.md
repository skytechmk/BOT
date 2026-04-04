# 📱 Telegram Group Management Module

## Overview
Complete Telegram group management functionality integrated with AI capabilities. Allows viewing and manipulating group members through AI commands.

## 🛠️ Available Functions

### 📊 Information Functions

#### 1. get_chat_administrators
```python
get_chat_administrators(chat_id: str, use_ops_bot: bool = False)
```
- **Purpose**: Get list of all chat administrators
- **Parameters**: 
  - `chat_id`: Telegram chat ID
  - `use_ops_bot`: Use OPS bot instead of main bot (default: False)
- **Returns**: List of admin details including permissions

#### 2. get_chat_member
```python
get_chat_member(chat_id: str, user_id: int, use_ops_bot: bool = False)
```
- **Purpose**: Get information about specific member
- **Parameters**:
  - `chat_id`: Telegram chat ID
  - `user_id`: Telegram user ID
  - `use_ops_bot`: Use OPS bot instead of main bot (default: False)
- **Returns**: Member details and permissions

#### 3. get_chat_member_count
```python
get_chat_member_count(chat_id: str, use_ops_bot: bool = False)
```
- **Purpose**: Get total number of members in chat
- **Parameters**:
  - `chat_id`: Telegram chat ID
  - `use_ops_bot`: Use OPS bot instead of main bot (default: False)
- **Returns**: Member count and timestamp

#### 4. get_chat_info
```python
get_chat_info(chat_id: str, use_ops_bot: bool = False)
```
- **Purpose**: Get comprehensive chat information
- **Parameters**:
  - `chat_id`: Telegram chat ID
  - `use_ops_bot`: Use OPS bot instead of main bot (default: False)
- **Returns**: Complete chat details including settings

### 🔧 Management Functions

#### 5. ban_chat_member
```python
ban_chat_member(chat_id: str, user_id: int, until_date: Optional[int] = None, 
               revoke_messages: bool = True, use_ops_bot: bool = False)
```
- **Purpose**: Ban a member from the chat
- **Parameters**:
  - `chat_id`: Telegram chat ID
  - `user_id`: Telegram user ID to ban
  - `until_date`: Unix timestamp when ban ends (None = permanent)
  - `revoke_messages`: Delete all user messages (default: True)
  - `use_ops_bot`: Use OPS bot instead of main bot (default: False)
- **Returns**: Operation result

#### 6. unban_chat_member
```python
unban_chat_member(chat_id: str, user_id: int, only_if_banned: bool = True, 
                 use_ops_bot: bool = False)
```
- **Purpose**: Unban a member from the chat
- **Parameters**:
  - `chat_id`: Telegram chat ID
  - `user_id`: Telegram user ID to unban
  - `only_if_banned`: Only unban if currently banned (default: True)
  - `use_ops_bot`: Use OPS bot instead of main bot (default: False)
- **Returns**: Operation result

#### 7. restrict_chat_member
```python
restrict_chat_member(chat_id: str, user_id: int, permissions: Dict[str, Any],
                    use_independent_chat_permissions: bool = False, 
                    use_ops_bot: bool = False)
```
- **Purpose**: Restrict member permissions
- **Parameters**:
  - `chat_id`: Telegram chat ID
  - `user_id`: Telegram user ID to restrict
  - `permissions`: Dictionary of permission settings
  - `use_independent_chat_permissions`: Use independent permissions (default: False)
  - `use_ops_bot`: Use OPS bot instead of main bot (default: False)
- **Returns**: Operation result

#### 8. promote_chat_member
```python
promote_chat_member(chat_id: str, user_id: int, permissions: Dict[str, Any],
                    use_ops_bot: bool = False)
```
- **Purpose**: Promote member to administrator
- **Parameters**:
  - `chat_id`: Telegram chat ID
  - `user_id`: Telegram user ID to promote
  - `permissions`: Dictionary of admin permissions
  - `use_ops_bot`: Use OPS bot instead of main bot (default: False)
- **Returns**: Operation result

#### 9. demote_chat_member
```python
demote_chat_member(chat_id: str, user_id: int, use_ops_bot: bool = False)
```
- **Purpose**: Demote administrator to regular member
- **Parameters**:
  - `chat_id`: Telegram chat ID
  - `user_id`: Telegram user ID to demote
  - `use_ops_bot`: Use OPS bot instead of main bot (default: False)
- **Returns**: Operation result

## 🤖 AI Integration

All functions are available through MCP bridge for AI agents:

### Example AI Commands:
- "Show me all administrators in the main group"
- "Get information about user 123456789"
- "How many members are in the trading group?"
- "Ban user 123456789 for spam"
- "Promote user 987654321 to admin"

### Permission Examples:

#### Restrict Permissions:
```python
permissions = {
    'can_send_messages': False,
    'can_send_media_messages': False,
    'can_send_polls': False
}
```

#### Admin Permissions:
```python
permissions = {
    'can_change_info': True,
    'can_delete_messages': True,
    'can_invite_users': True,
    'can_restrict_members': True,
    'can_pin_messages': True
}
```

## 🔐 Security Features

1. **Permission Checks**: Bot verifies it has required permissions before actions
2. **Audit Logging**: All actions are logged to `logs/ai_developer_actions.json`
3. **Error Handling**: Comprehensive error handling with detailed messages
4. **Dual Bot Support**: Can use main bot or OPS bot for different privilege levels

## 📝 Usage Examples

### Get Group Info:
```python
from telegram_group_manager import GROUP_MANAGER

# Get chat info
info = await GROUP_MANAGER.get_chat_info("-1002209928687")
print(f"Group: {info['title']}, Members: {info['member_count']}")
```

### Ban User:
```python
# Ban for 24 hours (86400 seconds)
result = await GROUP_MANAGER.ban_chat_member(
    chat_id="-1002209928687",
    user_id=123456789,
    until_date=int(time.time()) + 86400
)
```

### Restrict User:
```python
permissions = {
    'can_send_messages': False,
    'can_send_media_messages': False
}
result = await GROUP_MANAGER.restrict_chat_member(
    chat_id="-1002209928687",
    user_id=123456789,
    permissions=permissions
)
```

## 🚀 Integration

The module is fully integrated with:
- **MCP Bridge**: All functions available to AI agents
- **Telegram Handler**: Seamless integration with existing bot
- **Audit System**: All actions logged and tracked
- **Error Recovery**: Robust error handling and recovery

## 📋 Requirements

- Telegram Bot API access
- Appropriate bot permissions in target groups
- Valid bot tokens in environment variables

## ⚠️ Important Notes

1. **Bot Permissions**: Bot must be administrator in target groups for management functions
2. **API Limits**: Respect Telegram API rate limits
3. **Privacy**: Use responsibly and comply with Telegram ToS
4. **Logging**: All actions are permanently logged for audit purposes

## 🎯 Best Practices

1. **Check Permissions**: Always verify bot permissions before actions
2. **Use OPS Bot**: Use OPS bot for sensitive operations
3. **Log Actions**: All actions are automatically logged
4. **Handle Errors**: Implement proper error handling
5. **Rate Limits**: Be mindful of Telegram API limits
