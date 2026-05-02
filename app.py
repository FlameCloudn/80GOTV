# Flask 主入口 - 所有路由
from flask import Flask, render_template, request, redirect, url_for, session, flash, jsonify
from werkzeug.security import check_password_hash, generate_password_hash
from werkzeug.utils import secure_filename
from config import Config
from models import get_db, init_tables
import os
import json
import uuid
from datetime import datetime
from functools import wraps
from utils.stats_calc import calculate_rating

app = Flask(__name__)
app.config.from_object(Config)

# ============ 辅助函数 ============

def login_required(f):
    """后台登录保护装饰器"""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'admin_id' not in session:
            return redirect(url_for('admin_login'))
        return f(*args, **kwargs)
    return decorated_function

def allowed_file(filename):
    """检查文件扩展名"""
    return '.' in filename and \
           filename.rsplit('.', 1)[1].lower() in Config.ALLOWED_EXTENSIONS

# ============ 前台路由 ============

@app.route('/')
def index():
    """首页"""
    conn = get_db()
    news = conn.execute(
        "SELECT * FROM news ORDER BY publish_time DESC LIMIT 6"
    ).fetchall()
    
    matches = conn.execute("""
        SELECT m.*, t1.name AS team1_name, t2.name AS team2_name,
               t1.short_name AS t1s, t2.short_name AS t2s, e.name AS event_name
        FROM matches m
        LEFT JOIN teams t1 ON m.team1_id=t1.id
        LEFT JOIN teams t2 ON m.team2_id=t2.id
        LEFT JOIN events e ON m.event_id=e.id
        WHERE m.status IN ('upcoming','live')
        ORDER BY m.match_time LIMIT 8
    """).fetchall()
    
    recent = conn.execute("""
        SELECT m.*, t1.name AS team1_name, t2.name AS team2_name,
               t1.short_name AS t1s, t2.short_name AS t2s
        FROM matches m
        LEFT JOIN teams t1 ON m.team1_id=t1.id
        LEFT JOIN teams t2 ON m.team2_id=t2.id
        WHERE m.status='completed'
        ORDER BY m.match_time DESC LIMIT 5
    """).fetchall()
    
    # 本周最佳选手（简单取 Rating 最高的）
    top_player = conn.execute("""
        SELECT p.nickname, p.id, t.short_name AS team, AVG(ms.rating) AS avg_rating
        FROM match_stats ms
        JOIN players p ON ms.player_id=p.id
        JOIN teams t ON p.team_id=t.id
        GROUP BY p.id
        ORDER BY avg_rating DESC LIMIT 1
    """).fetchone()
    
    conn.close()
    return render_template('index.html', news=news, matches=matches, 
                          recent=recent, top_player=top_player)

@app.route('/news')
def news_list():
    """新闻列表"""
    page = request.args.get('page', 1, type=int)
    per_page = 20
    offset = (page - 1) * per_page
    
    conn = get_db()
    news = conn.execute(
        "SELECT * FROM news ORDER BY publish_time DESC LIMIT ? OFFSET ?",
        (per_page, offset)
    ).fetchall()
    
    total = conn.execute("SELECT COUNT(*) as cnt FROM news").fetchone()['cnt']
    conn.close()
    
    total_pages = (total + per_page - 1) // per_page
    return render_template('news.html', news=news, page=page, total_pages=total_pages)

@app.route('/news/<int:news_id>')
def news_detail(news_id):
    """新闻详情"""
    conn = get_db()
    news = conn.execute("SELECT * FROM news WHERE id=?", (news_id,)).fetchone()
    conn.close()
    
    if not news:
        return "新闻不存在", 404
    return render_template('news_detail.html', news=news)

@app.route('/matches')
def matches_list():
    """比赛列表（未开始+进行中）"""
    event_filter = request.args.get('event', '')
    status_filter = request.args.get('status', '')
    
    conn = get_db()
    query = """
        SELECT m.*, t1.name AS team1_name, t2.name AS team2_name,
               t1.short_name AS t1s, t2.short_name AS t2s, e.name AS event_name
        FROM matches m
        LEFT JOIN teams t1 ON m.team1_id=t1.id
        LEFT JOIN teams t2 ON m.team2_id=t2.id
        LEFT JOIN events e ON m.event_id=e.id
        WHERE m.status IN ('upcoming','live')
    """
    params = []
    
    if event_filter:
        query += " AND m.event_id=?"
        params.append(event_filter)
    if status_filter:
        query += " AND m.status=?"
        params.append(status_filter)
    
    query += " ORDER BY m.match_time"
    matches = conn.execute(query, params).fetchall()
    
    events = conn.execute("SELECT * FROM events ORDER BY start_date DESC").fetchall()
    conn.close()
    
    return render_template('matches.html', matches=matches, events=events,
                          event_filter=event_filter, status_filter=status_filter)

