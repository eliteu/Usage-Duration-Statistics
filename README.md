# 游戏设备使用时长统计系统

基于 MQTT + Peewee + SQLite 的实时游戏设备使用时长统计系统。

## 功能特性

- 🎮 实时监听 MQTT 消息，自动记录游戏开始/结束事件
- 📊 统计玩家使用时长、游戏次数等数据
- 🌐 提供 Web 界面展示统计结果
- 🔄 支持实时数据更新
- 📱 响应式设计，支持移动端访问

## 系统架构

```
MQTT Broker (wss://guest:test@mqtt.aimaker.space:8084/mqtt)
    ↓ (主题: game)
MQTT Client (mqtt_client.py)
    ↓
SQLite Database (game_usage.db)
    ↓
Flask API (api.py)
    ↓
Web Frontend (static/index.html)
```

## 安装依赖

```bash
pip install -r requirements.txt
```

## 使用方法

### 1. 初始化数据库

```bash
python models.py
```

### 2. 启动完整系统

```bash
python run.py
```

这将同时启动：
- MQTT 客户端（监听游戏事件）
- Web API 服务器（提供数据接口）

### 3. 访问 Web 界面

打开浏览器访问：http://localhost:5000/static/index.html

### 4. 单独运行组件

**只运行 MQTT 客户端：**
```bash
python mqtt_client.py
```

**只运行 API 服务器：**
```bash
python api.py
```

## MQTT 消息格式

系统监听主题 `game`，支持以下消息格式：

### 基础格式（向后兼容）

**游戏开始：**
```json
{
    "event": "game_start",
    "playerId": "娃娃机（英荔总部）",
    "playerName": "娃娃机（英荔总部）"
}
```

**游戏结束：**
```json
{
    "event": "game_end",
    "playerId": "娃娃机（英荔总部）",
    "playerName": "娃娃机（英荔总部）"
}
```

### 扩展格式（推荐，支持注册表映射）

#### 方式 1：bleId + playerId/playerName（向后兼容）

```json
{
    "event": "game_start",
    "playerId": "备用设备ID",
    "playerName": "备用设备名",
    "bleId": "MicroBlocks ABC"
}
```

#### 方式 2：仅 bleId（如果已在注册表中配置）

如果 `bleId` 已在后台注册表中配置，可以**只提供 `bleId`**，系统会自动使用注册表的映射：

```json
{
    "event": "game_start",
    "bleId": "MicroBlocks ABC"
}
```

**说明：**
- `bleId` 字段是**可选的**：
  - 如果提供了 `bleId` 且在注册表中找到映射，可以不提供 `playerId` 和 `playerName`
  - 如果提供了 `bleId` 但未在注册表中，必须提供 `playerId` 和 `playerName` 作为后备
  - 如果不提供 `bleId`，必须提供 `playerId` 和 `playerName`
- 如果提供了 `bleId` 且在注册表中找到映射，前端会显示"校区-项目"格式的名称
- 格式要求：`MicroBlocks` + 空格 + 3个字母（如 `MicroBlocks ABC`）
- 详见 `BLE_ID_FORMAT.md`

## API 接口

### 获取游戏会话列表
```
GET /api/sessions?page=1&per_page=20&player_id=xxx
```

### 获取统计数据
```
GET /api/stats
```

### 获取玩家排行榜
```
GET /api/players
```

## 数据库结构

**GameSession 表：**
- `id`: 主键
- `player_id`: 玩家ID
- `player_name`: 玩家名称
- `start_time`: 游戏开始时间
- `end_time`: 游戏结束时间
- `duration_seconds`: 游戏时长（秒）
- `created_at`: 记录创建时间

## 配置说明

**MQTT 连接配置（mqtt_client.py）：**
- Broker: mqtt.aimaker.space:8084
- 用户名: guest
- 密码: test
- 主题: game
- 协议: WebSocket

**Web 服务器配置（api.py）：**
- 端口: 5000
- 主机: 0.0.0.0（允许外部访问）

## 注意事项

1. 确保网络能够访问 MQTT Broker
2. 系统会自动处理重复的游戏开始事件
3. 未正常结束的游戏会话在新游戏开始时自动结束
4. Web 界面每30秒自动刷新数据

## 故障排除

**MQTT 连接失败：**
- 检查网络连接
- 确认 MQTT Broker 地址和端口
- 验证用户名和密码

**数据库错误：**
- 确保有写入权限
- 检查磁盘空间
- 重新初始化数据库

**Web 界面无法访问：**
- 确认 Flask 服务器正在运行
- 检查防火墙设置
- 验证端口 5000 是否被占用