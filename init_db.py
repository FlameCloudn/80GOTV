# 初始化数据库 + 插入模拟数据
# 用法：python init_db.py
from models import init_tables, get_db
from werkzeug.security import generate_password_hash
from datetime import datetime, timedelta
import json
import os
from config import Config

def run():
    # 如果已存在数据库，先删了重建，方便测试
    if os.path.exists(Config.DATABASE):
        os.remove(Config.DATABASE)
        print('🗑️  删除旧数据库')

    init_tables()
    print('📋 创建数据表')
    
    conn = get_db()
    c = conn.cursor()

    # ---- 队伍 ----
    teams = [
        ('星辰电竞社', 'STAR', '一支充满激情的队伍'),
        ('暴风战队', 'STORM', '以快速进攻著称'),
        ('夜枭俱乐部', 'OWL', '战术大师云集'),
        ('烈焰兵团', 'FIRE', '火力全开'),
        ('寒冰军团', 'ICE', '冷静沉着'),
        ('雷霆战队', 'THUNDER', '雷霆万钧'),
        ('幻影小队', 'PHANTOM', '神出鬼没'),
        ('钢铁之师', 'STEEL', '防守坚如磐石'),
    ]
    for name, short, desc in teams:
        c.execute("INSERT INTO teams(name, short_name, description) VALUES(?,?,?)", 
                  (name, short, desc))
    print(f'✅ 插入 {len(teams)} 支队伍')

    # ---- 选手 ----
    nicks = [
        ('苍穹', '张伟'),
        ('破晓', '李强'),
        ('寒冰', '王磊'),
        ('疾风', '刘洋'),
        ('落叶', '陈浩'),
    ]
    player_count = 0
    for tid in range(1, 9):
        for nick, real in nicks:
            c.execute("INSERT INTO players(nickname, real_name, team_id, steam_id) VALUES(?,?,?,?)",
                      (f'{nick}{tid}', real, tid, f'STEAM_0:{tid}:{player_count}'))
            player_count += 1
    print(f'✅ 插入 {player_count} 名选手')

    # ---- 赛事 ----
    today = datetime.now()
    events_data = [
        ('校园春季杯', '春季学期首个大型赛事', 
         (today-timedelta(days=30)).isoformat(), 
         (today-timedelta(days=10)).isoformat(), 
         '单败淘汰', 'completed'),
        ('校园夏季联赛', '夏季学期常规联赛', 
         (today-timedelta(days=2)).isoformat(), 
         (today+timedelta(days=15)).isoformat(), 
         '双循环积分', 'ongoing'),
        ('校园秋季邀请赛', '邀请各校顶尖战队', 
         (today+timedelta(days=30)).isoformat(), 
         (today+timedelta(days=45)).isoformat(), 
         '瑞士轮+淘汰', 'upcoming'),
    ]
    for ev in events_data:
        c.execute("""INSERT INTO events(name, description, start_date, end_date, format, status) 
                     VALUES(?,?,?,?,?,?)""", ev)
    print(f'✅ 插入 {len(events_data)} 个赛事')

    # ---- 比赛 ----
    matches_data = [
        # 春季杯已结束的比赛
        (1, 1, 2, 16, 14, (today-timedelta(days=25)).isoformat(), 'BO1', 'completed'),
        (1, 3, 4, 16, 9, (today-timedelta(days=24)).isoformat(), 'BO1', 'completed'),
        (1, 5, 6, 13, 16, (today-timedelta(days=23)).isoformat(), 'BO1', 'completed'),
        (1, 7, 8, 16, 12, (today-timedelta(days=22)).isoformat(), 'BO1', 'completed'),
        (1, 1, 3, 16, 11, (today-timedelta(days=18)).isoformat(), 'BO3', 'completed'),
        (1, 6, 7, 14, 16, (today-timedelta(days=17)).isoformat(), 'BO3', 'completed'),
        (1, 1, 7, 19, 22, (today-timedelta(days=12)).isoformat(), 'BO5', 'completed'),
        
        # 夏季联赛进行中
        (2, 1, 2, 16, 12, (today-timedelta(hours=5)).isoformat(), 'BO3', 'completed'),
        (2, 3, 4, 14, 16, (today-timedelta(hours=3)).isoformat(), 'BO3', 'completed'),
        (2, 5, 6, 8, 5, today.isoformat(), 'BO3', 'live'),
        (2, 7, 8, 0, 0, (today+timedelta(hours=3)).isoformat(), 'BO3', 'upcoming'),
        (2, 1, 3, 0, 0, (today+timedelta(days=1)).isoformat(), 'BO3', 'upcoming'),
        (2, 2, 4, 0, 0, (today+timedelta(days=1, hours=3)).isoformat(), 'BO3', 'upcoming'),
        (2, 5, 7, 0, 0, (today+timedelta(days=2)).isoformat(), 'BO3', 'upcoming'),
        (2, 6, 8, 0, 0, (today+timedelta(days=2, hours=3)).isoformat(), 'BO3', 'upcoming'),
        
        # 秋季赛未开始
        (3, 1, 5, 0, 0, (today+timedelta(days=30)).isoformat(), 'BO1', 'upcoming'),
        (3, 2, 6, 0, 0, (today+timedelta(days=30, hours=2)).isoformat(), 'BO1', 'upcoming'),
    ]
    for m in matches_data:
        c.execute("""INSERT INTO matches(event_id, team1_id, team2_id, team1_score, 
                     team2_score, match_time, bo_format, status, map_pool)
                     VALUES(?,?,?,?,?,?,?,?,?)""", 
                  (*m, json.dumps(['de_mirage', 'de_dust2', 'de_inferno'])))
    print(f'✅ 插入 {len(matches_data)} 场比赛')

    # ---- 比赛数据（只为已完成的比赛生成） ----
    completed_matches = c.execute(
        "SELECT id, team1_id, team2_id FROM matches WHERE status='completed'"
    ).fetchall()
    
    stats_count = 0
    for match in completed_matches:
        match_id, t1_id, t2_id = match['id'], match['team1_id'], match['team2_id']
        
        # 为两队各5名选手生成数据
        for team_id in [t1_id, t2_id]:
            players = c.execute(
                "SELECT id FROM players WHERE team_id=? LIMIT 5", (team_id,)
            ).fetchall()
            
            for p in players:
                import random
                kills = random.randint(10, 30)
                deaths = random.randint(10, 25)
                assists = random.randint(2, 8)
                adr = round(random.uniform(60, 100), 1)
                rating = round(random.uniform(0.8, 1.5), 2)
                kast = round(random.uniform(60, 85), 1)
                hs = round(random.uniform(35, 65), 1)
                
                c.execute("""INSERT INTO match_stats(match_id, player_id, team_id, kills, 
                             deaths, assists, adr, rating, kast, headshot_percentage, map_name)
                             VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
                          (match_id, p['id'], team_id, kills, deaths, assists, 
                           adr, rating, kast, hs, 'de_mirage'))
                stats_count += 1
    print(f'✅ 插入 {stats_count} 条比赛数据')

    # ---- 新闻 ----
    news_data = [
        ('夏季联赛今日开打！星辰对阵暴风', 
         '经过漫长的等待，校园夏季联赛终于在今天拉开帷幕。首场比赛由卫冕冠军星辰电竞社对阵老牌劲旅暴风战队。双方在 de_mirage 上展开激烈对抗，最终星辰以 16:12 险胜。选手"苍穹1"发挥出色，拿下 28 杀，Rating 高达 1.45。赛后采访中，他表示："这只是开始，我们的目标是卫冕。"暴风战队虽然失利，但"破晓2"的表现同样可圈可点，多次关键残局力挽狂澜。',
         '揭幕战精彩纷呈', 'admin', (today-timedelta(hours=5)).isoformat(), 42),
        
        ('春季杯回顾：夜枭俱乐部逆袭夺冠', 
         '在刚刚结束的春季杯决赛中，夜枭俱乐部以 3:2 的比分战胜星辰电竞社，夺得冠军。这是夜枭俱乐部建队以来的首个冠军奖杯。决赛采用 BO5 赛制，双方在五张地图上展开鏖战。夜枭在 0:2 落后的情况下连扳三局，完成惊天逆转。队长"寒冰7"在接受采访时激动地说："我们从未放弃，这个冠军属于每一个队员。"',
         '春季杯落幕', 'admin', (today-timedelta(days=11)).isoformat(), 87),
        
        ('新版本更新：经济系统调整详解', 
         'Valve 在最新更新中对 CS2 的经济系统进行了微调。主要变化包括：1) 连败奖金上限从 $3400 提升至 $3500；2) C4 爆炸后全队奖金增加 $300；3) 手枪局失败后第二局奖金从 $1900 提升至 $2000。这些改动旨在减少经济碾压局，让比赛更具观赏性。职业选手普遍认为这是积极的改动，但也有人担心会削弱强队的滚雪球能力。我们将持续关注这些变化对比赛格局的影响。',
         '版本变动一览', 'admin', (today-timedelta(days=5)).isoformat(), 23),
        
        ('选手专访：苍穹1 的成长之路', 
         '作为星辰电竞社的王牌选手，"苍穹1"在过去一年中进步神速。从默默无闻的替补到如今的队内核心，他的故事激励着无数年轻选手。在专访中，他分享了自己的训练心得："每天至少 4 小时的 DM 练习，加上 2 小时的战术复盘。天赋很重要，但努力更重要。"他还透露，队伍正在准备秋季邀请赛，目标是打进全国赛。',
         '走近选手', 'admin', (today-timedelta(days=3)).isoformat(), 56),
        
        ('秋季邀请赛报名开启，奖金池创新高', 
         '校园秋季邀请赛将于下月举行，目前报名通道已正式开启。本届赛事奖金池高达 50,000 元，冠军将获得 25,000 元奖金以及全国赛直通名额。赛事采用瑞士轮+单败淘汰赛制，预计将有 16 支队伍参赛。组委会表示，今年将邀请职业解说团队，并进行全程直播。报名截止日期为本月 20 日，名额有限，先到先得。',
         '报名通道开启', 'admin', (today-timedelta(days=1)).isoformat(), 34),
        
        ('数据分析：本赛季 Rating 最高的五名选手', 
         '根据最新统计，本赛季 Rating 排名前五的选手分别是：1) 苍穹1 (1.42)，2) 寒冰7 (1.38)，3) 疾风3 (1.35)，4) 破晓2 (1.31)，5) 落叶5 (1.29)。值得注意的是，前五名中有三名来自春季杯四强队伍。数据专家指出，高 Rating 选手往往具备出色的定位意识和枪法，同时在关键局的发挥也更加稳定。',
         '数据看选手', 'admin', (today-timedelta(hours=12)).isoformat(), 19),
        
        ('战术解析：如何在 de_mirage 上打好 A 点进攻', 
         'de_mirage 是 CS2 中最经典的地图之一，A 点进攻是 T 方的常用战术。本文将详细解析几种主流打法：1) 快速爆弹 A 点：利用烟雾弹封锁 CT、忍者位和跳台，闪光弹配合队友冲入包点；2) 默认控图转 A：先控制中路和 A2 楼，观察防守站位后再决定进攻时机；3) A1 假打转 B：佯攻 A 点吸引防守，实则转向 B 点。每种打法都需要队员间的默契配合和精准的道具投掷。',
         '战术教学', 'admin', (today-timedelta(days=7)).isoformat(), 45),
        
        ('赛事公告：夏季联赛赛程调整通知', 
         '由于场地原因，原定于本周六举行的两场比赛将延期至下周三。受影响的比赛为：星辰 vs 夜枭、暴风 vs 烈焰。组委会对此造成的不便深表歉意，并承诺将为观众提供补偿。已购票观众可选择退票或保留至新日期使用。最新赛程已更新至官网，请各位选手和观众及时查看。',
         '赛程变动', 'admin', (today-timedelta(hours=8)).isoformat(), 12),
    ]
    for n in news_data:
        c.execute("""INSERT INTO news(title, content, summary, author, publish_time, comment_count)
                     VALUES(?,?,?,?,?,?)""", n)
    print(f'✅ 插入 {len(news_data)} 条新闻')

    # ---- 管理员账号 ----
    c.execute("INSERT INTO admins(username, password_hash) VALUES(?,?)",
              ('admin', generate_password_hash('admin123')))
    print('✅ 创建管理员账号 (admin / admin123)')

    conn.commit()
    conn.close()
    print('\n🎉 数据库初始化完成！')

if __name__ == '__main__':
    run()