@app.route('/results')
def results_list():
    """赛果列表（已结束）"""
    event_filter = request.args.get('event', '')
    page = request.args.get('page', 1, type=int)
    per_page = 20
    offset = (page - 1) * per_page
    
    conn = get_db()
    query = """
        SELECT m.*, t1.name AS team1_name, t2.name AS team2_name,
               t1.short_name AS t1s, t2.short_name AS t2s, e.name AS event_name
        FROM matches m
        LEFT JOIN teams t1 ON m.team1_id=t1.id
        LEFT JOIN teams t2 ON m.team2_id=t2.id
        LEFT JOIN events e ON m.event_id=e.id
        WHERE m.status='completed'
    """
    params = []
    
    if event_filter:
        query += " AND m.event_id=?"
        params.append(event_filter)
    
    query += " ORDER BY m.match_time DESC LIMIT ? OFFSET ?"
    params.extend([per_page, offset])
    
    matches = conn.execute(query, params).fetchall()
    events = conn.execute("SELECT * FROM events ORDER BY start_date DESC").fetchall()
    
    total_query = "SELECT COUNT(*) as cnt FROM matches WHERE status='completed'"
    if event_filter:
        total_query += " AND event_id=?"
        total = conn.execute(total_query, (event_filter,)).fetchone()['cnt']
    else:
        total = conn.execute(total_query).fetchone()['cnt']
    
    conn.close()
    
    total_pages = (total + per_page - 1) // per_page
    return render_template('results.html', matches=matches, events=events,
                          event_filter=event_filter, page=page, total_pages=total_pages)

@app.route('/matches/<int:match_id>')
def match_detail(match_id):
    """比赛详情"""
    conn = get_db()
    match = conn.execute("""
        SELECT m.*, t1.name AS team1_name, t2.name AS team2_name,
               t1.short_name AS t1s, t2.short_name AS t2s, 
               e.name AS event_name, e.id AS event_id
        FROM matches m
        LEFT JOIN teams t1 ON m.team1_id=t1.id
        LEFT JOIN teams t2 ON m.team2_id=t2.id
        LEFT JOIN events e ON m.event_id=e.id
        WHERE m.id=?
    """, (match_id,)).fetchone()
    
    if not match:
        conn.close()
        return "比赛不存在", 404
    
       # 获取比赛数据
    stats = conn.execute("""
        SELECT ms.*, p.nickname, p.id AS player_id, t.short_name AS team_short
        FROM match_stats ms
        JOIN players p ON ms.player_id=p.id
        JOIN teams t ON ms.team_id=t.id
        WHERE ms.match_id=?
        ORDER BY ms.map_name, ms.team_id, ms.rating DESC
    """, (match_id,)).fetchall()
    
    conn.close()
    
    # 每图比分 + 分图 stats（按队伍分好）
    map_scores = []
    for idx, (mn, t1, t2) in enumerate([
        (match['map1'], match['map1_t1'], match['map1_t2']),
        (match['map2'], match['map2_t1'], match['map2_t2']),
        (match['map3'], match['map3_t1'], match['map3_t2']),
    ]):
        if mn:
            all_for_map = [s for s in stats if s['map_name'] == mn]
            t1s = [s for s in all_for_map if s['team_id'] == match['team1_id']]
            t2s = [s for s in all_for_map if s['team_id'] == match['team2_id']]
            map_scores.append({
                'name': mn,
                'index': idx + 1,
                't1': t1 or 0,
                't2': t2 or 0,
                'team1_stats': t1s,
                'team2_stats': t2s,
            })
    
    # 总览：按选手聚合
    from collections import defaultdict
    team1_agg = defaultdict(lambda: {'kills':0,'deaths':0,'assists':0,'adr':0,'rating':0,'kast':0,'hs':0,'maps':0})
    team2_agg = defaultdict(lambda: {'kills':0,'deaths':0,'assists':0,'adr':0,'rating':0,'kast':0,'hs':0,'maps':0})
    
    for s in stats:
        agg = team1_agg if s['team_id'] == match['team1_id'] else team2_agg
        pid = s['player_id']
        agg[pid]['kills'] += s['kills']
        agg[pid]['deaths'] += s['deaths']
        agg[pid]['assists'] += s['assists']
        agg[pid]['adr'] += s['adr']
        agg[pid]['rating'] += s['rating']
        agg[pid]['kast'] += s['kast']
        agg[pid]['hs'] += s['headshot_percentage']
        agg[pid]['maps'] += 1
        agg[pid]['nickname'] = s['nickname']
        agg[pid]['player_id'] = pid
    
    def build_overall(agg_dict):
        result = []
        for pid, d in agg_dict.items():
            m = d['maps']
            result.append({
                'player_id': pid,
                'nickname': d['nickname'],
                'kills': d['kills'],
                'deaths': d['deaths'],
                'assists': d['assists'],
                'adr': round(d['adr'] / m, 1) if m else 0,
                'rating': round(d['rating'] / m, 2) if m else 0,
                'kast': round(d['kast'] / m, 1) if m else 0,
                'headshot_percentage': round(d['hs'] / m, 1) if m else 0,
                'maps': m,
            })
        result.sort(key=lambda x: x['rating'], reverse=True)
        return result
    
    overall_t1 = build_overall(team1_agg)
    overall_t2 = build_overall(team2_agg)
    
    return render_template('match_detail.html', match=match, map_scores=map_scores,
                          overall_t1=overall_t1, overall_t2=overall_t2)
    
