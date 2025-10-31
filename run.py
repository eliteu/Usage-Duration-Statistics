#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
游戏设备使用时长统计系统启动脚本
"""

import threading
import time
from models import init_db
from mqtt_client import GameUsageTracker
from api import app, update_queue

def start_mqtt_client():
    """启动 MQTT 客户端"""
    print("启动 MQTT 客户端...")
    tracker = GameUsageTracker(update_queue=update_queue)
    tracker.start()

def start_web_server():
    """启动 Web 服务器"""
    import os
    port = int(os.environ.get('PORT', 5001))
    print(f"启动 Web 服务器，端口: {port}")
    app.run(debug=False, host='0.0.0.0', port=port, use_reloader=False)

if __name__ == "__main__":
    print("=== 游戏设备使用时长统计系统 ===")
    
    # 初始化数据库
    print("初始化数据库...")
    init_db()
    
    # 创建线程
    mqtt_thread = threading.Thread(target=start_mqtt_client, daemon=True)
    web_thread = threading.Thread(target=start_web_server, daemon=True)
    
    # 启动线程
    mqtt_thread.start()
    time.sleep(2)  # 等待 MQTT 客户端启动
    web_thread.start()
    
    print("系统启动完成!")
    print("Web 界面: http://localhost:5001/static/index.html")
    print("API 接口: http://localhost:5001/api/")
    print("按 Ctrl+C 退出")
    
    try:
        # 保持主线程运行
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\n正在关闭系统...")
        print("系统已关闭")