# -*- coding: utf-8 -*-
from flask import Flask, jsonify, request, send_from_directory, Response
from flask_cors import CORS
import json
import time
import threading
import queue

import os
from models import GameSession, DeviceStatus, DeviceRegistry, normalize_ble_id, db
from datetime import datetime, timedelta, timezone
import logging

def format_datetime_for_frontend(dt):
    """格式化日期时间为前端可用的 ISO8601 UTC(Z) 字符串"""
    if dt is None:
        return None
    # 统一转为 UTC 并返回以 Z 结尾
    dt = to_utc_datetime(dt)
    return dt.isoformat().replace('+00:00', 'Z')

def to_utc_datetime(value):
    """将数据库取出的值规范为 UTC 有时区 datetime。
    - 支持 datetime 或 str（ISO8601，可能带 Z）
    - 对 naive datetime 视为 UTC
    """
    if value is None:
        return None
    if isinstance(value, str):
        s = value
        # 处理以 Z 结尾的 UTC 字符串
        if s.endswith('Z'):
            s = s[:-1] + '+00:00'
        try:
            dt = datetime.fromisoformat(s)
        except Exception:
            # 回退常见格式
            try:
                dt = datetime.strptime(s, '%Y-%m-%d %H:%M:%S')
            except Exception:
                # 最后兜底：当前时间，避免崩溃（也可返回 None）
                dt = datetime.now(timezone.utc)
    else:
        dt = value
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)

app = Flask(__name__)
CORS(app, origins=["*"])

# 用于实时更新的队列
update_queue = queue.Queue()
clients = []

# 配置日志
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# 离线阈值（秒），默认 300
try:
    OFFLINE_WINDOW_SECONDS = int(os.environ.get('OFFLINE_WINDOW_SECONDS', '300'))
except Exception:
    OFFLINE_WINDOW_SECONDS = 300

@app.before_request
def before_request():
    """每次请求前连接数据库"""
    if db.is_closed():
        db.connect()

@app.after_request
def after_request(response):
    """每次请求后关闭数据库连接"""
    if not db.is_closed():
        db.close()
    return response

