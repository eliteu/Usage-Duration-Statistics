import json
import paho.mqtt.client as mqtt
from datetime import datetime
from models import GameSession, db
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
            
            if not all([event, player_id, player_name]):
                logger.warning("⚠️ 消息格式不完整")
                return
            
            if event == "game_start":
                logger.info(f"🎮 处理游戏开始事件: {player_name}")
                self.handle_game_start(player_id, player_name)
            elif event == "game_end":
                logger.info(f"🏁 处理游戏结束事件: {player_name}")
                self.handle_game_end(player_id, player_name)
            else:
                logger.warning(f"❓ 未知事件类型: {event}")
                
        except json.JSONDecodeError as e:
            logger.error(f"❌ JSON 解析错误: {e}, 原始消息: {msg.payload.decode()}")
        except Exception as e:
            logger.error(f"❌ 处理消息时出错: {e}")
    
    def handle_game_start(self, player_id, player_name):
        """处理游戏开始事件"""
        try:
            # 检查是否有未结束的会话
            existing_session = GameSession.select().where(
                (GameSession.player_id == player_id) & 
                (GameSession.end_time.is_null())
            ).first()
            
            if existing_session:
                logger.warning(f"玩家 {player_name} 有未结束的会话，先结束之前的会话")
                self.end_session(existing_session)
            
            # 创建新的游戏会话
            session = GameSession.create(
                player_id=player_id,
                player_name=player_name,
                start_time=datetime.now()
            )
            logger.info(f"玩家 {player_name} 开始游戏，会话ID: {session.id}")
            
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
            else:
                logger.warning(f"未找到玩家 {player_name} 的活跃会话")
            
            # 触发实时更新
            self.trigger_realtime_update()
                
        except Exception as e:
            logger.error(f"处理游戏结束事件时出错: {e}")
    
    def end_session(self, session):
        """结束游戏会话"""
        end_time = datetime.now()
        duration = int((end_time - session.start_time).total_seconds())
        
        session.end_time = end_time
        session.duration_seconds = duration
        session.save()
    
    def trigger_realtime_update(self):
        """触发前端实时更新"""
        try:
            if self.update_queue:
                # 直接通过队列发送更新信号
                update_data = {
                    'type': 'mqtt_update',
                    'timestamp': datetime.now().isoformat()
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