@app.route('/events')
def events_list():
    """赛事列表"""
    conn = get_db()
    events = conn.execute("""
        SELECT e.*, COUNT(DISTINCT m.id) AS match_count,
               COUNT(DISTINCT m.team1_id) + COUNT(DISTINCT m.team2_id) AS team_count
        FROM events e
        LEFT JOIN matches m ON e.id=m.event_id
        GROUP BY e.id
        ORDER BY e.start_date DESC
    """).fetchall()
    conn.close()
    
    return render_template('events.html', events=events)

@app.route('/events/<int:event_id>')
def event_detail(event_id):
    """赛事详情"""
    conn = get_db()
    event = conn.execute("SELECT * FROM events WHERE id=?", (event_id,)).fetchone()
    
    if not event:
        conn.close()
        return "赛事不存在", 404
    
    matches = conn.execute("""
        SELECT m.*, t1.name AS team1_name, t2.name AS team2_name,
               t1.short_name AS t1s, t2.short_name AS t2s
        FROM matches m
        LEFT JOIN teams t1 ON m.team1_id=t1.id
        LEFT JOIN teams t2 ON m.team2_id=t2.id
        WHERE m.event_id=?
        ORDER BY m.match_time
    """, (event_id,)).fetchall()
    
    # 获取参赛队伍
    teams = conn.execute("""
        SELECT DISTINCT t.* FROM teams t
        JOIN matches m ON (t.id=m.team1_id OR t.id=m.team2_id)
        WHERE m.event_id=?
    """, (event_id,)).fetchall()
    
    conn.close()
    
    return render_template('event_detail.html', event=event, matches=matches, teams=teams)

@app.route('/players')
def players_list():
    """选手列表"""
    team_filter = request.args.get('team', '')
    
    conn = get_db()
    query = """
        SELECT p.*, t.name AS team_name, t.short_name AS team_short,
               AVG(ms.rating) AS avg_rating, AVG(ms.kills) AS avg_kills,
               AVG(ms.deaths) AS avg_deaths, COUNT(ms.id) AS match_count
        FROM players p
        LEFT JOIN teams t ON p.team_id=t.id
        LEFT JOIN match_stats ms ON p.id=ms.player_id
    """
    params = []
    
    if team_filter:
        query += " WHERE p.team_id=?"
        params.append(team_filter)
    
    query += " GROUP BY p.id ORDER BY avg_rating DESC"
    players = conn.execute(query, params).fetchall()
    
    teams = conn.execute("SELECT * FROM teams ORDER BY name").fetchall()
    conn.close()
    
    return render_template('players.html', players=players, teams=teams, team_filter=team_filter)

@app.route('/players/<int:player_id>')
def player_detail(player_id):
    """选手详情"""
    conn = get_db()
    player = conn.execute("""
        SELECT p.*, t.name AS team_name, t.short_name AS team_short
        FROM players p
        LEFT JOIN teams t ON p.team_id=t.id
        WHERE p.id=?
    """, (player_id,)).fetchone()
    
    if not player:
        conn.close()
        return "选手不存在", 404
    
    # 总体统计
    overall = conn.execute("""
        SELECT COUNT(*) AS matches, SUM(kills) AS total_kills, 
               SUM(deaths) AS total_deaths, SUM(assists) AS total_assists,
               AVG(rating) AS avg_rating, AVG(adr) AS avg_adr,
               AVG(kast) AS avg_kast, AVG(headshot_percentage) AS avg_hs
        FROM match_stats WHERE player_id=?
    """, (player_id,)).fetchone()
    
    # 最近比赛
    recent_matches = conn.execute("""
        SELECT m.*, ms.kills, ms.deaths, ms.assists, ms.rating, ms.adr,
               t1.name AS team1_name, t2.name AS team2_name,
               t1.short_name AS t1s, t2.short_name AS t2s,
               e.name AS event_name
        FROM match_stats ms
        JOIN matches m ON ms.match_id=m.id
        LEFT JOIN teams t1 ON m.team1_id=t1.id
        LEFT JOIN teams t2 ON m.team2_id=t2.id
        LEFT JOIN events e ON m.event_id=e.id
        WHERE ms.player_id=?
        ORDER BY m.match_time DESC LIMIT 10
    """, (player_id,)).fetchall()
    
    conn.close()
    
    return render_template('player_detail.html', player=player, 
                          overall=overall, recent_matches=recent_matches)