@app.route('/api/sessions', methods=['GET'])
def get_sessions():
    """获取游戏会话列表"""
    try:
        page = int(request.args.get('page', 1))
        per_page = int(request.args.get('per_page', 20))
        player_id = request.args.get('player_id')
        
        query = GameSession.select().order_by(GameSession.created_at.desc())
        
        if player_id:
            query = query.where(GameSession.player_id == player_id)
        
        # 分页
        sessions = query.paginate(page, per_page)
        
        result = []
        for session in sessions:
            result.append({
                'id': session.id,
                'player_id': session.player_id,
                'player_name': session.player_name,
                'start_time': format_datetime_for_frontend(session.start_time),
                'end_time': format_datetime_for_frontend(session.end_time),
                'duration_seconds': session.duration_seconds,
                'created_at': format_datetime_for_frontend(session.created_at)
            })
        
        return jsonify({
            'success': True,
            'data': result,
            'page': page,
            'per_page': per_page
        })
        
    except Exception as e:
        logger.error(f"获取会话列表时出错: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/device-registry', methods=['GET'])
def list_device_registry():
    try:
        page = int(request.args.get('page', 1))
        per_page = int(request.args.get('per_page', 20))
        query_kw = request.args.get('q')
        status = request.args.get('status')

        q = DeviceRegistry.select().order_by(DeviceRegistry.updated_at.desc())
        if query_kw:
            kw = f"%{query_kw}%"
            q = q.where((DeviceRegistry.ble_id.contains(query_kw)) | (DeviceRegistry.campus_name.contains(query_kw)) | (DeviceRegistry.project_name.contains(query_kw)))
        if status:
            q = q.where(DeviceRegistry.status == status)

        items = q.paginate(page, per_page)
        data = [{
            'ble_id': item.ble_id,
            'campus_name': item.campus_name,
            'project_name': item.project_name,
            'status': item.status,
            'remark': item.remark,
            'created_at': format_datetime_for_frontend(item.created_at),
            'updated_at': format_datetime_for_frontend(item.updated_at)
        } for item in items]

        return jsonify({'success': True, 'data': data, 'page': page, 'per_page': per_page})
    except Exception as e:
        logger.error(f"查询设备注册表失败: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/device-registry', methods=['POST'])
def create_device_registry():
    try:
        body = request.get_json(force=True) or {}
        ble_id_raw = body.get('ble_id', '')
        campus_name = body.get('campus_name', '')
        project_name = body.get('project_name', '')
        status = body.get('status', 'active')
        remark = body.get('remark')

        ble_id = normalize_ble_id(ble_id_raw)
        if not ble_id or not campus_name or not project_name:
            return jsonify({'success': False, 'error': 'ble_id/campus_name/project_name 不能为空'}), 400

        now_utc = datetime.now(timezone.utc)
        item = DeviceRegistry.create(
            ble_id=ble_id,
            campus_name=campus_name,
            project_name=project_name,
            status=status,
            remark=remark,
            created_at=now_utc,
            updated_at=now_utc
        )
        return jsonify({'success': True, 'data': {
            'ble_id': item.ble_id,
            'campus_name': item.campus_name,
            'project_name': item.project_name,
            'status': item.status,
            'remark': item.remark
        }})
    except Exception as e:
        logger.error(f"创建设备注册记录失败: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/device-registry/<ble_id>', methods=['PUT'])
def update_device_registry(ble_id):
    try:
        body = request.get_json(force=True) or {}
        norm = normalize_ble_id(ble_id)
        item = DeviceRegistry.get(DeviceRegistry.ble_id == norm)
        updated = False
        if 'campus_name' in body:
            item.campus_name = body['campus_name']
            updated = True
        if 'project_name' in body:
            item.project_name = body['project_name']
            updated = True
        if 'status' in body:
            item.status = body['status']
            updated = True
        if 'remark' in body:
            item.remark = body['remark']
            updated = True
        if updated:
            item.updated_at = datetime.now(timezone.utc)
            item.save()
        return jsonify({'success': True})
    except DeviceRegistry.DoesNotExist:
        return jsonify({'success': False, 'error': '记录不存在'}), 404
    except Exception as e:
        logger.error(f"更新设备注册记录失败: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/device-registry/<ble_id>', methods=['DELETE'])
def delete_device_registry(ble_id):
    try:
        norm = normalize_ble_id(ble_id)
        item = DeviceRegistry.get(DeviceRegistry.ble_id == norm)
        item.delete_instance()
        return jsonify({'success': True})
    except DeviceRegistry.DoesNotExist:
        return jsonify({'success': False, 'error': '记录不存在'}), 404
    except Exception as e:
        logger.error(f"删除设备注册记录失败: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500
        
        return jsonify({
            'success': True,
            'data': result,
            'page': page,
            'per_page': per_page
        })
        
    except Exception as e:
        logger.error(f"获取会话列表时出错: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/stats', methods=['GET'])
def get_stats():
    """获取使用统计"""
    try:
        date_str = request.args.get('date')
        if date_str:
            target_date = datetime.strptime(date_str, '%Y-%m-%d').date()
        else:
            target_date = datetime.now(timezone.utc).date()
        
        # 指定日期统计
        day_start = datetime.combine(target_date, datetime.min.time(), tzinfo=timezone.utc)
        day_end = day_start + timedelta(days=1)
        day_sessions = GameSession.select().where(
            GameSession.start_time >= day_start,
            GameSession.start_time < day_end,
            GameSession.duration_seconds.is_null(False)
        )
        
        day_total_time = sum(session.duration_seconds for session in day_sessions)
        day_session_count = day_sessions.count()
        
        # 本周统计
        week_start_date = target_date - timedelta(days=target_date.weekday())
        week_start = datetime.combine(week_start_date, datetime.min.time(), tzinfo=timezone.utc)
        week_end = week_start + timedelta(days=7)
        week_sessions = GameSession.select().where(
            GameSession.start_time >= week_start,
            GameSession.start_time < week_end,
            GameSession.duration_seconds.is_null(False)
        )
        
        week_total_time = sum(session.duration_seconds for session in week_sessions)
        week_session_count = week_sessions.count()
        
        # 活跃玩家统计
        active_players = GameSession.select(
            GameSession.player_id,
            GameSession.player_name
        ).where(
            GameSession.start_time >= target_date,
            GameSession.start_time < target_date + timedelta(days=1)
        ).distinct()
        
        # 在线设备统计（最近5分钟内有活动的设备）
        five_minutes_ago = datetime.now(timezone.utc) - timedelta(minutes=5)
        online_devices = GameSession.select(
            GameSession.player_id,
            GameSession.player_name
        ).where(
            (GameSession.end_time.is_null()) |
            (GameSession.start_time >= five_minutes_ago)
        ).distinct()
        
        return jsonify({
            'success': True,
            'data': {
                'selected_date': target_date.isoformat(),
                'day': {
                    'total_time_seconds': day_total_time,
                    'session_count': day_session_count,
                    'active_players': active_players.count()
                },
                'week': {
                    'total_time_seconds': week_total_time,
                    'session_count': week_session_count
                },
                'online_devices': online_devices.count()
            }
        })
        
    except Exception as e:
        logger.error(f"获取统计数据时出错: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/players', methods=['GET'])
def get_players():
    """获取玩家列表及其使用统计"""
    try:
        # 获取所有玩家的统计信息
        players_query = GameSession.select(
            GameSession.player_id,
            GameSession.player_name,
        ).distinct()
        
        result = []
        for player in players_query:
            # 计算该玩家的总使用时长
            player_sessions = GameSession.select().where(
                GameSession.player_id == player.player_id,
                GameSession.duration_seconds.is_null(False)
            )
            
            total_time = sum(session.duration_seconds for session in player_sessions)
            session_count = player_sessions.count()
            
            # 最后一次游戏时间 - 使用最新的活动时间
            last_session = GameSession.select().where(
                GameSession.player_id == player.player_id
            ).order_by(GameSession.start_time.desc()).first()
            
            last_played = None
            if last_session:
                # 使用最新的活动时间（开始时间或结束时间中较晚的）
                if last_session.end_time:
                    last_played = max(to_utc_datetime(last_session.start_time), to_utc_datetime(last_session.end_time))
                else:
                    last_played = to_utc_datetime(last_session.start_time)
            
            result.append({
                'player_id': player.player_id,
                'player_name': player.player_name,
                'total_time_seconds': total_time,
                'session_count': session_count,
                'last_played': format_datetime_for_frontend(last_played)
            })
        
        # 按总使用时长排序
        result.sort(key=lambda x: x['total_time_seconds'], reverse=True)
        
        return jsonify({
            'success': True,
            'data': result
        })
        
    except Exception as e:
        logger.error(f"获取玩家列表时出错: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/device-status', methods=['GET'])
def get_device_status():
    """获取设备实时状态"""
    try:
        now_utc = datetime.now(timezone.utc)
        devices_map = {}

        # 先用 DeviceStatus 构建设备视图
        for d in DeviceStatus.select():
            last_seen = to_utc_datetime(d.last_seen)
            latest_session = None
            if d.current_session_id:
                try:
                    latest_session = GameSession.get_by_id(d.current_session_id)
                except Exception:
                    latest_session = None

            status = "offline"
            if latest_session is not None and latest_session.end_time is None and last_seen and (now_utc - last_seen).total_seconds() <= OFFLINE_WINDOW_SECONDS:
                status = "playing"
            elif last_seen and (now_utc - last_seen).total_seconds() <= OFFLINE_WINDOW_SECONDS:
                status = "online"

            devices_map[d.player_id] = {
                'player_id': d.player_id,
                'player_name': d.player_name,
                'status': status,
                'current_session_id': d.current_session_id,
                'last_activity': format_datetime_for_frontend(last_seen)
            }

        # 用历史会话补全未入 DeviceStatus 的设备
        all_session_devices = GameSession.select(
            GameSession.player_id,
            GameSession.player_name
        ).distinct()
        for sdev in all_session_devices:
            if sdev.player_id in devices_map:
                continue
            latest_session = GameSession.select().where(
                GameSession.player_id == sdev.player_id
            ).order_by(GameSession.start_time.desc()).first()

            last_activity = None
            status = "offline"
            current_session_id = None
            if latest_session:
                if latest_session.end_time:
                    last_activity = max(to_utc_datetime(latest_session.start_time), to_utc_datetime(latest_session.end_time))
                else:
                    last_activity = to_utc_datetime(latest_session.start_time)
                if latest_session.end_time is None:
                    status = "playing"
                    current_session_id = latest_session.id
                else:
                    if last_activity and (now_utc - last_activity).total_seconds() <= OFFLINE_WINDOW_SECONDS:
                        status = "online"

            devices_map[sdev.player_id] = {
                'player_id': sdev.player_id,
                'player_name': sdev.player_name,
                'status': status,
                'current_session_id': current_session_id,
                'last_activity': format_datetime_for_frontend(last_activity)
            }

        devices = list(devices_map.values())
        
        # 统计各状态数量
        status_count = {
            'online': len([d for d in devices if d['status'] == 'online']),
            'playing': len([d for d in devices if d['status'] == 'playing']),
            'offline': len([d for d in devices if d['status'] == 'offline'])
        }
        
        return jsonify({
            'success': True,
            'data': {
                'devices': devices,
                'status_count': status_count,
                'total_devices': len(devices)
            }
        })
        
    except Exception as e:
        logger.error(f"获取设备状态时出错: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/campus-projects', methods=['GET'])
def get_campus_projects():
    """获取所有校区和项目列表（用于筛选）"""
    try:
        # 获取所有活跃的注册表记录
        registries = DeviceRegistry.select().where(DeviceRegistry.status == 'active')
        
        # 收集所有校区和项目
        campuses = set()
        projects = set()
        campus_projects = {}  # {校区: [项目列表]}
        
        for reg in registries:
            campuses.add(reg.campus_name)
            projects.add(reg.project_name)
            if reg.campus_name not in campus_projects:
                campus_projects[reg.campus_name] = []
            if reg.project_name not in campus_projects[reg.campus_name]:
                campus_projects[reg.campus_name].append(reg.project_name)
        
        return jsonify({
            'success': True,
            'data': {
                'campuses': sorted(list(campuses)),
                'projects': sorted(list(projects)),
                'campus_projects': {k: sorted(v) for k, v in campus_projects.items()}
            }
        })
    except Exception as e:
        logger.error(f"获取校区和项目列表失败: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/daily-chart', methods=['GET'])
def get_daily_chart():
    """获取每日使用时长图表数据"""
    try:
        days = int(request.args.get('days', 7))  # 默认7天
        start_date_str = request.args.get('start_date')
        end_date_str = request.args.get('end_date')
        campus_name = request.args.get('campus_name')
        project_name = request.args.get('project_name')
        
        # 如果提供了具体的开始和结束日期
        if start_date_str and end_date_str:
            start_date = datetime.strptime(start_date_str, '%Y-%m-%d').date()
            end_date = datetime.strptime(end_date_str, '%Y-%m-%d').date()
            days = (end_date - start_date).days + 1
        else:
            # 使用默认的天数范围
            end_date = datetime.now(timezone.utc).date()
            start_date = end_date - timedelta(days=days-1)
        
        # 如果指定了校区或项目，需要找到匹配的设备标识列表
        filter_player_ids = None
        filter_player_names = None
        if campus_name or project_name:
            query = DeviceRegistry.select(DeviceRegistry.ble_id, DeviceRegistry.campus_name, DeviceRegistry.project_name).where(DeviceRegistry.status == 'active')
            if campus_name:
                query = query.where(DeviceRegistry.campus_name == campus_name)
            if project_name:
                query = query.where(DeviceRegistry.project_name == project_name)
            
            # 获取匹配的 ble_id 列表和对应的显示名称
            matched_ble_ids = set()
            matched_display_names = set()
            for reg in query:
                matched_ble_ids.add(reg.ble_id)
                # 显示名称格式：校区-项目
                matched_display_names.add(f"{reg.campus_name}-{reg.project_name}")
            
            if matched_ble_ids or matched_display_names:
                filter_player_ids = matched_ble_ids
                filter_player_names = matched_display_names
            else:
                # 如果没有找到匹配的注册表，但指定了筛选条件，返回空数据
                filter_player_ids = set()
                filter_player_names = set()
        
        chart_data = []
        total_period_time = 0
        total_period_sessions = 0
        
        for i in range(days):
            current_date = start_date + timedelta(days=i)
            
            # 查询当天的会话数据
            day_start = datetime.combine(current_date, datetime.min.time(), tzinfo=timezone.utc)
            day_end = day_start + timedelta(days=1)
            day_sessions = GameSession.select().where(
                GameSession.start_time >= day_start,
                GameSession.start_time < day_end,
                GameSession.duration_seconds.is_null(False)
            )
            
            # 如果指定了筛选条件，过滤会话
            if filter_player_ids is not None:
                filtered_sessions = []
                for session in day_sessions:
                    # 匹配 player_id（可能是 ble_id）
                    if session.player_id in filter_player_ids:
                        filtered_sessions.append(session)
                    # 或者匹配 player_name（可能是 "校区-项目" 格式）
                    elif filter_player_names and session.player_name in filter_player_names:
                        filtered_sessions.append(session)
                day_sessions = filtered_sessions
            
            total_time = sum(session.duration_seconds for session in day_sessions)
            session_count = len(day_sessions)
            
            total_period_time += total_time
            total_period_sessions += session_count
            
            chart_data.append({
                'date': current_date.isoformat(),
                'total_time_minutes': round(total_time / 60, 1),
                'total_time_hours': round(total_time / 3600, 2),
                'session_count': session_count
            })
        
        return jsonify({
            'success': True,
            'data': {
                'daily_data': chart_data,
                'period_summary': {
                    'start_date': start_date.isoformat(),
                    'end_date': end_date.isoformat(),
                    'total_days': days,
                    'total_time_minutes': round(total_period_time / 60, 1),
                    'total_time_hours': round(total_period_time / 3600, 2),
                    'total_sessions': total_period_sessions,
                    'avg_daily_minutes': round(total_period_time / 60 / days, 1) if days > 0 else 0
                },
                'filter': {
                    'campus_name': campus_name,
                    'project_name': project_name
                }
            }
        })
        
    except Exception as e:
        logger.error(f"获取图表数据时出错: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/device/<player_id>', methods=['DELETE'])
def delete_device(player_id):
    """删除设备及其所有相关数据"""
    try:
        # 删除该设备的所有游戏会话记录
        deleted_sessions = GameSession.delete().where(
            GameSession.player_id == player_id
        ).execute()
        
        # 删除设备状态记录
        deleted_status = DeviceStatus.delete().where(
            DeviceStatus.player_id == player_id
        ).execute()
        
        # 尝试删除设备注册表记录（如果存在，基于规范化后的 BLE ID）
        # 注意：player_id 可能是规范化后的 BLE ID，也可能是原始 player_id
        deleted_registry = 0
        try:
            # 如果 player_id 是 BLE ID 格式，尝试删除注册表
            if player_id.startswith('MICROBLOCKS'):
                deleted_registry = DeviceRegistry.delete().where(
                    DeviceRegistry.ble_id == player_id
                ).execute()
        except Exception:
            pass  # 如果删除注册表失败，不影响整体删除
        
        logger.info(f"删除设备 {player_id}: {deleted_sessions} 条会话, {deleted_status} 条状态, {deleted_registry} 条注册表")
        
        return jsonify({
            'success': True,
            'message': f'成功删除设备 {player_id}：{deleted_sessions} 条会话记录，{deleted_status} 条状态记录，{deleted_registry} 条注册表记录'
        })
        
    except Exception as e:
        logger.error(f"删除设备时出错: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/session/<int:session_id>', methods=['DELETE'])
def delete_session(session_id):
    """删除单个游戏会话记录"""
    try:
        # 查找并删除指定的会话记录
        session = GameSession.get_by_id(session_id)
        session.delete_instance()
        
        logger.info(f"删除会话记录 {session_id}")
        
        return jsonify({
            'success': True,
            'message': f'成功删除会话记录 {session_id}'
        })
        
    except GameSession.DoesNotExist:
        return jsonify({'success': False, 'error': '会话记录不存在'}), 404
    except Exception as e:
        logger.error(f"删除会话记录时出错: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/daily-summary', methods=['GET'])
def get_daily_summary():
    """获取按日期汇总的使用记录"""
    try:
        days = int(request.args.get('days', 7))  # 默认显示最近7天
        end_date = datetime.now(timezone.utc).date()
        start_date = end_date - timedelta(days=days-1)
        
        daily_summary = []
        
        for i in range(days):
            current_date = start_date + timedelta(days=i)
            
            # 查询当天的会话数据
            day_start = datetime.combine(current_date, datetime.min.time(), tzinfo=timezone.utc)
            day_end = day_start + timedelta(days=1)
            day_sessions = GameSession.select().where(
                GameSession.start_time >= day_start,
                GameSession.start_time < day_end
            ).order_by(GameSession.start_time.desc())
            
            # 统计当天数据
            completed_sessions = [s for s in day_sessions if s.duration_seconds is not None]
            active_sessions = [s for s in day_sessions if s.duration_seconds is None]
            
            total_time = sum(session.duration_seconds for session in completed_sessions)
            
            # 获取当天活跃的设备
            active_devices = {}
            for session in day_sessions:
                device_id = session.player_id
                if device_id not in active_devices:
                    # 计算初始的最后活动时间
                    initial_last_activity = to_utc_datetime(session.start_time)
                    if session.end_time:
                        initial_last_activity = max(to_utc_datetime(session.start_time), to_utc_datetime(session.end_time))
                    
                    active_devices[device_id] = {
                        'player_name': session.player_name,
                        'sessions': 0,
                        'total_time': 0,
                        'last_activity': initial_last_activity
                    }
                
                active_devices[device_id]['sessions'] += 1
                if session.duration_seconds:
                    active_devices[device_id]['total_time'] += session.duration_seconds
                
                # 更新最后活动时间（考虑开始时间和结束时间）
                session_last_activity = to_utc_datetime(session.start_time)
                if session.end_time:
                    session_last_activity = max(to_utc_datetime(session.start_time), to_utc_datetime(session.end_time))
                
                if session_last_activity > active_devices[device_id]['last_activity']:
                    active_devices[device_id]['last_activity'] = session_last_activity
            
            # 格式化设备数据中的时间
            formatted_devices = []
            for device_data in active_devices.values():
                formatted_device = device_data.copy()
                formatted_device['last_activity'] = format_datetime_for_frontend(device_data['last_activity'])
                formatted_devices.append(formatted_device)
            
            daily_summary.append({
                'date': current_date.isoformat(),
                'total_time_seconds': total_time,
                'total_time_minutes': round(total_time / 60, 1),
                'completed_sessions': len(completed_sessions),
                'active_sessions': len(active_sessions),
                'total_sessions': len(day_sessions),
                'active_devices_count': len(active_devices),
                'devices': formatted_devices
            })
        
        # 按日期倒序排列（最新的在前面）
        daily_summary.reverse()
        
        return jsonify({
            'success': True,
            'data': daily_summary
        })
        
    except Exception as e:
        logger.error(f"获取每日汇总数据时出错: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/')
def index():
    """重定向到主页"""
    return send_from_directory('static', 'index.html')

@app.route('/static/<path:filename>')
def static_files(filename):
    """提供静态文件"""
    return send_from_directory('static', filename)

@app.route('/api/events')
def events():
    """Server-Sent Events 端点"""
    def event_stream():
        while True:
            try:
                # 等待更新事件，超时时间缩短到10秒
                data = update_queue.get(timeout=10)
                
                # 如果是 MQTT 更新信号，立即获取最新数据并推送
                if data.get('type') == 'mqtt_update':
                    logger.info("🔄 收到 MQTT 更新信号，推送最新数据")
                    
                    # 获取最新设备状态
                    device_data = get_latest_device_status()
                    yield f"data: {json.dumps({'type': 'device_update', 'data': device_data})}\n\n"
                    
                    # 获取最新统计数据
                    stats_data = get_latest_stats()
                    yield f"data: {json.dumps({'type': 'stats_update', 'data': stats_data})}\n\n"
                else:
                    # 其他类型的更新
                    yield f"data: {json.dumps(data)}\n\n"
                    
            except queue.Empty:
                # 发送心跳
                yield f"data: {json.dumps({'type': 'heartbeat'})}\n\n"
    
    return Response(event_stream(), mimetype="text/event-stream",
                   headers={
                       'Cache-Control': 'no-cache',
                       'Connection': 'keep-alive',
                       'Access-Control-Allow-Origin': '*',
                       'Access-Control-Allow-Headers': 'Cache-Control'
                   })

def get_latest_device_status():
    """获取最新设备状态"""
    try:
        # 复用 get_device_status 的逻辑
        with app.test_request_context():
            resp = get_device_status()
            data = resp.get_json()
            return {'devices': data['data']['devices']} if data and data.get('success') else {'devices': []}
    except Exception as e:
        logger.error(f"获取设备状态失败: {e}")
        return {'devices': []}

def get_latest_stats():
    """获取最新统计数据"""
    try:
        today = datetime.now(timezone.utc).date()
        today_start = datetime.combine(today, datetime.min.time(), tzinfo=timezone.utc)
        today_sessions = GameSession.select().where(
            GameSession.start_time >= today_start,
            GameSession.duration_seconds.is_null(False)
        )
        
        total_time = sum(session.duration_seconds for session in today_sessions)
        session_count = today_sessions.count()
        
        return {
            'total_time_seconds': total_time,
            'session_count': session_count
        }
    except Exception as e:
        logger.error(f"获取统计数据失败: {e}")
        return {'total_time_seconds': 0, 'session_count': 0}

def broadcast_update(update_type, data):
    """广播更新到所有客户端"""
    try:
        update_data = {
            'type': update_type,
            'data': data,
            'timestamp': time.time()
        }
        update_queue.put(update_data)
        logger.info(f"广播更新: {update_type}")
    except Exception as e:
        logger.error(f"广播更新失败: {e}")

@app.route('/api/debug-time', methods=['GET'])
def debug_time():
    """调试时间显示问题"""
    try:
        from datetime import datetime, timezone
        
        # 获取一些示例数据
        sessions = GameSession.select().limit(5)
        debug_data = []
        
        for session in sessions:
            debug_data.append({
                'player_name': session.player_name,
                'start_time_raw': str(session.start_time),
                'start_time_iso': session.start_time.isoformat() if session.start_time else None,
                'end_time_raw': str(session.end_time) if session.end_time else None,
                'end_time_iso': session.end_time.isoformat() if session.end_time else None,
                'server_time_now': datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z'),
                'created_at': session.created_at.isoformat() if session.created_at else None
            })
        
        return jsonify({
            'success': True,
            'server_timezone': str(datetime.now().astimezone().tzinfo),
            'data': debug_data
        })
        
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/trigger-update', methods=['POST'])
def trigger_update():
    """触发前端实时更新"""
    try:
        # 获取最新的设备状态和统计数据
        from datetime import datetime, timedelta, timezone
        
        # 获取设备状态（与 /api/device-status 一致）
        with app.test_request_context():
            device_resp = get_device_status()
            device_json = device_resp.get_json()
            devices = device_json['data']['devices'] if device_json and device_json.get('success') else []
        
        # 广播设备状态更新
        broadcast_update('device_update', {'devices': devices})
        
        # 获取今日统计
        today = datetime.now(timezone.utc).date()
        today_start = datetime.combine(today, datetime.min.time(), tzinfo=timezone.utc)
        today_sessions = GameSession.select().where(
            GameSession.start_time >= today_start,
            GameSession.duration_seconds.is_null(False)
        )
        
        today_total_time = sum(session.duration_seconds for session in today_sessions)
        today_session_count = today_sessions.count()
        
        # 广播统计更新
        broadcast_update('stats_update', {
            'total_time_seconds': today_total_time,
            'session_count': today_session_count
        })
        
        return jsonify({'success': True})
    except Exception as e:
        logger.error(f"触发更新失败: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500

if __name__ == '__main__':
    # 初始化数据库
    from models import init_db
    init_db()
    
    app.run(debug=True, host='0.0.0.0', port=5001)