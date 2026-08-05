"""访问流量统计。

请求由 before_request 记录到 MongoDB traffic 集合
（{path, method, ip, time}）。Phase 6 提供管理面板查询接口。
"""
import time

from . import state


def record():
    if state.traffic is None:
        return
    from flask import request
    path = request.path
    if '/static/' in path or path.endswith('.js') or path.endswith('.css'):
        return
    try:
        state.traffic.insert_one({
            'path': path,
            'method': request.method,
            'ip': request.remote_addr or '',
            'time': time.time(),
        })
    except Exception:
        state.logger.exception('记录流量失败')


def summary():
    """返回 {total, today, today_paths, top_paths, unique_ips, recent_days}。"""
    if state.traffic is None:
        return {'total': 0, 'today': 0, 'top_paths': [], 'unique_ips': 0, 'recent_days': []}
    today_start = time.time() - time.time() % 86400 - 8 * 3600  # 近似北京时间零点
    today = state.traffic.count_documents({'time': {'$gte': today_start}})
    total = state.traffic.estimated_document_count()
    top = list(state.traffic.aggregate([
        {'$group': {'_id': '$path', 'count': {'$sum': 1}}},
        {'$sort': {'count': -1}},
        {'$limit': 10},
    ]))
    unique = len(state.traffic.distinct('ip'))
    days = []
    for offset in range(6, -1, -1):
        day_start = today_start - offset * 86400
        day_end = day_start + 86400
        days.append({
            'day': time.strftime('%m-%d', time.localtime(day_start + 8 * 3600)),
            'count': state.traffic.count_documents({'time': {'$gte': day_start, '$lt': day_end}}),
        })
    return {
        'total': total,
        'today': today,
        'top_paths': [{'path': item['_id'], 'count': item['count']} for item in top],
        'unique_ips': unique,
        'recent_days': days,
    }
