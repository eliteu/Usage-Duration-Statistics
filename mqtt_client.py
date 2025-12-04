# -*- coding: utf-8 -*-
import json
import os
import paho.mqtt.client as mqtt
from datetime import datetime, timezone, timedelta
from models import GameSession, DeviceStatus, DeviceRegistry, normalize_ble_id, db
import logging
import requests
import queue
import threading

# 配置日志
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class GameUsageTracker:
    def __init__(self, update_queue=None):
        self.client = mqtt.Client()
        self.client.on_connect = self.on_connect
        self.client.on_message = self.on_message
        self.client.on_disconnect = self.on_disconnect
        
        # MQTT 连接配置
        self.broker_host = "mqtt.aimaker.space"
        self.broker_port = 1883  # 使用标准 TCP 端口
        self.username = "guest"
        self.password = "test"
        self.topic = "game"
        self.reconnect_delay = 5
        self.max_reconnect_delay = 60
        
        # 实时更新队列
        self.update_queue = update_queue
        # 离线阈值（秒）可配置，默认 300
        try:
            self.offline_window_seconds = int(os.environ.get('OFFLINE_WINDOW_SECONDS', '300'))
        except Exception:
            self.offline_window_seconds = 300

    def _to_utc(self, value) -> datetime:
        """将任意值规范为 UTC 有时区 datetime。
        - 支持 datetime 或 str（ISO8601，可能带 Z）
        - 对 naive datetime 视为 UTC
        """
        if value is None:
            return None
        if isinstance(value, str):
            s = value
            if s.endswith('Z'):
                s = s[:-1] + '+00:00'
            try:
                dt = datetime.fromisoformat(s)
            except Exception:
                try:
                    dt = datetime.strptime(s, '%Y-%m-%d %H:%M:%S')
                except Exception:
                    dt = datetime.now(timezone.utc)
        else:
            dt = value
        if dt.tzinfo is None:
            return dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
        
    def on_connect(self, client, userdata, flags, rc):
        if rc == 0:
            logger.info("✅ 成功连接到 MQTT Broker")
            result = client.subscribe(self.topic)
            logger.info(f"✅ 订阅主题: {self.topic}, 结果: {result}")
            # 重置重连延迟
            self.reconnect_delay = 5
        else:
            error_messages = {
                1: "协议版本不正确",
                2: "客户端标识符无效", 
                3: "服务器不可用",
                4: "用户名或密码错误",
                5: "未授权"
            }
            logger.error(f"❌ 连接失败，错误代码: {rc} - {error_messages.get(rc, '未知错误')}")
    
    def on_disconnect(self, client, userdata, rc):
        if rc != 0:
            logger.warning(f"意外断开连接，错误代码: {rc}")
            logger.info(f"{self.reconnect_delay}秒后尝试重新连接...")
        else:
            logger.info("正常断开连接")
    
    def on_message(self, client, userdata, msg):
        try:
            # 解析 MQTT 消息
            raw_message = msg.payload.decode()
            logger.info(f"📨 收到原始消息: {raw_message}")
            
            message = json.loads(raw_message)
            logger.info(f"📋 解析后消息: {message}")
            
            event = message.get("event")
            player_id = message.get("playerId")
            player_name = message.get("playerName")
            ble_id_raw = message.get("bleId")
            norm_ble = normalize_ble_id(ble_id_raw) if ble_id_raw else None
            if ble_id_raw:
                if norm_ble:
                    logger.info(f"🔷 BLE ID 规范化: {ble_id_raw} -> {norm_ble}")
                else:
                    logger.warning(f"⚠️ BLE ID 格式不正确: {ble_id_raw}，期望格式：MicroBlocks ABC")
            
            # 验证消息格式
            # 必须有 event
            if not event:
                logger.warning("⚠️ 消息格式不完整：缺少 event 字段")
                return
            
            # 验证设备标识：必须有 bleId（且在注册表中）或 playerId+playerName
            if norm_ble:
                # 尝试查找注册表
                try:
                    reg = DeviceRegistry.get(DeviceRegistry.ble_id == norm_ble, DeviceRegistry.status == 'active')
                    # 找到了注册表映射，使用 bleId 作为 device_key，映射名称作为 display_name
                    device_key = norm_ble
                    display_name = f"{reg.campus_name}-{reg.project_name}"
                    logger.info(f"✅ 使用注册表映射: {norm_ble} -> {display_name}")
                except DeviceRegistry.DoesNotExist:
                    # 有 bleId 但未在注册表中，需要 fallback
                    if not player_id or not player_name:
                        logger.warning(f"⚠️ 消息格式不完整：BLE ID {norm_ble} 未在注册表中，请提供 playerId 和 playerName 作为后备，或在后台注册表中添加该 BLE ID")
                        return
                    device_key = norm_ble
                    display_name = player_name or norm_ble
                    logger.info(f"ℹ️ BLE ID {norm_ble} 未在注册表中，使用提供的 playerName: {display_name}")
            else:
                # 没有 bleId 或 bleId 格式不正确，必须提供 playerId 和 playerName
                if not player_id:
                    logger.warning("⚠️ 消息格式不完整：缺少 playerId，且没有提供有效的 bleId")
                    return
                if not player_name:
                    logger.warning("⚠️ 消息格式不完整：缺少 playerName，且没有提供有效的 bleId")
                    return
                device_key = player_id
                display_name = player_name

            # 先获取旧的设备状态（用于计算异常断线的真实时长）
            old_last_seen = None
            try:
                old_device = DeviceStatus.get_or_none(DeviceStatus.player_id == device_key)
                if old_device:
                    old_last_seen = self._to_utc(old_device.last_seen)
            except Exception:
                pass

            # 如果是 game_start，必须在更新 last_seen 之前处理，否则 old_last_seen 就失效了
            # 这是为了解决“先发 heartbeat 立即发 game_start”导致的时长统计错误问题
            if event == "game_start":
                logger.info(f"🎮 处理游戏开始事件: {display_name}")
                self.handle_game_start(device_key, display_name, old_last_seen)
                # game_start 处理完后再更新心跳，这样新会话的开始才算“活着”
                self.update_device_last_seen(device_key, display_name)
            else:
                # 其他消息（heartbeat, game_end 等）先更新心跳
                self.update_device_last_seen(device_key, display_name)
                
                if event == "game_end":
                    logger.info(f"🏁 处理游戏结束事件: {display_name}")
                    self.handle_game_end(device_key, display_name)
                elif event == "heartbeat":
                    logger.info(f"💓 心跳: {display_name}")
                    # last_seen 已在上面统一更新
                    self.trigger_realtime_update()
                else:
                    logger.warning(f"❓ 未知事件类型: {event}")
                
        except json.JSONDecodeError as e:
            logger.error(f"❌ JSON 解析错误: {e}, 原始消息: {msg.payload.decode()}")
        except Exception as e:
            logger.error(f"❌ 处理消息时出错: {e}")
    
    def handle_game_start(self, player_id, player_name, old_last_seen=None):
        """处理游戏开始事件"""
        try:
            # 检查是否有未结束的会话
            existing_session = GameSession.select().where(
                (GameSession.player_id == player_id) & 
                (GameSession.end_time.is_null())
            ).first()
            
            if existing_session:
                logger.warning(f"玩家 {player_name} 有未结束的会话，先结束之前的会话")
                self.end_session(existing_session, is_forced=True, forced_end_time=old_last_seen)
            
            # 创建新的游戏会话
            session = GameSession.create(
                player_id=player_id,
                player_name=player_name,
                start_time=datetime.now(timezone.utc)
            )
            logger.info(f"玩家 {player_name} 开始游戏，会话ID: {session.id}")

            # 更新设备当前会话
            self.set_device_current_session(player_id, player_name, session.id)
            
            # 触发实时更新
            self.trigger_realtime_update()
            
        except Exception as e:
            logger.error(f"处理游戏开始事件时出错: {e}")
    
    def handle_game_end(self, player_id, player_name):
        """处理游戏结束事件"""
        try:
            # 查找最近的未结束会话
            session = GameSession.select().where(
                (GameSession.player_id == player_id) & 
                (GameSession.end_time.is_null())
            ).order_by(GameSession.start_time.desc()).first()
            
            if session:
                self.end_session(session)
                logger.info(f"玩家 {player_name} 结束游戏，游戏时长: {session.duration_seconds}秒")
                # 清空设备当前会话
                self.set_device_current_session(player_id, player_name, None)
            else:
                logger.warning(f"未找到玩家 {player_name} 的活跃会话")
            
            # 触发实时更新
            self.trigger_realtime_update()
                
        except Exception as e:
            logger.error(f"处理游戏结束事件时出错: {e}")
    
    def end_session(self, session, is_forced=False, forced_end_time=None):
        """结束游戏会话"""
        now = datetime.now(timezone.utc)
        start_time_utc = self._to_utc(session.start_time)
        
        # 默认使用当前时间作为结束时间
        end_time = now
        
        # 如果是强制结束（被新游戏挤掉），尝试使用上一次的心跳时间
        if is_forced:
            if forced_end_time and forced_end_time > start_time_utc:
                # 如果有有效的心跳时间（晚于开始时间），使用心跳时间作为结束时间
                # 这能准确反映设备实际断线的时间
                end_time = forced_end_time
                logger.info(f"使用最后心跳时间作为结束时间: {end_time}")
            else:
                # 如果没有有效心跳，使用最大时长封顶策略
                # 比如：如果隔了几天才重连，且没发心跳，我们假设它玩了最多 30 分钟
                MAX_NO_HEARTBEAT_DURATION = 30 * 60  # 30分钟
                
                # 如果实际流逝时间超过了封顶值，就用封顶值
                raw_duration = (now - start_time_utc).total_seconds()
                if raw_duration > MAX_NO_HEARTBEAT_DURATION:
                    end_time = start_time_utc + timedelta(seconds=MAX_NO_HEARTBEAT_DURATION)
                    logger.warning(f"无有效心跳且时长过长，修正为封顶时长 {MAX_NO_HEARTBEAT_DURATION} 秒")
        
        # 计算最终时长
        duration = int((end_time - start_time_utc).total_seconds())
        
        # 防止负数（理论上不会发生）
        if duration < 0:
            duration = 0
        
        session.end_time = end_time
        session.duration_seconds = duration
        session.save()

    def update_device_last_seen(self, player_id: str, player_name: str):
        """更新设备最后心跳时间"""
        now_utc = datetime.now(timezone.utc)
        try:
            device, _ = DeviceStatus.get_or_create(player_id=player_id, defaults={
                'player_name': player_name,
                'last_seen': now_utc,
                'updated_at': now_utc
            })
            device.player_name = player_name
            device.last_seen = now_utc
            device.updated_at = now_utc
            device.save()
        except Exception as e:
            logger.warning(f"更新设备心跳失败: {e}")

    def set_device_current_session(self, player_id: str, player_name: str, session_id):
        """设置设备当前会话ID（开始/结束时调用）"""
        now_utc = datetime.now(timezone.utc)
        try:
            device, _ = DeviceStatus.get_or_create(player_id=player_id, defaults={
                'player_name': player_name,
                'updated_at': now_utc
            })
            device.player_name = player_name
            device.current_session_id = session_id
            device.updated_at = now_utc
            device.save()
        except Exception as e:
            logger.warning(f"更新设备当前会话失败: {e}")
    
    def trigger_realtime_update(self):
        """触发前端实时更新"""
        try:
            if self.update_queue:
                # 直接通过队列发送更新信号
                update_data = {
                    'type': 'mqtt_update',
                    'timestamp': datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z')
                }
                self.update_queue.put(update_data)
                logger.info("✅ 成功触发实时更新（队列）")
            else:
                # 备用方案：HTTP 请求
                import requests
                try:
                    response = requests.post('https://devicetime.aimaker.space/api/trigger-update', timeout=1)
                    if response.status_code == 200:
                        logger.info("✅ 成功触发实时更新（HTTP）")
                except:
                    logger.debug("HTTP 触发失败，使用队列方式")
                
        except Exception as e:
            logger.warning(f"⚠️ 触发实时更新失败: {e}")
    
    def start(self):
        """启动 MQTT 客户端"""
        while True:
            try:
                # 设置用户名和密码
                self.client.username_pw_set(self.username, self.password)
                
                logger.info(f"正在连接到 MQTT Broker: {self.broker_host}:{self.broker_port}")
                self.client.connect(self.broker_host, self.broker_port, 60)
                
                logger.info("开始监听 MQTT 消息...")
                self.client.loop_forever()
                
            except KeyboardInterrupt:
                logger.info("收到中断信号，正在退出...")
                break
            except Exception as e:
                logger.error(f"MQTT 客户端出错: {e}")
                logger.info(f"{self.reconnect_delay}秒后尝试重新连接...")
                
                import time
                time.sleep(self.reconnect_delay)
                
                # 增加重连延迟，但不超过最大值
                self.reconnect_delay = min(self.reconnect_delay * 2, self.max_reconnect_delay)
        
        # 清理连接
        try:
            self.client.disconnect()
        except:
            pass

if __name__ == "__main__":
    # 初始化数据库
    db.connect()
    
    # 启动游戏使用时长追踪器
    tracker = GameUsageTracker()
    tracker.start()