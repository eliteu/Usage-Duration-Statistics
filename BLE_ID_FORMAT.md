# BLE ID 格式说明

## 格式规范

系统支持 **MicroBlocks IOP** 格式的 BLE ID：

- **格式**：`MicroBlocks` + **空格** + 3个随机字母（大小写均可）
- **示例**：
  - `MicroBlocks ABC`
  - `MicroBlocks XYZ`
  - `microblocks def`（会自动规范化为 `MICROBLOCKSDEF`）

**重要**：MicroBlocks 后**必须**有空格，然后是3个字母。

## 规范化规则

系统会自动将输入的 BLE ID 规范化为统一格式：
- 识别 "MicroBlocks" 前缀（不区分大小写）
- **要求**：MicroBlocks 后必须有空格
- 提取空格后的 3 个字母
- 统一转换为大写：`MICROBLOCKSXXX`（存储时无空格）

例如：
- `MicroBlocks ABC` → `MICROBLOCKSABC`
- `MicroBlocks XYZ` → `MICROBLOCKSXYZ`
- `microblocks def` → `MICROBLOCKSDEF`
- `MicroBlocks  ABC` → `MICROBLOCKSABC`（多个空格也支持）

## 关于蓝牙关闭的影响

### ✅ 不影响的功能

1. **设备识别与映射**：
   - 只要在 `game_start` 事件时能获取到 BLE ID，就能正确匹配注册表映射
   - 蓝牙关闭不影响已创建的会话记录
   - 蓝牙关闭不影响历史统计数据

2. **会话记录**：
   - 游戏开始时记录的数据会完整保存
   - 即使蓝牙中途关闭，游戏时长仍会正确计算（基于 `game_start` 和 `game_end` 时间）

### ⚠️ 可能受影响的功能

1. **实时状态判断**：
   - 如果蓝牙关闭，设备无法发送 `heartbeat` 事件
   - `last_seen` 不会更新，可能在 5 分钟后被判定为离线
   - 这是正常的离线状态，不影响历史数据

2. **在线状态显示**：
   - 蓝牙关闭后，前端可能显示设备为"离线"状态
   - 但这只是实时状态，不影响已保存的使用记录

## 建议

1. **在游戏开始时确保蓝牙开启**：
   - 确保 `game_start` 事件能携带正确的 BLE ID
   - 这是正确匹配校区/项目映射的关键

2. **游戏结束后可以关闭蓝牙**：
   - 蓝牙关闭不影响已记录的数据
   - 系统会基于 `game_start` 和 `game_end` 的时间差计算使用时长

3. **如果需要保持在线状态**：
   - 可以定期发送 `heartbeat` 事件
   - 或者在游戏结束后不立即关闭蓝牙，等待一段时间后再关闭

## MQTT 消息格式

设备发送的消息应包含 `bleId` 字段：

```json
{
  "event": "game_start",
  "playerId": "备用设备ID",
  "playerName": "备用设备名",
  "bleId": "MicroBlocksABC"
}
```

系统会优先使用 `bleId` 来匹配注册表，如果匹配成功，展示名会变为"校区-项目"格式。