@app.route('/stats')
def stats_page():
    """数据排行榜"""
    metric = request.args.get('metric', 'rating')
    event_filter = request.args.get('event', '')
    
    # 指标映射
    metric_map = {
        'rating': 'AVG(ms.rating)',
        'kd': '(SUM(ms.kills) * 1.0 / NULLIF(SUM(ms.deaths), 0))',
        'adr': 'AVG(ms.adr)',
        'kpr': 'AVG(ms.kpr)',
        'kast': 'AVG(ms.kast)',
        'impact': 'AVG(ms.impact)',
        'hs': 'AVG(ms.headshot_percentage)',
        'clutch': 'SUM(ms.clutches_won)'
    }
    
    order_by = metric_map.get(metric, 'AVG(ms.rating)')
    
    conn = get_db()
    query = f"""
        SELECT p.nickname, p.id, t.short_name AS team,
               {order_by} AS value,
               COUNT(ms.id) AS matches
        FROM match_stats ms
        JOIN players p ON ms.player_id=p.id
        JOIN teams t ON p.team_id=t.id
        JOIN matches m ON ms.match_id=m.id
    """
    params = []
    
    if event_filter:
        query += " WHERE m.event_id=?"
        params.append(event_filter)
    
    query += f" GROUP BY p.id HAVING matches >= 3 ORDER BY value DESC LIMIT 20"
    
    rankings = conn.execute(query, params).fetchall()
    events = conn.execute("SELECT * FROM events ORDER BY start_date DESC").fetchall()
    conn.close()
    
    return render_template('stats.html', rankings=rankings, events=events,
                          metric=metric, event_filter=event_filter)

# ============ 后台路由 ============

@app.route('/admin/login', methods=['GET', 'POST'])
def admin_login():
    """后台登录"""
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        
        conn = get_db()
        admin = conn.execute(
            "SELECT * FROM admins WHERE username=?", (username,)
        ).fetchone()
        conn.close()
        
        if admin and check_password_hash(admin['password_hash'], password):
            session['admin_id'] = admin['id']
            session['admin_username'] = admin['username']
            flash('登录成功', 'success')
            return redirect(url_for('admin_dashboard'))
        else:
            flash('用户名或密码错误', 'error')
    
    return render_template('admin/login.html')

@app.route('/admin/logout')
def admin_logout():
    """后台登出"""
    session.clear()
    flash('已退出登录', 'success')
    return redirect(url_for('admin_login'))

@app.route('/admin')
@login_required
def admin_dashboard():
    """后台首页"""
    conn = get_db()
    stats = {
        'teams': conn.execute("SELECT COUNT(*) as cnt FROM teams").fetchone()['cnt'],
        'players': conn.execute("SELECT COUNT(*) as cnt FROM players").fetchone()['cnt'],
        'events': conn.execute("SELECT COUNT(*) as cnt FROM events").fetchone()['cnt'],
        'matches': conn.execute("SELECT COUNT(*) as cnt FROM matches").fetchone()['cnt'],
        'news': conn.execute("SELECT COUNT(*) as cnt FROM news").fetchone()['cnt'],
    }
    conn.close()
    return render_template('admin/dashboard.html', stats=stats)

# ---- 队伍管理 ----

@app.route('/admin/teams')
@login_required
def admin_teams():
    """队伍列表"""
    conn = get_db()
    teams = conn.execute("SELECT * FROM teams ORDER BY created_at DESC").fetchall()
    conn.close()
    return render_template('admin/teams.html', teams=teams)

@app.route('/admin/teams/add', methods=['GET', 'POST'])
@login_required
def admin_teams_add():
    """添加队伍"""
    if request.method == 'POST':
        name = request.form.get('name')
        short_name = request.form.get('short_name')
        description = request.form.get('description')
        
        conn = get_db()
        conn.execute(
            "INSERT INTO teams(name, short_name, description) VALUES(?,?,?)",
            (name, short_name, description)
        )
        conn.commit()
        conn.close()
        
        flash('队伍添加成功', 'success')
        return redirect(url_for('admin_teams'))
    
    return render_template('admin/teams_form.html', team=None)

@app.route('/admin/teams/edit/<int:team_id>', methods=['GET', 'POST'])
@login_required
def admin_teams_edit(team_id):
    """编辑队伍"""
    conn = get_db()
    
    if request.method == 'POST':
        name = request.form.get('name')
        short_name = request.form.get('short_name')
        description = request.form.get('description')
        
        conn.execute(
            "UPDATE teams SET name=?, short_name=?, description=? WHERE id=?",
            (name, short_name, description, team_id)
        )
        conn.commit()
        conn.close()
        
        flash('队伍更新成功', 'success')
        return redirect(url_for('admin_teams'))
    
    team = conn.execute("SELECT * FROM teams WHERE id=?", (team_id,)).fetchone()
    conn.close()
    
    return render_template('admin/teams_form.html', team=team)

