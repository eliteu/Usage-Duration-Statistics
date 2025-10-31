# 故障排除指南

## "消息格式不完整" 错误说明

系统会在以下几种情况下提示"消息格式不完整"：

### 情况 1：缺少 event 字段

**错误提示：**
```
⚠️ 消息格式不完整：缺少 event 字段
```

**原因：**
消息中必须包含 `event` 字段，值为 `game_start`、`game_end` 或 `heartbeat`。

**解决方案：**
确保消息包含 `event` 字段：
```json
{
    "event": "game_start",
    ...
}
```

---

### 情况 2：只提供了 bleId，但未在注册表中

**错误提示：**
```
⚠️ 消息格式不完整：BLE ID MICROBLOCKSABC 未在注册表中，请提供 playerId 和 playerName 作为后备，或在后台注册表中添加该 BLE ID
```

**原因：**
- 消息中只提供了 `bleId` 字段
- 该 `bleId` 未在后台注册表中配置

**解决方案（两种方式）：**

**方式 1：在后台注册表中添加该 BLE ID（推荐）**
1. 访问后台管理页面：`http://localhost:5001/static/admin.html`
2. 添加新的映射：
   - BLE ID: `MicroBlocks ABC`
   - 校区名称: 填写校区
   - 项目名称: 填写项目
3. 保存后，后续消息可以只发送 `bleId`

**方式 2：在消息中添加 playerId 和 playerName 作为后备**
```json
{
    "event": "game_start",
    "playerId": "备用设备ID",
    "playerName": "备用设备名",
    "bleId": "MicroBlocks ABC"
}
```

---

### 情况 3：bleId 格式不正确

**错误提示：**
```
⚠️ BLE ID 格式不正确: MicroBlocksABC，期望格式：MicroBlocks ABC
```

**原因：**
BLE ID 格式错误，缺少空格。正确格式应该是：`MicroBlocks` + **空格** + 3个字母

**解决方案：**
修正 BLE ID 格式：
```json
{
    "event": "game_start",
    "bleId": "MicroBlocks ABC"  // ✅ 正确：有空格
}
```

**错误的格式示例：**
- ❌ `MicroBlocksABC`（缺少空格）
- ❌ `microblocks abc`（虽然会被规范化为 MICROBLOCKSABC，但建议使用标准格式）
- ✅ `MicroBlocks ABC`（正确格式）

---

### 情况 4：没有提供 bleId 和 playerId/playerName

**错误提示：**
```
⚠️ 消息格式不完整：缺少 playerId，且没有提供有效的 bleId
⚠️ 消息格式不完整：缺少 playerName，且没有提供有效的 bleId
```

**原因：**
消息中既没有提供 `bleId`（或 `bleId` 格式不正确），也没有提供 `playerId` 和 `playerName`。

**解决方案：**
必须至少满足以下条件之一：

1. **提供有效的 bleId（且在注册表中）**
```json
{
    "event": "game_start",
    "bleId": "MicroBlocks ABC"  // 必须在注册表中
}
```

2. **提供 playerId 和 playerName**
```json
{
    "event": "game_start",
    "playerId": "设备ID",
    "playerName": "设备名称"
}
```

---

## 消息格式快速参考

### ✅ 推荐格式 1：仅 bleId（需在注册表中）
```json
{
    "event": "game_start",
    "bleId": "MicroBlocks ABC"
}
```

### ✅ 推荐格式 2：bleId + 后备信息
```json
{
    "event": "game_start",
    "playerId": "备用ID",
    "playerName": "备用名称",
    "bleId": "MicroBlocks ABC"
}
```

### ✅ 兼容格式：仅 playerId/playerName
```json
{
    "event": "game_start",
    "playerId": "设备ID",
    "playerName": "设备名称"
}
```

---

## 常见问题

### Q: 为什么我的 bleId 格式看起来正确但还是提示不完整？

A: 可能的原因：
1. **bleId 未在注册表中**：即使格式正确，如果没有在后台注册表中配置，且没有提供 `playerId`/`playerName`，也会提示不完整
2. **空格问题**：确保是单个空格，不是多个空格或制表符
3. **字母数量**：必须是 3 个字母，不能多不能少

### Q: 如何检查 bleId 是否在注册表中？

A: 
1. 访问后台管理页面：`http://localhost:5001/static/admin.html`
2. 在查询框中搜索你的 BLE ID
3. 或者在数据库中查询 `device_registry` 表

### Q: 我可以同时提供 bleId 和 playerId/playerName 吗？

A: 可以！这是推荐的做法，因为：
- 如果 `bleId` 在注册表中，会使用注册表的映射
- 如果 `bleId` 不在注册表中，会使用 `playerId`/`playerName` 作为后备
- 这样既能享受映射功能，又有向后兼容性

---

## 调试技巧

1. **查看日志**：系统会输出详细的日志信息，包括：
   - BLE ID 规范化结果
   - 是否找到注册表映射
   - 使用的设备标识和显示名称

2. **测试消息格式**：可以使用 `send_test_data.py` 脚本测试不同的消息格式

3. **检查后台注册表**：确保 BLE ID 已正确添加且状态为 `active`

