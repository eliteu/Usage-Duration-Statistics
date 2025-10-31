# -*- coding: utf-8 -*-
from peewee import *
from datetime import datetime, timezone
import re

# SQLite 数据库配置
db = SqliteDatabase('game_usage.db')

class BaseModel(Model):
    class Meta:
        database = db

class GameSession(BaseModel):
    """游戏会话记录"""
    player_id = CharField(max_length=100)
    player_name = CharField(max_length=100)
    start_time = DateTimeField()
    end_time = DateTimeField(null=True)
    duration_seconds = IntegerField(null=True)
    created_at = DateTimeField(default=lambda: datetime.now(timezone.utc))
    
    class Meta:
        table_name = 'game_sessions'

class DeviceStatus(BaseModel):
    """设备状态与最近心跳"""
    player_id = CharField(max_length=100, unique=True)
    player_name = CharField(max_length=100)
    last_seen = DateTimeField(null=True)
    current_session_id = IntegerField(null=True)
    updated_at = DateTimeField(default=lambda: datetime.now(timezone.utc))

    class Meta:
        table_name = 'device_status'

class DeviceRegistry(BaseModel):
    """设备注册表：将 BLE ID 映射到校区与项目名称"""
    ble_id = CharField(max_length=64, unique=True)  # 规范化后的 BLE（大写无分隔）
    campus_name = CharField(max_length=100)
    project_name = CharField(max_length=100)
    status = CharField(max_length=16, default='active')  # active/disabled
    remark = CharField(max_length=255, null=True)
    created_at = DateTimeField(default=lambda: datetime.now(timezone.utc))
    updated_at = DateTimeField(default=lambda: datetime.now(timezone.utc))

    class Meta:
        table_name = 'device_registry'

def normalize_ble_id(ble_id: str) -> str:
    """
    规范化 BLE ID（MicroBlocks IOP 格式）
    格式：MicroBlocks + 空格 + 3个随机字母（如 "MicroBlocks ABC"）
    - 自动识别 MicroBlocks 前缀（大小写不敏感）
    - 要求 MicroBlocks 后必须有空格，然后是3个字母
    - 提取后续的3个字母并转换为大写
    - 统一格式为：MICROBLOCKSXXX（无空格）
    """
    if not ble_id:
        return ''
    
    # 去除首尾空格，转换为统一格式便于处理
    s = ble_id.strip()
    
    # 使用正则表达式识别格式：MicroBlocks + 空格 + 3个字母
    # 匹配格式：MicroBlocks（不区分大小写）+ 空格 + 3个字母
    pattern = r'^[Mm]icro[Bb]locks\s+([A-Za-z]{3})'
    match = re.match(pattern, s)
    
    if match:
        # 提取3个字母并转为大写
        suffix = match.group(1).upper()
        return f'MICROBLOCKS{suffix}'
    else:
        # 如果不是标准格式，尝试兼容处理（去除空格后检查）
        # 只保留字母，转大写
        letters_only = ''.join(ch for ch in s if ch.isalpha()).upper()
        if letters_only.startswith('MICROBLOCKS') and len(letters_only) >= 14:
            # 提取 MicroBlocks 后的3个字母
            suffix = letters_only[11:14]
            if len(suffix) == 3:
                return f'MICROBLOCKS{suffix}'
        # 返回原字符串的大写字母版本
        return letters_only

def init_db():
    """初始化数据库"""
    db.connect()
    db.create_tables([GameSession, DeviceStatus, DeviceRegistry], safe=True)
    print("数据库初始化完成")

if __name__ == "__main__":
    init_db()