@app.route('/admin/teams/delete/<int:team_id>')
@login_required
def admin_teams_delete(team_id):
    """删除队伍"""
    try:
        conn = get_db()
        conn.execute("DELETE FROM teams WHERE id=?", (team_id,))
        conn.commit()
        conn.close()
        flash('队伍删除成功', 'success')
    except Exception as e:
        flash(f'删除失败：{str(e)}', 'error')
    return redirect(url_for('admin_teams'))

# ---- 选手管理 ----

@app.route('/admin/players')
@login_required
def admin_players():
    """选手列表"""
    conn = get_db()
    players = conn.execute("""
        SELECT p.*, t.name AS team_name
        FROM players p
        LEFT JOIN teams t ON p.team_id=t.id
        ORDER BY p.created_at DESC
    """).fetchall()
    conn.close()
    return render_template('admin/players.html', players=players)

@app.route('/admin/players/add', methods=['GET', 'POST'])
@login_required
def admin_players_add():
    """添加选手"""
    conn = get_db()
    
    if request.method == 'POST':
        nickname = request.form.get('nickname')
        real_name = request.form.get('real_name')
        team_id = request.form.get('team_id')
        steam_id = request.form.get('steam_id')
        
        # 处理头像上传
        avatar_filename = None
        if 'avatar' in request.files:
            file = request.files['avatar']
            if file and file.filename and allowed_file(file.filename):
                ext = file.filename.rsplit('.', 1)[1].lower()
                avatar_filename = f"{uuid.uuid4().hex}.{ext}"
                avatar_path = os.path.join(app.root_path, 'static', 'avatars', avatar_filename)
                os.makedirs(os.path.dirname(avatar_path), exist_ok=True)
                file.save(avatar_path)
        
        conn.execute(
            "INSERT INTO players(nickname, real_name, team_id, steam_id, avatar) VALUES(?,?,?,?,?)",
            (nickname, real_name, team_id if team_id else None, steam_id, avatar_filename)
        )
        conn.commit()
        conn.close()
        
        flash('选手添加成功', 'success')
        return redirect(url_for('admin_players'))
    
    teams = conn.execute("SELECT * FROM teams ORDER BY name").fetchall()
    conn.close()
    return render_template('admin/players_form.html', player=None, teams=teams)

@app.route('/admin/players/edit/<int:player_id>', methods=['GET', 'POST'])
@login_required
def admin_players_edit(player_id):
    """编辑选手"""
    conn = get_db()
    
    if request.method == 'POST':
        nickname = request.form.get('nickname')
        real_name = request.form.get('real_name')
        team_id = request.form.get('team_id')
        steam_id = request.form.get('steam_id')
        
        # 处理头像上传
        avatar_filename = None
        if 'avatar' in request.files:
            file = request.files['avatar']
            if file and file.filename and allowed_file(file.filename):
                ext = file.filename.rsplit('.', 1)[1].lower()
                avatar_filename = f"{uuid.uuid4().hex}.{ext}"
                avatar_path = os.path.join(app.root_path, 'static', 'avatars', avatar_filename)
                os.makedirs(os.path.dirname(avatar_path), exist_ok=True)
                file.save(avatar_path)
        
        if avatar_filename:
            conn.execute(
                "UPDATE players SET nickname=?, real_name=?, team_id=?, steam_id=?, avatar=? WHERE id=?",
                (nickname, real_name, team_id if team_id else None, steam_id, avatar_filename, player_id)
            )
        else:
            conn.execute(
                "UPDATE players SET nickname=?, real_name=?, team_id=?, steam_id=? WHERE id=?",
                (nickname, real_name, team_id if team_id else None, steam_id, player_id)
            )
        conn.commit()
        conn.close()
        
        flash('选手更新成功', 'success')
        return redirect(url_for('admin_players'))
    
    player = conn.execute("SELECT * FROM players WHERE id=?", (player_id,)).fetchone()
    teams = conn.execute("SELECT * FROM teams ORDER BY name").fetchall()
    conn.close()
    
    return render_template('admin/players_form.html', player=player, teams=teams)

@app.route('/admin/players/delete/<int:player_id>')
@login_required
def admin_players_delete(player_id):
    """删除选手"""
    try:
        conn = get_db()
        conn.execute("DELETE FROM players WHERE id=?", (player_id,))
        conn.commit()
        conn.close()
        flash('选手删除成功', 'success')
    except Exception as e:
        flash(f'删除失败：{str(e)}', 'error')
    return redirect(url_for('admin_players'))

# ---- 赛事管理 ----

@app.route('/admin/events')
@login_required
def admin_events():
    """赛事列表"""
    conn = get_db()
    events = conn.execute("SELECT * FROM events ORDER BY start_date DESC").fetchall()
    conn.close()
    return render_template('admin/events.html', events=events)

@app.route('/admin/events/add', methods=['GET', 'POST'])
@login_required
def admin_events_add():
    """添加赛事"""
    if request.method == 'POST':
        name = request.form.get('name')
        description = request.form.get('description')
        start_date = request.form.get('start_date')
        end_date = request.form.get('end_date')
        format_type = request.form.get('format')
        status = request.form.get('status')
        
        conn = get_db()
        conn.execute(
            """INSERT INTO events(name, description, start_date, end_date, format, status) 
               VALUES(?,?,?,?,?,?)""",
            (name, description, start_date, end_date, format_type, status)
        )
        conn.commit()
        conn.close()
        
        flash('赛事添加成功', 'success')
        return redirect(url_for('admin_events'))
    
    return render_template('admin/events_form.html', event=None)

@app.route('/admin/events/edit/<int:event_id>', methods=['GET', 'POST'])
@login_required
def admin_events_edit(event_id):
    """编辑赛事"""
    conn = get_db()
    
    if request.method == 'POST':
        name = request.form.get('name')
        description = request.form.get('description')
        start_date = request.form.get('start_date')
        end_date = request.form.get('end_date')
        format_type = request.form.get('format')
        status = request.form.get('status')
        
        conn.execute(
            """UPDATE events SET name=?, description=?, start_date=?, 
               end_date=?, format=?, status=? WHERE id=?""",
            (name, description, start_date, end_date, format_type, status, event_id)
        )
        conn.commit()
        conn.close()
        
        flash('赛事更新成功', 'success')
        return redirect(url_for('admin_events'))
    
    event = conn.execute("SELECT * FROM events WHERE id=?", (event_id,)).fetchone()
    conn.close()
    
    return render_template('admin/events_form.html', event=event)

@app.route('/admin/events/delete/<int:event_id>')
@login_required
def admin_events_delete(event_id):
    """删除赛事"""
    try:
        conn = get_db()
        conn.execute("DELETE FROM events WHERE id=?", (event_id,))
        conn.commit()
        conn.close()
        flash('赛事删除成功', 'success')
    except Exception as e:
        flash(f'删除失败：{str(e)}', 'error')
    return redirect(url_for('admin_events'))

# ---- 比赛管理 ----

@app.route('/admin/matches')
@login_required
def admin_matches():
    """比赛列表"""
    conn = get_db()
    matches = conn.execute("""
        SELECT m.*, t1.name AS team1_name, t2.name AS team2_name, e.name AS event_name
        FROM matches m
        LEFT JOIN teams t1 ON m.team1_id=t1.id
        LEFT JOIN teams t2 ON m.team2_id=t2.id
        LEFT JOIN events e ON m.event_id=e.id
        ORDER BY m.match_time DESC
    """).fetchall()
    conn.close()
    return render_template('admin/matches.html', matches=matches)

@app.route('/admin/matches/add', methods=['GET', 'POST'])
@login_required
def admin_matches_add():
    """添加比赛"""
    conn = get_db()
    
    if request.method == 'POST':
        event_id = request.form.get('event_id')
        team1_id = request.form.get('team1_id')
        team2_id = request.form.get('team2_id')
        match_time = request.form.get('match_time')
        bo_format = request.form.get('bo_format')
        status = request.form.get('status')
        team1_score = request.form.get('team1_score', 0)
        team2_score = request.form.get('team2_score', 0)
        map1 = request.form.get('map1', '')
        map1_t1 = request.form.get('map1_t1', 0)
        map1_t2 = request.form.get('map1_t2', 0)
        map2 = request.form.get('map2', '')
        map2_t1 = request.form.get('map2_t1', 0)
        map2_t2 = request.form.get('map2_t2', 0)
        map3 = request.form.get('map3', '')
        map3_t1 = request.form.get('map3_t1', 0)
        map3_t2 = request.form.get('map3_t2', 0)
        
        conn.execute(
            """INSERT INTO matches(event_id, team1_id, team2_id, team1_score, team2_score,
               match_time, bo_format, status, map_pool,
               map1, map1_t1, map1_t2, map2, map2_t1, map2_t2, map3, map3_t1, map3_t2)
               VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (event_id, team1_id, team2_id, team1_score, team2_score,
             match_time, bo_format, status, json.dumps(['de_mirage', 'de_dust2', 'de_inferno']),
             map1, map1_t1, map1_t2, map2, map2_t1, map2_t2, map3, map3_t1, map3_t2)
        )
        conn.commit()
        conn.close()
        
        flash('比赛添加成功', 'success')
        return redirect(url_for('admin_matches'))
    
    events = conn.execute("SELECT * FROM events ORDER BY start_date DESC").fetchall()
    teams = conn.execute("SELECT * FROM teams ORDER BY name").fetchall()
    conn.close()
    
    return render_template('admin/matches_form.html', match=None, events=events, teams=teams)

@app.route('/admin/matches/edit/<int:match_id>', methods=['GET', 'POST'])
@login_required
def admin_matches_edit(match_id):
    """编辑比赛"""
    conn = get_db()
    
    if request.method == 'POST':
        event_id = request.form.get('event_id')
        team1_id = request.form.get('team1_id')
        team2_id = request.form.get('team2_id')
        match_time = request.form.get('match_time')
        bo_format = request.form.get('bo_format')
        status = request.form.get('status')
        map1 = request.form.get('map1', '')
        map2 = request.form.get('map2', '')
        map3 = request.form.get('map3', '')
        map1_t1 = request.form.get('map1_t1', 0)
        map1_t2 = request.form.get('map1_t2', 0)
        map2_t1 = request.form.get('map2_t1', 0)
        map2_t2 = request.form.get('map2_t2', 0)
        map3_t1 = request.form.get('map3_t1', 0)
        map3_t2 = request.form.get('map3_t2', 0)
        team1_score = request.form.get('team1_score', 0)
        team2_score = request.form.get('team2_score', 0)
        
        conn.execute(
            """UPDATE matches SET event_id=?, team1_id=?, team2_id=?, team1_score=?,
               team2_score=?, match_time=?, bo_format=?, status=?,
               map1=?, map1_t1=?, map1_t2=?,
               map2=?, map2_t1=?, map2_t2=?,
               map3=?, map3_t1=?, map3_t2=?
               WHERE id=?""",
            (event_id, team1_id, team2_id, team1_score, team2_score,
             match_time, bo_format, status,
             map1, map1_t1, map1_t2,
             map2, map2_t1, map2_t2,
             map3, map3_t1, map3_t2,
             match_id)
        )
        conn.commit()
        conn.close()
        
        flash('比赛更新成功', 'success')
        return redirect(url_for('admin_matches'))
    
    match = conn.execute("SELECT * FROM matches WHERE id=?", (match_id,)).fetchone()
    events = conn.execute("SELECT * FROM events ORDER BY start_date DESC").fetchall()
    teams = conn.execute("SELECT * FROM teams ORDER BY name").fetchall()
    conn.close()
    
    return render_template('admin/matches_form.html', match=match, events=events, teams=teams)

@app.route('/admin/matches/delete/<int:match_id>')
@login_required
def admin_matches_delete(match_id):
    """删除比赛"""
    try:
        conn = get_db()
        conn.execute("DELETE FROM matches WHERE id=?", (match_id,))
        conn.commit()
        conn.close()
        flash('比赛删除成功', 'success')
    except Exception as e:
        flash(f'删除失败：{str(e)}', 'error')
    return redirect(url_for('admin_matches'))

# ---- 比赛数据录入 ----
@app.route('/admin/matches/<int:match_id>/stats', methods=['GET', 'POST'])
@login_required
def admin_match_stats(match_id):
    """录入比赛数据（分图）"""
    conn = get_db()
    
    match = conn.execute("""
        SELECT m.*, t1.name AS team1_name, t2.name AS team2_name,
               e.name AS event_name
        FROM matches m
        LEFT JOIN teams t1 ON m.team1_id=t1.id
        LEFT JOIN teams t2 ON m.team2_id=t2.id
        LEFT JOIN events e ON m.event_id=e.id
        WHERE m.id=?
    """, (match_id,)).fetchone()
    
    if not match:
        conn.close()
        return "比赛不存在", 404

    team1_players = conn.execute(
        "SELECT * FROM players WHERE team_id=?", (match['team1_id'],)
    ).fetchall()
    team2_players = conn.execute(
        "SELECT * FROM players WHERE team_id=?", (match['team2_id'],)
    ).fetchall()

    existing_stats = conn.execute(
        "SELECT * FROM match_stats WHERE match_id=?", (match_id,)
    ).fetchall()

    map_names = [match['map1'], match['map2'], match['map3']]
    maps = []
    for i, mn in enumerate(map_names):
        map_stats = {}
        for s in existing_stats:
            if s['map_name'] == mn:
                map_stats[s['player_id']] = s
        maps.append({
            'name': mn,
            'disabled': not mn,
            'has_data': len(map_stats) > 0,
            'stats': map_stats,
            'index': i
        })

    active_tab = 0
    for i, m in enumerate(maps):
        if not m['disabled']:
            active_tab = i
            break

    if request.method == 'POST':
        map_name = request.form.get('map_name', '')
        conn.execute(
            "DELETE FROM match_stats WHERE match_id=? AND map_name=?",
            (match_id, map_name)
        )

        rounds = 30
        if map_name == match['map1']:
            rounds = (match['map1_t1'] or 0) + (match['map1_t2'] or 0)
        elif map_name == match['map2']:
            rounds = (match['map2_t1'] or 0) + (match['map2_t2'] or 0)
        elif map_name == match['map3']:
            rounds = (match['map3_t1'] or 0) + (match['map3_t2'] or 0)
        if rounds == 0:
            rounds = 30

        all_players = list(team1_players) + list(team2_players)
        for p in all_players:
            pid = p['id']
            kills = request.form.get(f'kills_{pid}', 0)
            deaths = request.form.get(f'deaths_{pid}', 0)
            assists = request.form.get(f'assists_{pid}', 0)
            adr = request.form.get(f'adr_{pid}', 0)
            kast = request.form.get(f'kast_{pid}', 0)
            hs = request.form.get(f'hs_{pid}', 0)
            team_id = request.form.get(f'team_id_{pid}')

            rating = calculate_rating(
                kills=int(kills),
                deaths=int(deaths),
                rounds_played=rounds,
                adr=float(adr),
                kast=float(kast)
            )

            conn.execute("""
                INSERT INTO match_stats(match_id, player_id, team_id, kills, deaths, assists,
                                       adr, rating, kast, headshot_percentage, map_name)
                VALUES(?,?,?,?,?,?,?,?,?,?,?)
            """, (match_id, pid, team_id, kills, deaths, assists, adr, rating, kast, hs, map_name))

        conn.commit()
        conn.close()
        flash(f'{map_name} 数据已保存', 'success')
        return redirect(url_for('admin_matches'))

    conn.close()
    return render_template('admin/match_stats.html', match=match,
                          team1_players=team1_players, team2_players=team2_players,
                          maps=maps, active_tab=active_tab)

# ---- 新闻管理 ----

@app.route('/admin/news')
@login_required
def admin_news():
    """新闻列表"""
    conn = get_db()
    news = conn.execute("SELECT * FROM news ORDER BY publish_time DESC").fetchall()
    conn.close()
    return render_template('admin/news.html', news=news)

@app.route('/admin/news/add', methods=['GET', 'POST'])
@login_required
def admin_news_add():
    """添加新闻"""
    if request.method == 'POST':
        title = request.form.get('title')
        content = request.form.get('content')
        summary = request.form.get('summary')
        author = request.form.get('author', 'admin')
        publish_time = request.form.get('publish_time', datetime.now().isoformat())
        
        conn = get_db()
        conn.execute(
            """INSERT INTO news(title, content, summary, author, publish_time) 
               VALUES(?,?,?,?,?)""",
            (title, content, summary, author, publish_time)
        )
        conn.commit()
        conn.close()
        
        flash('新闻添加成功', 'success')
        return redirect(url_for('admin_news'))
    
    return render_template('admin/news_form.html', news=None)

@app.route('/admin/news/edit/<int:news_id>', methods=['GET', 'POST'])
@login_required
def admin_news_edit(news_id):
    """编辑新闻"""
    conn = get_db()
    
    if request.method == 'POST':
        title = request.form.get('title')
        content = request.form.get('content')
        summary = request.form.get('summary')
        author = request.form.get('author')
        publish_time = request.form.get('publish_time')
        
        conn.execute(
            """UPDATE news SET title=?, content=?, summary=?, author=?, publish_time=? 
               WHERE id=?""",
            (title, content, summary, author, publish_time, news_id)
        )
        conn.commit()
        conn.close()
        
        flash('新闻更新成功', 'success')
        return redirect(url_for('admin_news'))
    
    news = conn.execute("SELECT * FROM news WHERE id=?", (news_id,)).fetchone()
    conn.close()
    
    return render_template('admin/news_form.html', news=news)

@app.route('/admin/news/delete/<int:news_id>')
@login_required
def admin_news_delete(news_id):
    """删除新闻"""
    try:
        conn = get_db()
        conn.execute("DELETE FROM news WHERE id=?", (news_id,))
        conn.commit()
        conn.close()
        flash('新闻删除成功', 'success')
    except Exception as e:
        flash(f'删除失败：{str(e)}', 'error')
    return redirect(url_for('admin_news'))

# ============ 启动应用 ============

if __name__ == '__main__':
    init_tables()
    
    # 自动创建默认管理员（如果不存在）
    conn = get_db()
    admin = conn.execute("SELECT id FROM admins WHERE username='admin'").fetchone()
    if not admin:
        from werkzeug.security import generate_password_hash
        conn.execute("INSERT INTO admins(username, password_hash) VALUES(?,?)",
                     ('admin', generate_password_hash('admin123')))
        conn.commit()
    conn.close()
    
    app.run(debug=True, port=5000, host='0.0.0.0')