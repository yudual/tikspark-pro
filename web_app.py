import os
import json
import subprocess
import traceback
import threading
import time
import random
import base64
import requests
import re
from datetime import datetime, timedelta, timezone
import smtplib
import ssl
from email.mime.text import MIMEText
from flask import Flask, request, jsonify, render_template, send_file
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import text, inspect
from flask_migrate import Migrate
from flask_socketio import SocketIO, emit
from werkzeug.exceptions import HTTPException
from playwright.sync_api import sync_playwright
import uuid
import string
import queue
from celery import Celery

app = Flask(__name__)
app.config['SECRET_KEY'] = os.getenv('SECRET_KEY', 'spark_flow_secret_key')
app.config['SQLALCHEMY_DATABASE_URI'] = os.getenv('DB_URI', 'sqlite:///data.db')
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
ADMIN_USERNAME = os.getenv('ADMIN_USERNAME', 'admin123')
ADMIN_PASSWORD = os.getenv('ADMIN_PASSWORD', 'adminadmin')
ADMIN_TOKEN = os.getenv('ADMIN_TOKEN', 'ADMIN_TOKEN')

# 【性能优化】：添加数据库连接池配置，防止查询卡顿和 MySQL 掉线
app.config['SQLALCHEMY_ENGINE_OPTIONS'] = {
    'pool_size': 20,          # 连接池最大连接数
    'pool_recycle': 3600,     # 1小时回收一次连接
    'pool_pre_ping': True     # 每次分配连接前先 ping 一下保证存活
}

# 配置 Celery 与 Redis 分布式引擎
app.config['CELERY_BROKER_URL'] = os.getenv('REDIS_URL', 'redis://localhost:6379/0')
app.config['CELERY_RESULT_BACKEND'] = os.getenv('REDIS_URL', 'redis://localhost:6379/0')

celery_app = Celery(app.name, broker=app.config['CELERY_BROKER_URL'])
celery_app.conf.update(app.config)

app.jinja_env.variable_start_string = '{['
app.jinja_env.variable_end_string = ']}'

# 开启 SocketIO 的 Redis 消息队列支持，实现 Celery 跨进程推流
socketio = SocketIO(app, cors_allowed_origins="*", async_mode='threading', message_queue=app.config['CELERY_BROKER_URL'])

sms_code_waiter = {}

@app.errorhandler(Exception)
def handle_exception(e):
    if isinstance(e, HTTPException): return e
    traceback.print_exc()
    return jsonify({"code": 500, "msg": f"系统内部错误: {str(e)}"}), 500

db = SQLAlchemy(app)
migrate = Migrate(app, db)

def get_now():
    tz_cn = timezone(timedelta(hours=8))
    return datetime.now(tz_cn).replace(tzinfo=None)

ALLOWED_EMAIL_DOMAINS = ['qq.com', '163.com', '126.com', '139.com', 'sohu.com', 'aliyun.com', '189.com', 'hotmail.com', 'gmail.com', 'sina.com', 'yahoo.com', 'outlook.com', 'foxmail.com']
def is_valid_email(email):
    if not email or '@' not in email: return False
    return email.split('@')[-1].lower() in ALLOWED_EMAIL_DOMAINS

# ================= 数据库模型 =================
class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(50), unique=True, nullable=False)
    password = db.Column(db.String(100), nullable=False)
    email = db.Column(db.String(100), unique=True, nullable=False)
    qq_number = db.Column(db.String(20), default="")
    points = db.Column(db.Integer, default=10)
    vip_level = db.Column(db.Integer, default=1)
    vip_expire = db.Column(db.DateTime, nullable=True)
    daily_free_date = db.Column(db.String(20), nullable=True)
    daily_free_used = db.Column(db.Integer, default=0)
    token = db.Column(db.String(100), unique=True)
    invite_code = db.Column(db.String(10), unique=True)
    invited_by = db.Column(db.Integer, nullable=True)
    has_first_topup = db.Column(db.Boolean, default=False)
    is_pinned = db.Column(db.Boolean, default=False)
    notify_success = db.Column(db.Boolean, default=True)
    notify_fail = db.Column(db.Boolean, default=True)
    notify_vip = db.Column(db.Boolean, default=True)
    notify_points = db.Column(db.Boolean, default=True)
    notify_state = db.Column(db.Text, default="{}") 
    accounts = db.relationship('DouyinAccount', backref='user', lazy=True, cascade="all, delete-orphan")

class VerifyCode(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(100), nullable=False)
    code = db.Column(db.String(10), nullable=False)
    expire_at = db.Column(db.DateTime, nullable=False)

class DouyinAccount(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    douyin_id = db.Column(db.String(100))
    nickname = db.Column(db.String(100))
    cookie = db.Column(db.Text, nullable=False)
    proxy_ip = db.Column(db.String(100), default="")
    friends_cache = db.Column(db.Text, default="[]") 
    tasks = db.relationship('TaskConfig', backref='account', lazy=True, cascade="all, delete-orphan")

class TaskConfig(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    account_id = db.Column(db.Integer, db.ForeignKey('douyin_account.id'), nullable=False)
    friend_id = db.Column(db.String(100), nullable=False) 
    remark = db.Column(db.String(100), default="") 
    message = db.Column(db.Text, nullable=False) 
    time_range = db.Column(db.String(20), default="06:00-08:00") 
    target_run_time = db.Column(db.DateTime, nullable=True)
    last_run_date = db.Column(db.String(50), nullable=True) 
    run_count = db.Column(db.Integer, default=0)
    last_status = db.Column(db.String(20), default="等待调度")
    last_run_time = db.Column(db.DateTime, nullable=True)
    logs = db.relationship('ExecutionLog', backref='task', lazy=True, cascade="all, delete-orphan")

class ExecutionLog(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    task_id = db.Column(db.Integer, db.ForeignKey('task_config.id'), nullable=False)
    status = db.Column(db.String(20)) 
    content = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=get_now) 

class CDKey(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    key_str = db.Column(db.String(50), unique=True, nullable=False)
    key_type = db.Column(db.String(20), nullable=False)
    value = db.Column(db.Integer, nullable=False)
    is_used = db.Column(db.Boolean, default=False)
    used_by = db.Column(db.String(50), nullable=True)
    is_event = db.Column(db.Boolean, default=False)
    used_count = db.Column(db.Integer, default=0)

class UserEventRecord(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    key_id = db.Column(db.Integer, db.ForeignKey('cd_key.id'), nullable=False)
    created_at = db.Column(db.DateTime, default=get_now)

class SystemConfig(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    key_name = db.Column(db.String(50), unique=True)
    key_value = db.Column(db.Text)

# ================= 坚如磐石的数据库启动策略 =================
def init_db():
    with app.app_context():
        with db.engine.connect() as conn:
            pass
        db.create_all()

        try:
            inspector = inspect(db.engine)
            tables = inspector.get_table_names()
            if 'douyin_account' in tables:
                columns = [c['name'] for c in inspector.get_columns('douyin_account')]
                if 'friends_cache' not in columns:
                    with db.engine.begin() as conn:
                        conn.execute(text("ALTER TABLE douyin_account ADD COLUMN friends_cache TEXT"))
                    with db.engine.begin() as conn:
                        conn.execute(text("UPDATE douyin_account SET friends_cache = '[]' WHERE friends_cache IS NULL"))
            if 'user' in tables:
                columns = [c['name'] for c in inspector.get_columns('user')]
                user_migrations = [
                    ('vip_level', "ALTER TABLE `user` ADD COLUMN vip_level INTEGER DEFAULT 1"),
                    ('daily_free_date', "ALTER TABLE `user` ADD COLUMN daily_free_date VARCHAR(20)"),
                    ('daily_free_used', "ALTER TABLE `user` ADD COLUMN daily_free_used INTEGER DEFAULT 0"),
                ]
                for column_name, ddl in user_migrations:
                    if column_name not in columns:
                        with db.engine.begin() as conn:
                            conn.execute(text(ddl))
                with db.engine.begin() as conn:
                    conn.execute(text("UPDATE `user` SET vip_level = 1 WHERE vip_level IS NULL"))
                    conn.execute(text("UPDATE `user` SET daily_free_used = 0 WHERE daily_free_used IS NULL"))
        except Exception as e:
            print(f"【数据库平滑升级错误】: {e}", flush=True)
            
        defaults = {
            'proxy_api_url': 'https://api.hailiangip.com:8522/api/getIp?type=1&num=1&pid=4&unbindTime=60&cid=9&orderId=O26040423594970296011&time=1776623355&sign=5bac8a6402215b70ff62b84a97c503e3&noDuplicate=1&dataType=0&lineSeparator=0',
            'site_name': '续火花平台', 'site_title': '抖音续火花托管平台',
            'reg_reward_type': 'points', 'reg_reward_value': '10',
            'announcement': '欢迎使用全自动续火花平台！', 'match_mode': 'short_id',
            'mail_tpl_success_title': '【续火成功通知】任务已完成', 'mail_tpl_success': '尊敬的 {username}，您的账号 {douyin_id} 已成功为您执行了续火花任务。\n当前剩余积分：{points}。',
            'mail_tpl_fail_title': '【续火失败通知】请及时处理', 'mail_tpl_fail': '尊敬的 {username}，您的账号 {douyin_id} 任务执行失败！\n失败原因：{reason}\n请登录平台检查日志或更新Cookie。',
            'mail_tpl_vip_title': '【会员到期通知】资产状态变更', 'mail_tpl_vip': '尊敬的 {username}：\n您的会员状态：{reason}。\n到期时间：{vip_expire}。',
            'mail_tpl_points_title': '【积分告警】账户额度不足', 'mail_tpl_points': '尊敬的 {username}：\n您的账户积分存在风险：{reason}。\n当前剩余：{points} 积分。',
            'pw_wait_creator': '10000',
            'pw_wait_login_click': '5000',
            'pw_wait_login_success': '2500',
            'pw_wait_clear_cache': '2000',
            'pw_wait_chat_load': '10000',
            'pw_scroll_times': '35',
            'pw_wait_scroll_interval': '1000',
            'enable_spark_days': '1'  # 默认开启火花天数提取
        }
        for k, v in defaults.items():
            if not SystemConfig.query.filter_by(key_name=k).first(): db.session.add(SystemConfig(key_name=k, key_value=v))
        db.session.commit()

db_ready = False
for i in range(20):
    try:
        init_db()
        db_ready = True
        break
    except Exception as e:
        time.sleep(3)

def generate_invite_code():
    while True:
        code = ''.join(random.choices(string.ascii_uppercase + string.digits, k=6))
        if not User.query.filter_by(invite_code=code).first(): return code

def compute_target_run_time(time_range_str):
    try:
        start_str, end_str = time_range_str.split('-')
        now = get_now()
        start_t = datetime.strptime(f"{now.strftime('%Y-%m-%d')} {start_str}", "%Y-%m-%d %H:%M")
        end_t = datetime.strptime(f"{now.strftime('%Y-%m-%d')} {end_str}", "%Y-%m-%d %H:%M")
        if start_t == end_t: return start_t
        if end_t < start_t: end_t += timedelta(days=1)
        return start_t + timedelta(seconds=random.randint(0, int((end_t - start_t).total_seconds())))
    except: return get_now().replace(hour=9, minute=0, second=0)

def get_effective_vip_level(user):
    level = int(getattr(user, 'vip_level', 1) or 1)
    if level < 1: level = 1
    if level > 3: level = 3
    if level > 1 and (not user.vip_expire or user.vip_expire <= get_now()):
        return 1
    return level

def get_daily_free_quota(user):
    level = get_effective_vip_level(user)
    if level >= 3: return None
    if level == 2: return 5
    return 1

def reset_daily_free_counter(user):
    today_str = get_now().strftime('%Y-%m-%d')
    if user.daily_free_date != today_str:
        user.daily_free_date = today_str
        user.daily_free_used = 0

def get_billing_snapshot(user):
    reset_daily_free_counter(user)
    level = get_effective_vip_level(user)
    quota = get_daily_free_quota(user)
    used = int(user.daily_free_used or 0)
    remaining = None if quota is None else max(quota - used, 0)
    return {
        "vip_level": level,
        "vip_name": {1: "免费会员", 2: "二级会员", 3: "三级会员"}.get(level, "免费会员"),
        "daily_free_quota": quota,
        "daily_free_used": used,
        "daily_free_remaining": remaining
    }

def calculate_task_cost(user, task_count):
    snapshot = get_billing_snapshot(user)
    if snapshot["daily_free_quota"] is None:
        return 0, task_count, snapshot
    free_count = min(task_count, snapshot["daily_free_remaining"])
    return task_count - free_count, free_count, snapshot

def reserve_task_quota(user, task_count):
    cost, free_count, snapshot = calculate_task_cost(user, task_count)
    if cost > 0 and user.points < cost:
        return False, f"积分不足，需要 {cost} 积分。今日免费额度剩余 {snapshot['daily_free_remaining']} 条。", cost, free_count
    if snapshot["daily_free_quota"] is not None:
        user.daily_free_used = int(user.daily_free_used or 0) + free_count
    if cost > 0:
        user.points -= cost
    if snapshot["daily_free_quota"] is None:
        return True, "三级会员不限量执行，本次不扣积分。", cost, free_count
    return True, f"已使用免费额度 {free_count} 条，扣除积分 {cost}。", cost, free_count

def render_tpl_with_title(base_name, user, acc=None, reason=""):
    with app.app_context():
        title_cfg = SystemConfig.query.filter_by(key_name=base_name+'_title').first()
        content_cfg = SystemConfig.query.filter_by(key_name=base_name).first()
        title = title_cfg.key_value if title_cfg else ""
        content = content_cfg.key_value if content_cfg else ""
        format_dict = {
            "username": user.username,
            "email": user.email,
            "points": user.points,
            "vip_expire": user.vip_expire.strftime('%Y-%m-%d') if user.vip_expire else "未开通",
            "douyin_id": acc.nickname or acc.douyin_id if acc else "全局",
            "reason": reason
        }
        for key, val in format_dict.items():
            token_str = "{" + key + "}"
            title = title.replace(token_str, str(val))
            content = content.replace(token_str, str(val))
        return title, content

def send_email(to_email, subject, content):
    with app.app_context():
        host = SystemConfig.query.filter_by(key_name='smtp_host').first()
        port = SystemConfig.query.filter_by(key_name='smtp_port').first()
        user = SystemConfig.query.filter_by(key_name='smtp_user').first()
        pwd = SystemConfig.query.filter_by(key_name='smtp_pass').first()
        if not (host and port and user and pwd) or not host.key_value: return False, "未配置"
        try:
            h, p, u, pw = host.key_value.strip(), int(str(port.key_value).strip()), user.key_value.strip(), pwd.key_value.strip()
            msg = MIMEText(content.replace('\n', '<br>') if "<" not in content else content, 'html', 'utf-8')
            msg['Subject'] = subject; msg['From'] = u; msg['To'] = to_email
            context = ssl._create_unverified_context()
            for retry in range(2):
                try:
                    server = smtplib.SMTP_SSL(h, p, timeout=12, context=context) if p in [465, 466] else smtplib.SMTP(h, p, timeout=12)
                    if p not in [465, 466]: server.ehlo(); server.starttls(context=context)
                    server.login(u, pw); server.sendmail(u, [to_email], msg.as_string()); server.quit()
                    return True, "发送成功"
                except smtplib.SMTPServerDisconnected as e:
                    if retry == 0: time.sleep(1); continue
                    return False, f"断开连接: {str(e)}"
        except Exception as e: return False, str(e)

def get_dynamic_proxy(pid, cid):
    if str(pid) == '-1': return None
    with app.app_context():
        cfg = SystemConfig.query.filter_by(key_name='proxy_api_url').first()
        api_url = cfg.key_value.strip() if cfg and cfg.key_value else ""
    
    if not api_url: return None
    
    if 'pid=' in api_url: req_url = re.sub(r'([?&])pid=[^&]*', rf'\g<1>pid={pid}', api_url)
    else: req_url = api_url + f"&pid={pid}"
        
    if 'cid=' in req_url: req_url = re.sub(r'([?&])cid=[^&]*', rf'\g<1>cid={cid}', req_url)
    else: req_url += f"&cid={cid}"

    try:
        res = requests.get(req_url, timeout=10)
        text = res.text.strip()
        if text.startswith('{'):
            data = json.loads(text)
            if data.get('code') == 0 and data.get('data'): return f"http://{data['data'][0]['ip']}:{data['data'][0]['port']}"
        elif ":" in text and "{" not in text and "<" not in text:
            if "请添加" not in text and "错误" not in text: return f"http://{text}"
    except: pass
    return None

def qr_login_worker(user_id, proxy_url, sid, nickname, douyin_id):
    try:
        # 获取数据库中的动态配置时间及开关
        with app.app_context():
            def get_cfg_int(key, default):
                cfg = SystemConfig.query.filter_by(key_name=key).first()
                try: return int(cfg.key_value) if cfg and cfg.key_value else default
                except: return default
                
            pw_wait_creator = get_cfg_int('pw_wait_creator', 10000)
            pw_wait_login_click = get_cfg_int('pw_wait_login_click', 5000)
            pw_wait_login_success = get_cfg_int('pw_wait_login_success', 2500)
            pw_wait_clear_cache = get_cfg_int('pw_wait_clear_cache', 2000)
            pw_wait_chat_load = get_cfg_int('pw_wait_chat_load', 10000)
            pw_scroll_times = get_cfg_int('pw_scroll_times', 35)
            pw_wait_scroll_interval = get_cfg_int('pw_wait_scroll_interval', 1000)
            enable_spark_days = get_cfg_int('enable_spark_days', 1) == 1

        sms_code_waiter[sid] = queue.Queue()
        socketio.emit('qr_status', {'msg': '🚀 正在为您启动云端独立环境...', 'status': 'loading'}, to=sid)
        
        with sync_playwright() as p:
            proxy_settings = {"server": proxy_url} if proxy_url else None
            browser = p.chromium.launch(headless=True, proxy=proxy_settings, args=['--disable-blink-features=AutomationControlled', '--force-webrtc-ip-handling-policy=disable_non_proxied_udp'])
            context = browser.new_context(viewport={'width': 1280, 'height': 800}, user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36", locale="zh-CN", timezone_id="Asia/Shanghai")
            page = context.new_page()
            
            def find_and_click(text, exact=False):
                try:
                    loc = page.get_by_text(text, exact=exact) if exact else page.locator(f"text='{text}'")
                    if loc.count() > 0 and loc.first.is_visible():
                        loc.first.click(timeout=1500)
                        return True
                except: pass
                for frame in page.frames:
                    try:
                        loc = frame.get_by_text(text, exact=exact) if exact else frame.locator(f"text='{text}'")
                        if loc.count() > 0 and loc.first.is_visible():
                            loc.first.click(timeout=1500)
                            return True
                    except: pass
                return False

            def find_and_fill_input(text_to_fill):
                selectors = ["input[placeholder*='验证码']", "input[placeholder*='code']", "input[maxlength='6']", "input[type='tel']", "input[type='number']", "input[type='text']", "input"]
                def try_fill(inputs):
                    for idx in range(inputs.count()):
                        try:
                            el = inputs.nth(idx)
                            box = el.bounding_box()
                            if el.is_visible() and not el.is_disabled() and box and box['width'] > 10:
                                el.click(timeout=1000)
                                el.fill("") 
                                page.keyboard.type(text_to_fill, delay=150)
                                return True
                        except: pass
                    return False
                for sel in selectors:
                    if try_fill(page.locator(sel)): return True
                for frame in page.frames:
                    for sel in selectors:
                        if try_fill(frame.locator(sel)): return True
                return False

            def is_input_visible():
                selectors = ["input[placeholder*='验证码']", "input[maxlength='6']", "input[type='tel']", "input[type='number']", "input[type='text']", "input"]
                for sel in selectors:
                    inputs = page.locator(sel)
                    for idx in range(inputs.count()):
                        try:
                            box = inputs.nth(idx).bounding_box()
                            if inputs.nth(idx).is_visible() and box and box['width'] > 10: return True
                        except: pass
                for frame in page.frames:
                    for sel in selectors:
                        inputs = frame.locator(sel)
                        for idx in range(inputs.count()):
                            try:
                                box = inputs.nth(idx).bounding_box()
                                if inputs.nth(idx).is_visible() and box and box['width'] > 10: return True
                            except: pass
                return False

            socketio.emit('qr_status', {'msg': '🌐 正在请求抖音安全连接...', 'status': 'loading'}, to=sid)
            page.goto("https://creator.douyin.com/", timeout=60000, wait_until="domcontentloaded")
            
            try: page.wait_for_selector("canvas", timeout=12000)
            except: page.wait_for_timeout(pw_wait_creator)
            
            try:
                login_btns = [page.locator("text='登录'").first, page.locator(".login-btn").first]
                for btn in login_btns:
                    if btn.is_visible() and not page.locator("canvas").is_visible():
                        btn.click()
                        socketio.emit('qr_status', {'msg': '👆 已探测到页面，正在唤起安全登录弹窗...', 'status': 'loading'}, to=sid)
                        page.wait_for_timeout(pw_wait_login_click)
                        break
            except: pass
            
            socketio.emit('qr_status', {'msg': '✅ 请扫描下方二维码。画面每2秒刷新一次，若过期请稍候', 'status': 'waiting'}, to=sid)
            
            has_clicked_verify = False
            has_requested_sms = False
            
            max_wait_seconds = 120
            for i in range(max_wait_seconds):
                try:
                    cookies = context.cookies()
                    cookie_names = [c['name'] for c in cookies]
                    
                    if "sessionid" in cookie_names or "sessionid_ss" in cookie_names:
                        socketio.emit('qr_status', {'msg': '🎉 登录成功！正在准备提取数据...', 'status': 'loading'}, to=sid)
                        page.wait_for_timeout(pw_wait_login_success)
                        
                        final_cookies = context.cookies()
                        formatted_cookies = []
                        for c in final_cookies:
                            same_site = c.get("sameSite", "")
                            same_site_val = "no_restriction" if same_site.lower() == "none" else (same_site if same_site else "unspecified")
                            formatted_cookies.append({
                                "domain": c.get("domain", ""), "expirationDate": c.get("expires", 0),
                                "hostOnly": not c.get("domain", "").startswith("."), "httpOnly": c.get("httpOnly", False),
                                "name": c.get("name", ""), "path": c.get("path", "/"),
                                "sameSite": same_site_val, "secure": c.get("secure", False),
                                "session": c.get("expires", -1) == -1, "storeId": None, "value": c.get("value", "")
                            })
                        
                        with app.app_context():
                            new_acc = DouyinAccount(user_id=user_id, douyin_id=douyin_id if douyin_id else "未提供", nickname=nickname or "云端扫码账号", cookie=json.dumps(formatted_cookies, ensure_ascii=False), proxy_ip=proxy_url or "")
                            db.session.add(new_acc)
                            db.session.commit()
                            new_acc_id = new_acc.id
                            
                        # =================【纯净且无敌的 API 距离计算引擎】=================
                        base_info_dict = {}
                        spark_days_dict = {}

                        def extract_deep(obj):
                            if isinstance(obj, dict):
                                if "nickname" in obj and "uid" in obj:
                                    uid = str(obj.get("uid", "")).strip()
                                    if uid:
                                        nick = str(obj.get("nickname", "")).strip()
                                        remark = str(obj.get("remark_name", "")).strip()
                                        unique_id = str(obj.get("unique_id", "")).strip()
                                        short_id = str(obj.get("short_id", "")).strip()
                                        display_id = unique_id if unique_id else short_id
                                        
                                        if display_id:
                                            base_info_dict[uid] = {
                                                "display_id": display_id,
                                                "nickname": nick,
                                                "remark": remark
                                            }

                                for k, v in obj.items():
                                    if isinstance(v, str) and v.startswith('{') and v.endswith('}'):
                                        try: extract_deep(json.loads(v))
                                        except: pass
                                    elif isinstance(v, (dict, list)):
                                        extract_deep(v)
                            elif isinstance(obj, list):
                                for item in obj: extract_deep(item)

                        def on_response(response):
                            try:
                                if response.request.resource_type in ["fetch", "xhr"]:
                                    url = response.url
                                    
                                    if "im/user/info" in url:
                                        if not response.ok: return
                                        try:
                                            data = response.json()
                                            extract_deep(data)
                                            print(f"[*] 【雷达】资料包解析成功 | 资料表累积: {len(base_info_dict)}人", flush=True)
                                        except Exception: pass
                                        
                                    elif "douyin.com" in url and enable_spark_days:
                                        if not response.ok: return
                                        try:
                                            raw_text = response.body().decode('utf-8', errors='ignore')
                                            
                                            if "s:create_conv_visible" in raw_text or "real_days" in raw_text:
                                                uids = []
                                                for m in re.finditer(r's:create_conv_visible[^\d]{1,10}(\d+)', raw_text):
                                                    uids.append((m.start(), m.group(1)))
                                                
                                                days_list = []
                                                for m in re.finditer(r'(?:\W|^)(?:\"real_days\"|\breal_days\b)\W{1,5}(\d+)', raw_text):
                                                    val = int(m.group(1))
                                                    if 0 < val < 10000:
                                                        days_list.append((m.start(), val))
                                                
                                                found_sparks = 0
                                                for d_pos, d_val in days_list:
                                                    closest_uid = None
                                                    min_dist = 4000  
                                                    for u_pos, c_uid in uids:
                                                        dist = abs(u_pos - d_pos)
                                                        if dist < min_dist:
                                                            min_dist = dist
                                                            closest_uid = c_uid
                                                    
                                                    if closest_uid:
                                                        spark_days_dict[closest_uid] = max(spark_days_dict.get(closest_uid, 0), d_val)
                                                        found_sparks += 1
                                                        
                                                if found_sparks > 0:
                                                    api_name = url.split("?")[0].split("/")[-1]
                                                    print(f"[*] 【雷达】从 {api_name} 包解密成功，新增提取 {found_sparks} 个真实天数 | 天数表累积: {len(spark_days_dict)}人", flush=True)
                                        except Exception: pass
                            except Exception: pass

                        page.on("response", on_response)
                        
                        try:
                            print("【雷达侦测】准备清理本地 IndexedDB 与 LocalStorage 强缓存...", flush=True)
                            try:
                                page.goto("https://www.douyin.com/", timeout=60000, wait_until="domcontentloaded")
                                page.evaluate("""() => {
                                    window.indexedDB.databases().then(dbs => {
                                        dbs.forEach(db => { window.indexedDB.deleteDatabase(db.name); });
                                    });
                                    localStorage.clear();
                                    sessionStorage.clear();
                                }""")
                                page.wait_for_timeout(pw_wait_clear_cache)
                            except: pass

                            print("【雷达侦测】正在空降至网页版私信面板...", flush=True)
                            page.goto("https://www.douyin.com/chat", timeout=60000, wait_until="domcontentloaded")
                            socketio.emit('qr_status', {'msg': '已直达私信面板，正在初始化云端底层数据...', 'status': 'loading'}, to=sid)
                            
                            page.wait_for_timeout(pw_wait_chat_load)
                            
                            try: page.mouse.click(10, 10)
                            except: pass
                            
                            socketio.emit('qr_status', {'msg': '正在平滑滚动列表触发好友网络包...', 'status': 'loading'}, to=sid)
                            
                            for _ in range(pw_scroll_times):
                                try:
                                    page.evaluate("""() => {
                                        let scrollable = document.querySelector('.web-scroll-bar-none') || 
                                                         document.querySelector('[data-e2e="conversation-list"]') ||
                                                         document.querySelector('div[style*="overflow-y: scroll"]');
                                        if(scrollable) { 
                                            scrollable.scrollBy(0, 400); 
                                        } else {
                                            document.querySelectorAll('div').forEach(el => { 
                                                if(el.scrollHeight > el.clientHeight + 100) el.scrollBy(0, 400); 
                                            });
                                        }
                                    }""")
                                except: pass
                                page.wait_for_timeout(pw_wait_scroll_interval)
                                
                        except Exception as e: 
                            err_msg = str(e)
                            print(f"【雷达侦测】提取页面加载发生报错: {err_msg}", flush=True)
                            if "ERR_TUNNEL_CONNECTION_FAILED" in err_msg:
                                socketio.emit('qr_success', {'msg': '账号绑定成功！(代理IP失效导致断网，请稍后使用自动添加功能重试)'}, to=sid)
                                browser.close()
                                return
                        
                        # ================== C: 数据融合与输出 ==================
                        final_friends = []
                        print("【雷达侦测】正在整理提取数据...", flush=True)
                        
                        for u_id, info in base_info_dict.items():
                            if u_id == str(douyin_id): continue 
                            
                            if enable_spark_days:
                                days = spark_days_dict.get(u_id, 0)
                                spark_status = f"{days} 天" if days > 0 else "无"
                            else:
                                spark_status = "未提取"
                                
                            final_friends.append({
                                "douyin_id": info["display_id"],
                                "nickname": info["nickname"],
                                "remark": info["remark"],
                                "spark_days": spark_status
                            })
                        
                        if final_friends:
                            with app.app_context():
                                acc_to_update = db.session.get(DouyinAccount, new_acc_id)
                                if acc_to_update:
                                    acc_to_update.friends_cache = json.dumps(final_friends, ensure_ascii=False)
                                    db.session.commit()

                            socketio.emit('friends_extracted', {
                                'msg': f'好友数据提取成功！共发现 {len(final_friends)} 名联系人。',
                                'friends': final_friends,
                                'account_id': new_acc_id
                            }, to=sid)
                        else:
                            page.screenshot(path="/app/extract_failed.png", full_page=True)
                            print("【雷达侦测】好友提取失败，现场截图已保存", flush=True)
                            socketio.emit('qr_success', {'msg': '账号绑定成功！(系统未抓取到好友资料包，已保存现场截图)'}, to=sid)
                            
                        browser.close()
                        return
                    
                    if not has_clicked_verify:
                        if find_and_click("接收短信验证码"):
                            socketio.emit('qr_status', {'msg': '🛡️ 触发设备保护，系统正在自动点击“接收短信验证码”...', 'status': 'loading'}, to=sid)
                            page.wait_for_timeout(1500)
                            find_and_click("验证", exact=True)
                            has_clicked_verify = True
                            page.wait_for_timeout(2500)
                    
                    if has_clicked_verify and not has_requested_sms:
                        if is_input_visible():
                            socketio.emit('qr_status', {'msg': '📩 验证码已发送至您的手机，请在下方输入：', 'status': 'need_sms'}, to=sid)
                            has_requested_sms = True
                            
                    try:
                        sms_code = sms_code_waiter[sid].get_nowait()
                        if sms_code:
                            socketio.emit('qr_status', {'msg': '⚙️ 正在向远端节点物理敲击提交短信验证码...', 'status': 'loading'}, to=sid)
                            is_filled = find_and_fill_input(sms_code)
                            if is_filled:
                                page.wait_for_timeout(1000)
                                for btn_name in ["验证", "登录", "确认", "下一步", "确定", "完成"]:
                                    if find_and_click(btn_name, exact=True): break
                                page.wait_for_timeout(3000)
                                socketio.emit('qr_status', {'msg': '🔄 验证码已提交，正在核实身份...', 'status': 'loading'}, to=sid)
                            else:
                                socketio.emit('qr_status', {'msg': '⚠️ 未能在页面中找到有效验证码输入框！已退回直播画面，请重试。', 'status': 'waiting'}, to=sid)
                                has_requested_sms = False 
                    except queue.Empty: pass
                        
                    if i % 2 == 0:
                        img_bytes = page.screenshot(clip={'x': 640, 'y': 0, 'width': 640, 'height': 800}, type="jpeg", quality=70)
                        b64_img = base64.b64encode(img_bytes).decode('utf-8')
                        socketio.emit('qr_image', {'img': f"data:image/jpeg;base64,{b64_img}"}, to=sid)

                except Exception as e: pass
                page.wait_for_timeout(1000)
            
            socketio.emit('qr_status', {'msg': '⏰ 二维码或验证已过期超时，请关闭重试。', 'status': 'error'}, to=sid)
            browser.close()
            
    except Exception as e:
        socketio.emit('qr_status', {'msg': f'❌ 云端环境启动异常: {str(e)}', 'status': 'error'}, to=sid)
    finally:
        if sid in sms_code_waiter: del sms_code_waiter[sid]

def auto_extract_worker(acc_id, cookie_str, proxy_url, self_douyin_id, sid):
    try:
        # 获取数据库中的动态配置时间及开关
        with app.app_context():
            def get_cfg_int(key, default):
                cfg = SystemConfig.query.filter_by(key_name=key).first()
                try: return int(cfg.key_value) if cfg and cfg.key_value else default
                except: return default
                
            pw_wait_creator = get_cfg_int('pw_wait_creator', 10000)
            pw_wait_login_click = get_cfg_int('pw_wait_login_click', 5000)
            pw_wait_login_success = get_cfg_int('pw_wait_login_success', 2500)
            pw_wait_clear_cache = get_cfg_int('pw_wait_clear_cache', 2000)
            pw_wait_chat_load = get_cfg_int('pw_wait_chat_load', 10000)
            pw_scroll_times = get_cfg_int('pw_scroll_times', 35)
            pw_wait_scroll_interval = get_cfg_int('pw_wait_scroll_interval', 1000)
            enable_spark_days = get_cfg_int('enable_spark_days', 1) == 1

        socketio.emit('qr_status', {'msg': '🚀 正在为您唤醒云端无头浏览器...', 'status': 'loading'}, to=sid)
        
        with sync_playwright() as p:
            proxy_settings = {"server": proxy_url} if proxy_url else None
            browser = p.chromium.launch(headless=True, proxy=proxy_settings, args=['--disable-blink-features=AutomationControlled'])
            context = browser.new_context(viewport={'width': 1280, 'height': 800}, user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36", locale="zh-CN", timezone_id="Asia/Shanghai")
            
            try:
                cookies = json.loads(cookie_str)
                context.add_cookies(cookies)
            except Exception as e:
                socketio.emit('qr_status', {'msg': '❌ Cookie 解析失败，该账号可能需要重新扫码绑定', 'status': 'error'}, to=sid)
                browser.close()
                return
                
            page = context.new_page()
            
            # =================【纯净且无敌的 API 距离计算引擎】=================
            base_info_dict = {}
            spark_days_dict = {}

            def extract_deep(obj):
                if isinstance(obj, dict):
                    if "nickname" in obj and "uid" in obj:
                        uid = str(obj.get("uid", "")).strip()
                        if uid:
                            nick = str(obj.get("nickname", "")).strip()
                            remark = str(obj.get("remark_name", "")).strip()
                            unique_id = str(obj.get("unique_id", "")).strip()
                            short_id = str(obj.get("short_id", "")).strip()
                            display_id = unique_id if unique_id else short_id
                            
                            if display_id:
                                base_info_dict[uid] = {
                                    "display_id": display_id,
                                    "nickname": nick,
                                    "remark": remark
                                }

                    for k, v in obj.items():
                        if isinstance(v, str) and v.startswith('{') and v.endswith('}'):
                            try: extract_deep(json.loads(v))
                            except: pass
                        elif isinstance(v, (dict, list)):
                            extract_deep(v)
                elif isinstance(obj, list):
                    for item in obj: extract_deep(item)

            def on_response(response):
                try:
                    if response.request.resource_type in ["fetch", "xhr"]:
                        url = response.url
                        
                        if "im/user/info" in url:
                            if not response.ok: return
                            try:
                                data = response.json()
                                extract_deep(data)
                                print(f"[*] 【雷达】资料包解析成功 | 资料表累积: {len(base_info_dict)}人", flush=True)
                            except Exception: pass
                            
                        # 仅在开启火花提取时进行解密计算
                        elif "douyin.com" in url and enable_spark_days:
                            if not response.ok: return
                            try:
                                raw_text = response.body().decode('utf-8', errors='ignore')
                                
                                if "s:create_conv_visible" in raw_text or "real_days" in raw_text:
                                    uids = []
                                    for m in re.finditer(r's:create_conv_visible[^\d]{1,10}(\d+)', raw_text):
                                        uids.append((m.start(), m.group(1)))
                                    
                                    days_list = []
                                    for m in re.finditer(r'(?:\W|^)(?:\"real_days\"|\breal_days\b)\W{1,5}(\d+)', raw_text):
                                        val = int(m.group(1))
                                        if 0 < val < 10000:
                                            days_list.append((m.start(), val))
                                    
                                    found_sparks = 0
                                    for d_pos, d_val in days_list:
                                        closest_uid = None
                                        min_dist = 4000  
                                        for u_pos, c_uid in uids:
                                            dist = abs(u_pos - d_pos)
                                            if dist < min_dist:
                                                min_dist = dist
                                                closest_uid = c_uid
                                        
                                        if closest_uid:
                                            spark_days_dict[closest_uid] = max(spark_days_dict.get(closest_uid, 0), d_val)
                                            found_sparks += 1
                                            
                                    if found_sparks > 0:
                                        api_name = url.split("?")[0].split("/")[-1]
                                        print(f"[*] 【雷达】从 {api_name} 包解密成功，新增提取 {found_sparks} 个真实天数 | 天数表累积: {len(spark_days_dict)}人", flush=True)
                            except Exception: pass
                except Exception: pass

            page.on("response", on_response)
            
            try:
                print("【雷达侦测】自动提取-准备清理本地 IndexedDB 与 LocalStorage 强缓存...", flush=True)
                try:
                    page.goto("https://www.douyin.com/", timeout=60000, wait_until="domcontentloaded")
                    page.evaluate("""() => {
                        window.indexedDB.databases().then(dbs => {
                            dbs.forEach(db => { window.indexedDB.deleteDatabase(db.name); });
                        });
                        localStorage.clear();
                        sessionStorage.clear();
                    }""")
                    page.wait_for_timeout(pw_wait_clear_cache)
                except: pass

                print("【雷达侦测】自动提取-正在空降至私信主站...", flush=True)
                page.goto("https://www.douyin.com/chat", timeout=60000, wait_until="domcontentloaded")
                socketio.emit('qr_status', {'msg': '已直达私信面板，正在初始化底层缓存数据...', 'status': 'loading'}, to=sid)
                
                page.wait_for_timeout(pw_wait_chat_load)
                
                try: page.mouse.click(10, 10)
                except: pass
                
                socketio.emit('qr_status', {'msg': '正在平滑滚动列表触发所有好友网络包...', 'status': 'loading'}, to=sid)
                
                for _ in range(pw_scroll_times):
                    try:
                        page.evaluate("""() => {
                            let scrollable = document.querySelector('.web-scroll-bar-none') || 
                                             document.querySelector('[data-e2e="conversation-list"]') ||
                                             document.querySelector('div[style*="overflow-y: scroll"]');
                            if(scrollable) { 
                                scrollable.scrollBy(0, 400); 
                            } else {
                                document.querySelectorAll('div').forEach(el => { 
                                    if(el.scrollHeight > el.clientHeight + 100) el.scrollBy(0, 400); 
                                });
                            }
                        }""")
                    except: pass
                    page.wait_for_timeout(pw_wait_scroll_interval)
                    
            except Exception as e: 
                err_msg = str(e)
                print(f"【雷达侦测】自动提取-页面加载报错: {err_msg}", flush=True)
                if "ERR_TUNNEL_CONNECTION_FAILED" in err_msg:
                    socketio.emit('qr_status', {'msg': '❌ 提取失败：当前使用的代理IP无法连通(ERR_TUNNEL_CONNECTION_FAILED)。请联系管理员。', 'status': 'error'}, to=sid)
                    browser.close()
                    return
            
            # ================== C: 数据融合与输出 ==================
            final_friends = []
            print("【雷达侦测】自动提取-正在整理数据...", flush=True)
            
            for u_id, info in base_info_dict.items():
                if u_id == str(self_douyin_id): continue 
                
                if enable_spark_days:
                    days = spark_days_dict.get(u_id, 0)
                    spark_status = f"{days} 天" if days > 0 else "无"
                else:
                    spark_status = "未提取"
                    
                final_friends.append({
                    "douyin_id": info["display_id"],
                    "nickname": info["nickname"],
                    "remark": info["remark"],
                    "spark_days": spark_status
                })
            
            if final_friends:
                with app.app_context():
                    acc_to_update = db.session.get(DouyinAccount, acc_id)
                    if acc_to_update:
                        acc_to_update.friends_cache = json.dumps(final_friends, ensure_ascii=False)
                        db.session.commit()

                socketio.emit('friends_extracted', {
                    'msg': f'好友提取执行成功！共提取并更新了 {len(final_friends)} 名联系人缓存。',
                    'friends': final_friends,
                    'account_id': acc_id
                }, to=sid)
            else:
                page.screenshot(path="/app/extract_failed.png", full_page=True)
                print("【雷达侦测】自动提取-好友提取失败，现场截图已保存，请访问 你的域名或IP:5009/debug/screenshot?type=extract 查看", flush=True)
                socketio.emit('qr_status', {'msg': '自动提取失败，未捕获到资料包。已保存现场截图。', 'status': 'error'}, to=sid)
                
            browser.close()
            
    except Exception as e:
        socketio.emit('qr_status', {'msg': f'❌ 云端环境启动异常: {str(e)}', 'status': 'error'}, to=sid)

# ================= 极速读取缓存引擎 =================
@socketio.on('request_auto_extract')
def handle_auto_extract(data):
    token = data.get('token')
    acc_id = data.get('account_id')
    with app.app_context():
        user = User.query.filter_by(token=token).first()
        if not user: return emit('qr_status', {'msg': '用户鉴权失败，请重新登录。', 'status': 'error'})
        
        acc = db.session.get(DouyinAccount, acc_id)
        if not acc or acc.user_id != user.id: 
            if not check_admin(): return emit('qr_status', {'msg': '找不到该账号', 'status': 'error'})

        try:
            friends_list = json.loads(acc.friends_cache) if acc.friends_cache else []
            if friends_list and len(friends_list) > 0:
                emit('friends_extracted', {
                    'msg': f'读取缓存成功！为您还原了 {len(friends_list)} 名联系人。',
                    'friends': friends_list,
                    'account_id': acc_id
                })
            else:
                emit('qr_status', {'msg': '缓存为空，请删除账号并重新“扫码绑定”以获取最新好友列表。', 'status': 'error'})
        except Exception as e:
            emit('qr_status', {'msg': f'读取云端缓存失败: {str(e)}', 'status': 'error'})

@socketio.on('request_qr_login')
def handle_qr_login(data):
    token = data.get('token')
    pid = data.get('pid', '-1')
    cid = data.get('cid', '-1')
    nickname = data.get('nickname', '')
    douyin_id = data.get('douyin_id', '')
    
    with app.app_context():
        user = User.query.filter_by(token=token).first()
        if not user: return emit('qr_status', {'msg': '用户鉴权失败，请重新登录。', 'status': 'error'})
            
    emit('qr_status', {'msg': '🔍 正在为您调配家庭宽带独立IP...', 'status': 'loading'})
    
    if str(pid) != '-1':
        proxy_url = get_dynamic_proxy(pid, cid)
        if proxy_url:
            clean_ip = proxy_url.split("//")[-1]
            emit('qr_status', {'msg': f'✅ 代理分配成功 ({clean_ip})，准备安全接入...', 'status': 'loading'})
            time.sleep(1.5) 
        else:
            emit('qr_status', {'msg': f'❌ 代理分配失败！为防止异地登录导致封号，系统已强制熔断拦截。请联系管理员检查配置。', 'status': 'error'})
            return 
    else:
        proxy_url = None
        emit('qr_status', {'msg': f'⚠️ 您选择了直连模式，将使用服务器原生节点通信...', 'status': 'loading'})
        time.sleep(1.5)
        
    threading.Thread(target=qr_login_worker, args=(user.id, proxy_url, request.sid, nickname, douyin_id)).start()

@socketio.on('submit_sms_code')
def handle_submit_sms(data):
    sid = request.sid
    code = data.get('code')
    if sid in sms_code_waiter and code:
        sms_code_waiter[sid].put(code)

# ================= Celery 分布式高并发执行器 =================
@celery_app.task
def execute_playwright_job(user_id, acc_id, msg, friends, task_ids, billing_cost=0, billing_free=0):
    with app.app_context():
        user = db.session.get(User, user_id)
        acc = db.session.get(DouyinAccount, acc_id)
        if not user or not acc: return
        
        for t_id in task_ids:
            task = db.session.get(TaskConfig, t_id)
            if task: 
                task.last_status = "正在执行..."
                socketio.emit('task_update', {
                    'task_id': task.id, 'status': task.last_status, 
                    'run_count': task.run_count, 
                    'last_run_time': task.last_run_time.strftime('%Y-%m-%d %H:%M:%S') if task.last_run_time else '从未执行'
                }, namespace='/')
        db.session.commit()
        
        mode_cfg = SystemConfig.query.filter_by(key_name='match_mode').first()
        match_mode = mode_cfg.key_value if mode_cfg and mode_cfg.key_value else 'short_id'
        uid = f"user_{acc.id}"
        tasks_json = json.dumps([{"username": acc.nickname or "未知", "unique_id": uid, "targets": friends}], ensure_ascii=False)
        safe_msg = msg.replace("'", "\\'")
        proxy_val = acc.proxy_ip if hasattr(acc, 'proxy_ip') and acc.proxy_ip else ""
        
        env_lines = [
            f"PROXY_ADDRESS={proxy_val}", f"MESSAGE_TEMPLATE='{safe_msg}'", "HITOKOTO_TYPES='[\"文学\",\"影视\",\"诗词\",\"哲学\"]'",
            f"MATCH_MODE={match_mode}", "BROWSER_TIMEOUT=120000", "FRIEND_LIST_WAIT_TIME=5000", "TASK_RETRY_TIMES=3",
            "LOG_LEVEL=Info", "HEADLESS=True", f"TASKS='{tasks_json}'",
            f"cookies_{uid}='{acc.cookie.strip()}'", f"COOKIES_{uid}='{acc.cookie.strip()}'", "TZ=Asia/Shanghai"
        ]
        with open(f'.env_{uid}', 'w', encoding='utf-8') as f: f.write("\n".join(env_lines))
            
        run_env = os.environ.copy()
        run_env['MESSAGE_TEMPLATE'] = msg; run_env['MATCH_MODE'] = match_mode; run_env['PROXY_ADDRESS'] = proxy_val
        run_env['HEADLESS'] = 'True'; run_env['TASKS'] = tasks_json; run_env[f"cookies_{uid}"] = acc.cookie.strip()
        run_env[f"COOKIES_{uid}"] = acc.cookie.strip(); run_env['TZ'] = 'Asia/Shanghai'

        is_init_run = False
        try:
            result = subprocess.run(["xvfb-run", "-a", "--server-args=-screen 0 1920x1080x24", "python", "main.py"], env=run_env, capture_output=True, text=True, timeout=180)
            log_output = result.stdout + "\n" + result.stderr
            
            if "浏览器安装完成" in log_output or "downloaded to /app/chrome" in log_output or "FFMPEG playwright build" in log_output:
                is_init_run = True
                log_output = "【系统初始化】底层云端浏览器环境已自动配置完成。本次操作不计入免费额度、不扣除积分，请重新点击立即执行即可顺利运行。"
                status = "success"
                if billing_cost:
                    user.points += int(billing_cost)
                if billing_free and user.daily_free_date == get_now().strftime('%Y-%m-%d'):
                    user.daily_free_used = max(0, int(user.daily_free_used or 0) - int(billing_free))
            else:
                status = "success" if "任务完成" in log_output or result.returncode == 0 else "error"
        except subprocess.TimeoutExpired:
            log_output = "【执行严重超时】(超过3分钟被系统强制阻断)。原因分析：您填入的Cookie已失效或格式错误，导致底层脚本在后台陷入了死等扫码验证的无限循环。请删除账号，重新扫码绑定！"
            status = "error"
        except Exception as e:
            log_output = str(e); status = "error"
            
        if os.path.exists(f'.env_{uid}'): os.remove(f'.env_{uid}')

        now_time = get_now()
        for t_id in task_ids:
            task = db.session.get(TaskConfig, t_id)
            if task:
                if status == 'success' and not is_init_run: task.run_count += 1
                task.last_status = '配置完成' if is_init_run else ('成功' if status == 'success' else '异常')
                task.last_run_time = now_time
                db.session.add(ExecutionLog(task_id=task.id, status=status, content=log_output[-1500:], created_at=now_time))
                socketio.emit('task_update', {
                    'task_id': task.id, 'status': task.last_status, 
                    'run_count': task.run_count, 
                    'last_run_time': task.last_run_time.strftime('%Y-%m-%d %H:%M:%S')
                }, namespace='/')
        db.session.commit()
        
        if not is_init_run:
            if status == 'success' and user.notify_success:
                title, content = render_tpl_with_title('mail_tpl_success', user, acc, log_output[-100:])
                send_email(user.email, title, content)
            elif status == 'error' and user.notify_fail:
                title, content = render_tpl_with_title('mail_tpl_fail', user, acc, log_output[-100:])
                send_email(user.email, title, content)

def check_system_notifications():
    try:
        with app.app_context():
            now = get_now(); today_str = now.strftime('%Y-%m-%d')
            sys_chk = SystemConfig.query.filter_by(key_name='last_daily_check').first()
            if sys_chk and sys_chk.key_value == today_str: return
                
            for u in User.query.all():
                state = json.loads(u.notify_state or "{}")
                if u.notify_points:
                    if u.points <= 0 and state.get('points_0') != today_str:
                        title, content = render_tpl_with_title('mail_tpl_points', u, reason="积分已完全耗尽，自动任务已暂停。")
                        send_email(u.email, title, content); state['points_0'] = today_str
                    elif 0 < u.points < 5 and state.get('points_low') != today_str:
                        title, content = render_tpl_with_title('mail_tpl_points', u, reason="积分余额已低于5分安全线，随时可能断缴。")
                        send_email(u.email, title, content); state['points_low'] = today_str
                
                if u.notify_vip and u.vip_expire:
                    days_left = (u.vip_expire.date() - now.date()).days
                    if days_left in [3, 2, 1, 0, -7]:
                        key = f"vip_{days_left}_{today_str}"
                        if state.get('last_vip_alert') != key:
                            if days_left == -7: title, content = render_tpl_with_title('mail_tpl_vip', u, reason="您的会员已经过期长达一周！现已恢复按次计费模式")
                            elif days_left == 0: title, content = render_tpl_with_title('mail_tpl_vip', u, reason="您的会员特权即将在【今天】失效")
                            else: title, content = render_tpl_with_title('mail_tpl_vip', u, reason=f"您的会员特权仅剩 {days_left} 天")
                            send_email(u.email, title, content); state['last_vip_alert'] = key
                u.notify_state = json.dumps(state)
            if not sys_chk: db.session.add(SystemConfig(key_name='last_daily_check', key_value=today_str))
            else: sys_chk.key_value = today_str
            db.session.commit()
    except Exception as e: print(f"通知检测异常: {e}")

def start_scheduler():
    print("独立调度器已启动。", flush=True)
    scheduler_loop()

def scheduler_loop():
    last_cleanup_date = None
    while True:
        try:
            with app.app_context():
                now = get_now(); today_str = now.strftime('%Y-%m-%d')
                check_system_notifications()
                
                if today_str != last_cleanup_date:
                    try:
                        os.system('find /tmp -name "playwright*" -type d -mtime +1 -exec rm -rf {} +')
                        os.system('find /tmp -name "xvfb-run*" -type d -mtime +1 -exec rm -rf {} +')
                        last_cleanup_date = today_str
                    except: pass

                for t in TaskConfig.query.all():
                    if not t.target_run_time or t.target_run_time.strftime('%Y-%m-%d') != today_str:
                        t.target_run_time = compute_target_run_time(t.time_range); db.session.commit()
                    if t.last_run_date == today_str: continue
                    if now >= t.target_run_time:
                        user = t.account.user
                        ok, billing_msg, cost, free_count = reserve_task_quota(user, 1)
                        if not ok:
                            error_mark = "no_money_" + today_str
                            if t.last_run_date != error_mark: t.last_run_date = error_mark; t.last_status = "积分不足"; db.session.commit()
                            continue
                        t.last_run_date = today_str; t.last_status = "排队执行中..."; db.session.commit()
                        msgs = [m.strip() for m in t.message.split('\n') if m.strip()]
                        chosen_msg = random.choice(msgs) if msgs else "[火花]"
                        execute_playwright_job.delay(user.id, t.account_id, chosen_msg, [t.friend_id], [t.id], cost, free_count)
        except Exception as e: print(f"调度器异常: {e}")
        time.sleep(30)

if os.getenv('RUN_SCHEDULER', '0') == '1':
    threading.Thread(target=scheduler_loop, daemon=True).start()

# ================= HTTP 路由接口 =================
@app.route('/')
def index(): return render_template('index.html')

def get_user():
    token = request.headers.get('Authorization')
    return User.query.filter_by(token=token).first() if token else None

def check_admin(): return request.headers.get('Authorization') == ADMIN_TOKEN

@app.route('/api/system/public', methods=['GET'])
def get_public_sys():
    ann = SystemConfig.query.filter_by(key_name='announcement').first()
    name = SystemConfig.query.filter_by(key_name='site_name').first()
    title = SystemConfig.query.filter_by(key_name='site_title').first()
    enable_spark = SystemConfig.query.filter_by(key_name='enable_spark_days').first()
    
    return jsonify({"code": 200, "data": {
        "announcement": ann.key_value if ann else "", 
        "site_name": name.key_value if name else "续火花平台", 
        "site_title": title.key_value if title else "抖音续火花托管平台",
        "enable_spark_days": enable_spark.key_value if enable_spark else "1"
    }})

@app.route('/api/auth/send_code', methods=['POST'])
def send_code():
    email = request.json.get('email')
    if not is_valid_email(email): return jsonify({"code": 400, "msg": "系统限制：仅支持使用常见邮箱注册。"})
    is_register = request.json.get('is_register', True)
    if is_register and User.query.filter_by(email=email).first(): return jsonify({"code": 400, "msg": "该邮箱已被注册"})
    code = ''.join(random.choices(string.digits, k=6))
    db.session.add(VerifyCode(email=email, code=code, expire_at=get_now() + timedelta(minutes=10)))
    db.session.commit()
    html_content = f"""<div style="max-width:600px; margin:0 auto; padding:25px; background:#ffffff; border-radius:12px; box-shadow: 0 4px 15px rgba(0,0,0,0.05); border:1px solid #e2e8f0; font-family: sans-serif;"><h2 style="color:#6366f1; margin-top:0; padding-bottom: 10px; border-bottom: 1px solid #f1f5f9;">账号安全验证</h2><p style="color:#334155; font-size:15px; margin-top:20px;">您好：</p><p style="color:#334155; font-size:15px;">您正在进行敏感操作，本次的动态验证码为：</p><div style="background:#f8fafc; padding:20px; text-align:center; border-radius:8px; margin:25px 0; border: 1px dashed #cbd5e1;"><b style="font-size:36px; color:#10b981; letter-spacing:8px;">{code}</b></div><p style="color:#64748b; font-size:13px;">请在 10 分钟内完成验证。为保障资产安全，请勿将此验证码泄露给他人。</p><div style="margin-top:35px; padding-top:15px; border-top:1px solid #f1f5f9; color:#94a3b8; font-size:12px;">* 此邮件由系统自动发出，请勿直接回复。<br>* 防伪追踪码：{uuid.uuid4().hex[:12].upper()}</div></div>"""
    success, msg = send_email(email, "【安全中心】您的动态安全验证码", html_content)
    return jsonify({"code": 200 if success else 500, "msg": "验证码已发送至邮箱" if success else f"验证邮件发送失败: {msg}"})

@app.route('/api/auth/register', methods=['POST'])
def register():
    data = request.json
    email = data.get('email')
    if data.get('password') != data.get('password_confirm'): return jsonify({"code": 400, "msg": "两次密码不一致"})
    if User.query.filter_by(username=data.get('username')).first(): return jsonify({"code": 400, "msg": "账号已存在"})
    if User.query.filter_by(email=email).first(): return jsonify({"code": 400, "msg": "邮箱已被注册"})
    if not is_valid_email(email): return jsonify({"code": 400, "msg": "系统限制：仅支持常见邮箱注册"})
    vc = VerifyCode.query.filter_by(email=email, code=data.get('code')).filter(VerifyCode.expire_at > get_now()).order_by(VerifyCode.id.desc()).first()
    if not vc: return jsonify({"code": 400, "msg": "验证码错误或已过期"})
    
    inviter_id = None
    if data.get('invite_code'):
        inv_user = User.query.filter_by(invite_code=data.get('invite_code')).first()
        if inv_user: inviter_id = inv_user.id
        
    r_type = SystemConfig.query.filter_by(key_name='reg_reward_type').first()
    r_val = SystemConfig.query.filter_by(key_name='reg_reward_value').first()
    reward_type = r_type.key_value if r_type else 'points'
    reward_value = int(r_val.key_value) if r_val else 10

    new_user = User(username=data.get('username'), password=data.get('password'), email=email, qq_number=email.split('@')[0] if email.lower().endswith('@qq.com') else "", invite_code=generate_invite_code(), invited_by=inviter_id, vip_level=1)
    if reward_type == 'points':
        new_user.points = reward_value; new_user.vip_expire = None; new_user.vip_level = 1
    else:
        new_user.points = 0; new_user.vip_expire = None; new_user.vip_level = 1
    db.session.add(new_user); db.session.commit()
    
    welcome_html = f"""<div style="max-width:600px; margin:0 auto; padding:25px; background:#ffffff; border-radius:12px; box-shadow: 0 4px 15px rgba(0,0,0,0.05); border:1px solid #e2e8f0; font-family: sans-serif;"><h2 style="color:#10b981; margin-top:0;">🎉 欢迎加入平台！</h2><p style="color:#334155; font-size:15px; margin-top:20px;">尊敬的 <b>{data.get('username')}</b>：</p><p style="color:#334155; font-size:15px;">系统已为您成功创建档案。并且已自动将您的 <b>新用户入驻奖励</b> 下发至您的账户中，请前往个人中心查收！</p><p style="color:#64748b; font-size:13px; margin-top:30px;">祝您使用愉快！</p></div>"""
    threading.Thread(target=send_email, args=(email, "【注册成功】欢迎您的加入", welcome_html)).start()
    return jsonify({"code": 200, "msg": "注册成功"})

@app.route('/api/auth/login', methods=['POST'])
def login():
    data = request.json
    if data.get('username') == ADMIN_USERNAME and data.get('password') == ADMIN_PASSWORD:
        return jsonify({"code": 200, "msg": "管理员登录成功", "token": ADMIN_TOKEN, "is_admin": True})
    user = User.query.filter_by(username=data.get('username'), password=data.get('password')).first()
    if not user: return jsonify({"code": 401, "msg": "账号或密码错误"})
    user.token = str(uuid.uuid4()); db.session.commit()
    return jsonify({"code": 200, "msg": "登录成功", "token": user.token, "is_admin": False})

@app.route('/api/user/dashboard', methods=['GET'])
def get_dashboard_stats():
    user = get_user()
    if not user: return jsonify({"code": 401})
    acc_count = len(user.accounts); task_count = sum(len(a.tasks) for a in user.accounts)
    run_count = sum(t.run_count for a in user.accounts for t in a.tasks)
    dates = [(get_now() - timedelta(days=i)).strftime('%m-%d') for i in range(6, -1, -1)]
    billing = get_billing_snapshot(user)
    return jsonify({"code": 200, "data": {"acc_count": acc_count, "task_count": task_count, "run_count": run_count, "points": user.points, "vip_level": billing["vip_level"], "vip_name": billing["vip_name"], "daily_free_quota": billing["daily_free_quota"], "daily_free_used": billing["daily_free_used"], "daily_free_remaining": billing["daily_free_remaining"], "vip_expire": user.vip_expire.strftime('%Y-%m-%d') if user.vip_expire else "无", "invite_code": user.invite_code, "chart": {"dates": dates, "accs": [acc_count] * 7, "tasks": [task_count] * 7, "runs": [run_count - (6-i)*2 if run_count-(6-i)*2 > 0 else 0 for i in range(7)]}}})

@app.route('/api/user/info', methods=['GET'])
def get_user_info():
    user = get_user()
    if not user: return jsonify({"code": 401})
    accounts_data = []
    for acc in user.accounts:
        tasks_data = [{"id": t.id, "friend_id": t.friend_id, "remark": t.remark, "message": t.message, "time_range": t.time_range, "run_count": t.run_count, "last_status": t.last_status, "last_run_time": t.last_run_time.strftime('%Y-%m-%d %H:%M:%S') if t.last_run_time else '从未执行'} for t in acc.tasks]
        
        fc_list = []
        try:
            cache_str = getattr(acc, 'friends_cache', None)
            if not cache_str: cache_str = "[]"
            fc_list = json.loads(cache_str)
        except: pass
        
        accounts_data.append({
            "id": acc.id, "douyin_id": acc.douyin_id, "nickname": acc.nickname, 
            "cookie": acc.cookie, "proxy_ip": acc.proxy_ip, "friends_cache": fc_list, 
            "tasks": tasks_data
        })
    return jsonify({"code": 200, "data": {"username": user.username, "email": user.email, "qq_number": user.qq_number, "notify": {"success": user.notify_success, "fail": user.notify_fail, "vip": user.notify_vip, "points": user.notify_points}, "accounts": accounts_data}})

@app.route('/api/user/send_profile_code', methods=['POST'])
def send_profile_code():
    user = get_user()
    if not user: return jsonify({"code": 401, "msg": "未登录"})
    code = ''.join(random.choices(string.digits, k=6))
    db.session.add(VerifyCode(email=user.email, code=code, expire_at=get_now() + timedelta(minutes=10)))
    db.session.commit()
    html_content = f"""<div style="max-width:600px; margin:0 auto; padding:25px; background:#ffffff; border-radius:12px; box-shadow: 0 4px 15px rgba(0,0,0,0.05); border:1px solid #e2e8f0; font-family: sans-serif;"><h2 style="color:#ef4444; margin-top:0; padding-bottom: 10px; border-bottom: 1px solid #f1f5f9;">安全资料变更确认</h2><p style="color:#334155; font-size:15px; margin-top:20px;">尊敬的 <b>{user.username}</b>：</p><p style="color:#334155; font-size:15px;">系统检测到您正在申请修改关键安全信息（如密码或邮箱）。为确认是您本人操作，验证码为：</p><div style="background:#fffbeb; padding:20px; text-align:center; border-radius:8px; margin:25px 0; border: 1px dashed #fcd34d;"><b style="font-size:36px; color:#f59e0b; letter-spacing:8px;">{code}</b></div><p style="color:#64748b; font-size:13px;">请在 10 分钟内完成验证。如非您本人操作，请立即登录平台修改您的密码！</p><div style="margin-top:35px; padding-top:15px; border-top:1px solid #f1f5f9; color:#94a3b8; font-size:12px;">* 此为系统安全验证邮件，请勿回复。<br>* 安全操作审计流：{uuid.uuid4().hex[:12].upper()}</div></div>"""
    success, msg = send_email(user.email, "【安全警告】敏感信息变更授权", html_content)
    return jsonify({"code": 200 if success else 500, "msg": "验证码已发送至您当前绑定的邮箱" if success else f"验证邮件发送失败: {msg}"})

@app.route('/api/user/profile', methods=['PUT'])
def edit_profile():
    user = get_user()
    if not user: return jsonify({"code": 401})
    data = request.json
    if data.get('code') and data.get('verify_email'):
        vc = VerifyCode.query.filter_by(email=data.get('verify_email'), code=data.get('code')).filter(VerifyCode.expire_at > get_now()).order_by(VerifyCode.id.desc()).first()
        if not vc: return jsonify({"code": 400, "msg": "验证码错误或已过期"})
        if data.get('password'): user.password = data['password']
        if data.get('email'): 
            new_email = data['email']
            if not is_valid_email(new_email): return jsonify({"code": 400, "msg": "不支持该邮箱后缀绑定，请使用常用邮箱"})
            user.email = new_email
            if new_email.lower().endswith('@qq.com') and not data.get('qq_number'): user.qq_number = new_email.split('@')[0]
    if 'qq_number' in data: user.qq_number = data['qq_number']
    if 'notify' in data:
        user.notify_success = data['notify'].get('success', True); user.notify_fail = data['notify'].get('fail', True)
        user.notify_vip = data['notify'].get('vip', True); user.notify_points = data['notify'].get('points', True)
    db.session.commit()
    return jsonify({"code": 200, "msg": "信息修改成功"})

@app.route('/api/user/account', methods=['POST'])
def manage_account():
    user = get_user()
    if request.method == 'POST':
        db.session.add(DouyinAccount(user_id=user.id, douyin_id=request.json.get('douyin_id'), nickname=request.json.get('nickname'), cookie=request.json.get('cookie')))
        db.session.commit(); return jsonify({"code": 200, "msg": "账号添加成功"})

@app.route('/api/user/account/<int:acc_id>', methods=['DELETE'])
def delete_account(acc_id):
    acc = DouyinAccount.query.filter_by(id=acc_id, user_id=get_user().id).first()
    if acc: db.session.delete(acc); db.session.commit()
    return jsonify({"code": 200, "msg": "账号已删除"})

@app.route('/api/user/task', methods=['POST'])
def add_task():
    user = get_user()
    acc = DouyinAccount.query.filter_by(id=request.json.get('account_id'), user_id=user.id).first()
    if not acc: return jsonify({"code": 403})
    task = TaskConfig(account_id=acc.id, friend_id=request.json.get('friend_id'), remark=request.json.get('remark', ''), message=request.json.get('message'), time_range=request.json.get('time_range'))
    task.target_run_time = compute_target_run_time(task.time_range)
    db.session.add(task); db.session.commit()
    return jsonify({"code": 200, "msg": "添加好友成功"})

@app.route('/api/user/task/batch', methods=['POST'])
def batch_add_task():
    user = get_user()
    if not user: return jsonify({"code": 401})
    data = request.json
    acc_id = data.get('account_id')
    friends = data.get('friends', [])
    
    acc = DouyinAccount.query.filter_by(id=acc_id, user_id=user.id).first()
    if not acc: return jsonify({"code": 403, "msg": "账号不存在或无权限"})
    
    count = 0
    for f in friends:
        t = TaskConfig(
            account_id=acc.id,
            friend_id=f.get('douyin_id'),
            remark=f.get('remark') or f.get('nickname') or '抖音好友',
            message="[火花]",
            time_range="06:00-08:00"
        )
        t.target_run_time = compute_target_run_time(t.time_range)
        db.session.add(t)
        count += 1
    db.session.commit()
    return jsonify({"code": 200, "msg": f"成功批量添加了 {count} 个续火好友！"})

@app.route('/api/user/task/<int:task_id>', methods=['PUT', 'DELETE'])
def edit_task(task_id):
    task = db.session.get(TaskConfig, task_id)
    if request.method == 'DELETE': db.session.delete(task); db.session.commit(); return jsonify({"code": 200, "msg": "已删除好友"})
    task.friend_id = request.json.get('friend_id'); task.remark = request.json.get('remark', ''); task.message = request.json.get('message'); task.time_range = request.json.get('time_range')
    task.target_run_time = compute_target_run_time(task.time_range); task.last_run_date = None 
    db.session.commit()
    return jsonify({"code": 200, "msg": "配置已更新"})

@app.route('/api/user/task/<int:task_id>/logs', methods=['GET'])
def get_task_logs(task_id):
    logs = ExecutionLog.query.filter_by(task_id=task_id).order_by(ExecutionLog.id.desc()).limit(20).all()
    return jsonify({"code": 200, "data": [{"time": l.created_at.strftime('%Y-%m-%d %H:%M:%S'), "status": l.status, "content": l.content} for l in logs]})

@app.route('/api/user/topup', methods=['POST'])
def topup():
    user = get_user()
    cdkey = CDKey.query.filter_by(key_str=request.json.get('key_str')).first()
    if not cdkey: return jsonify({"code": 404, "msg": "卡密不存在"})
    if cdkey.is_event:
        if UserEventRecord.query.filter_by(user_id=user.id, key_id=cdkey.id).first(): return jsonify({"code": 400, "msg": "您已兑换过此活动福利，每人限领一次"})
        db.session.add(UserEventRecord(user_id=user.id, key_id=cdkey.id)); cdkey.used_count += 1
    else:
        if cdkey.is_used: return jsonify({"code": 400, "msg": "普通卡密已被使用"})
        cdkey.is_used = True; cdkey.used_by = user.username
        
    if cdkey.key_type == 'points':
        user.points += cdkey.value; msg = f"兑换成功！获得 {cdkey.value} 积分"
    else:
        target_level = 3 if cdkey.key_type == 'vip3' else 2
        current_level = get_effective_vip_level(user)
        base = user.vip_expire if current_level == target_level and user.vip_expire and user.vip_expire > get_now() else get_now()
        user.vip_level = target_level
        user.vip_expire = base + timedelta(days=cdkey.value)
        msg = f"兑换成功！{get_billing_snapshot(user)['vip_name']}延长 {cdkey.value} 天"
        
    if not user.has_first_topup and not cdkey.is_event:
        user.has_first_topup = True
        if user.invited_by:
            inviter = db.session.get(User, user.invited_by)
            if inviter:
                if cdkey.key_type == 'points': inviter.points += cdkey.value
                else:
                    target_level = 3 if cdkey.key_type == 'vip3' else 2
                    current_level = get_effective_vip_level(inviter)
                    base_inv = inviter.vip_expire if current_level == target_level and inviter.vip_expire and inviter.vip_expire > get_now() else get_now()
                    inviter.vip_level = target_level
                    inviter.vip_expire = base_inv + timedelta(days=cdkey.value)
                threading.Thread(target=send_email, args=(inviter.email, "邀请奖励到账", f"您邀请的用户完成了首次兑换，系统已为您自动发放了同等奖励！")).start()
    db.session.commit()
    return jsonify({"code": 200, "msg": msg})

@app.route('/api/user/run_specific', methods=['POST'])
def run_specific():
    user = get_user()
    data = request.json
    tasks_to_run = []
    if data.get('task_id'):
        t = db.session.get(TaskConfig, data.get('task_id'))
        if t and t.account.user_id == user.id: tasks_to_run.append(t)
    elif data.get('account_id'):
        acc = DouyinAccount.query.filter_by(id=data.get('account_id'), user_id=user.id).first()
        if acc: tasks_to_run.extend(acc.tasks)
    
    if not tasks_to_run: return jsonify({"code": 400, "msg": "未找到任务"})
    
    ok, billing_msg, cost, free_count = reserve_task_quota(user, len(tasks_to_run))
    if not ok: return jsonify({"code": 400, "msg": billing_msg})
        
    msg_groups = {}
    for t in tasks_to_run:
        t.last_status = "排队执行中..."
        msgs = [m.strip() for m in t.message.split('\n') if m.strip()]
        msg_groups.setdefault(random.choice(msgs) if msgs else "[火花]", []).append(t)
        socketio.emit('task_update', {
            'task_id': t.id, 'status': t.last_status, 
            'run_count': t.run_count, 
            'last_run_time': t.last_run_time.strftime('%Y-%m-%d %H:%M:%S') if t.last_run_time else '从未执行'
        }, namespace='/')
    db.session.commit()
        
    remaining_cost = cost
    remaining_free = free_count
    for msg, t_list in msg_groups.items():
        group_size = len(t_list)
        group_free = min(remaining_free, group_size)
        group_cost = group_size - group_free
        remaining_free -= group_free
        remaining_cost -= group_cost
        execute_playwright_job.delay(user.id, t_list[0].account_id, msg, [t.friend_id for t in t_list], [t.id for t in t_list], group_cost, group_free)
    return jsonify({"code": 200, "msg": f"已加入分布式队列，请稍后查看日志。{billing_msg}"})

# ========================= 管理端接口 =========================
@app.route('/api/admin/users', methods=['GET'])
def admin_users():
    if not check_admin(): return jsonify({"code": 401})
    res = []
    for u in User.query.all():
        accounts_data = []
        for a in u.accounts:
            tasks_data = [{"id": t.id, "friend_id": t.friend_id, "remark": t.remark, "message": t.message, "time_range": t.time_range, "run_count": t.run_count, "last_status": t.last_status, "last_run_time": t.last_run_time.strftime('%Y-%m-%d %H:%M:%S') if t.last_run_time else '从未执行'} for t in a.tasks]
            accounts_data.append({"id": a.id, "douyin_id": a.douyin_id, "nickname": a.nickname, "cookie": a.cookie, "proxy_ip": a.proxy_ip, "tasks": tasks_data})
        billing = get_billing_snapshot(u)
        res.append({"id": u.id, "username": u.username, "email": u.email, "qq_number": u.qq_number, "points": u.points, "vip_level": billing["vip_level"], "vip_name": billing["vip_name"], "daily_free_used": billing["daily_free_used"], "daily_free_remaining": billing["daily_free_remaining"], "vip_expire": u.vip_expire.strftime('%Y-%m-%d') if u.vip_expire else "无", "is_pinned": u.is_pinned, "accounts": accounts_data})
    return jsonify({"code": 200, "data": res})

@app.route('/api/admin/user/<int:user_id>', methods=['PUT'])
def admin_edit_user(user_id):
    if not check_admin(): return jsonify({"code": 401})
    user = db.session.get(User, user_id)
    data = request.json
    if 'password' in data and data['password']: user.password = data['password']
    if 'email' in data and data['email']: user.email = data['email']
    if 'qq_number' in data: user.qq_number = data['qq_number']
    if 'points' in data: user.points = int(data['points'])
    if 'is_pinned' in data: user.is_pinned = bool(data['is_pinned'])
    if 'vip_level' in data: user.vip_level = max(1, min(3, int(data['vip_level'] or 1)))
    if 'vip_expire' in data:
        vip_str = data['vip_expire']
        if not vip_str or vip_str == '无': user.vip_expire = None
        else:
            try: user.vip_expire = datetime.strptime(vip_str, '%Y-%m-%d' if len(vip_str)<=10 else '%Y-%m-%d %H:%M:%S')
            except: pass
    if int(getattr(user, 'vip_level', 1) or 1) == 1:
        user.vip_expire = None
    db.session.commit()
    return jsonify({"code": 200, "msg": "修改成功"})

@app.route('/api/admin/account/<int:acc_id>/cookie', methods=['PUT'])
def admin_edit_cookie(acc_id):
    if not check_admin(): return jsonify({"code": 401})
    acc = db.session.get(DouyinAccount, acc_id)
    if acc:
        acc.cookie = request.json.get('cookie', acc.cookie)
        db.session.commit()
        return jsonify({"code": 200, "msg": "用户账号Cookie更新成功"})
    return jsonify({"code": 404, "msg": "账号不存在"})

@app.route('/api/admin/run_specific', methods=['POST'])
def admin_run_specific():
    if not check_admin(): return jsonify({"code": 401})
    data = request.json
    tasks_to_run = []
    if data.get('task_id'):
        t = db.session.get(TaskConfig, data.get('task_id'))
        if t: tasks_to_run.append(t)
    elif data.get('account_id'):
        acc = db.session.get(DouyinAccount, data.get('account_id'))
        if acc: tasks_to_run.extend(acc.tasks)
    
    if not tasks_to_run: return jsonify({"code": 400, "msg": "未找到任务"})
    
    user = tasks_to_run[0].account.user
    msg_groups = {}
    for t in tasks_to_run:
        t.last_status = "排队中(管理员触发)..."
        msgs = [m.strip() for m in t.message.split('\n') if m.strip()]
        msg_groups.setdefault(random.choice(msgs) if msgs else "[火花]", []).append(t)
        socketio.emit('task_update', {
            'task_id': t.id, 'status': t.last_status, 
            'run_count': t.run_count, 
            'last_run_time': t.last_run_time.strftime('%Y-%m-%d %H:%M:%S') if t.last_run_time else '从未执行'
        }, namespace='/')
    db.session.commit()
        
    for msg, t_list in msg_groups.items():
        execute_playwright_job.delay(user.id, t_list[0].account_id, msg, [t.friend_id for t in t_list], [t.id for t in t_list], 0, 0)
    return jsonify({"code": 200, "msg": "已将该任务加入分布式执行队列"})

@app.route('/api/admin/task/<int:task_id>', methods=['PUT', 'DELETE'])
def admin_edit_task(task_id):
    if not check_admin(): return jsonify({"code": 401})
    task = db.session.get(TaskConfig, task_id)
    if not task: return jsonify({"code": 404})
    if request.method == 'DELETE': 
        db.session.delete(task); db.session.commit()
        return jsonify({"code": 200, "msg": "已强制删除该用户的续火好友"})
    
    task.friend_id = request.json.get('friend_id')
    task.remark = request.json.get('remark', '')
    task.message = request.json.get('message')
    task.time_range = request.json.get('time_range')
    task.target_run_time = compute_target_run_time(task.time_range)
    db.session.commit()
    return jsonify({"code": 200, "msg": "用户任务配置更新成功"})

@app.route('/api/admin/task/<int:task_id>/logs', methods=['GET'])
def admin_get_task_logs(task_id):
    if not check_admin(): return jsonify({"code": 401})
    logs = ExecutionLog.query.filter_by(task_id=task_id).order_by(ExecutionLog.id.desc()).limit(20).all()
    return jsonify({"code": 200, "data": [{"time": l.created_at.strftime('%Y-%m-%d %H:%M:%S'), "status": l.status, "content": l.content} for l in logs]})

@app.route('/api/admin/config', methods=['GET', 'POST'])
def admin_config():
    if not check_admin(): return jsonify({"code": 401})
    keys = ['proxy_api_url', 'site_name', 'site_title', 'reg_reward_type', 'reg_reward_value', 'smtp_host', 'smtp_port', 'smtp_user', 'smtp_pass', 'announcement', 'match_mode', 'mail_tpl_success_title', 'mail_tpl_success', 'mail_tpl_fail_title', 'mail_tpl_fail', 'mail_tpl_vip_title', 'mail_tpl_vip', 'mail_tpl_points_title', 'mail_tpl_points', 'pw_wait_creator', 'pw_wait_login_click', 'pw_wait_login_success', 'pw_wait_clear_cache', 'pw_wait_chat_load', 'pw_scroll_times', 'pw_wait_scroll_interval', 'enable_spark_days']
    if request.method == 'POST':
        for k in keys:
            if k in request.json:
                cfg = SystemConfig.query.filter_by(key_name=k).first()
                if not cfg: db.session.add(SystemConfig(key_name=k, key_value=str(request.json[k]).strip()))
                else: cfg.key_value = str(request.json[k]).strip()
        db.session.commit()
        return jsonify({"code": 200, "msg": "保存成功"})
    return jsonify({"code": 200, "data": {k: (SystemConfig.query.filter_by(key_name=k).first().key_value if SystemConfig.query.filter_by(key_name=k).first() else "") for k in keys}})

@app.route('/api/admin/send_custom_mail', methods=['POST'])
def send_custom_mail():
    if not check_admin(): return jsonify({"code": 401})
    data = request.json
    users = User.query.filter_by(is_pinned=True).all() if data.get('only_pinned') else User.query.all()
    count = 0
    for u in users:
        s_fmt = data.get('subject', '').replace('{username}', u.username).replace('{points}', str(u.points))
        c_fmt = data.get('content', '').replace('{username}', u.username).replace('{points}', str(u.points))
        threading.Thread(target=send_email, args=(u.email, s_fmt, c_fmt)).start()
        count += 1
    return jsonify({"code": 200, "msg": f"群发队列投递完毕，已触达 {count} 名用户"})

@app.route('/api/admin/keys', methods=['GET', 'POST'])
def admin_keys():
    if not check_admin(): return jsonify({"code": 401})
    if request.method == 'POST':
        k_type = request.json.get('type', 'points'); is_ev = request.json.get('is_event', False); val = int(request.json.get('value', 10))
        if k_type not in ['points', 'vip2', 'vip3']: k_type = 'vip2'
        prefix = {'points': 'PT-', 'vip2': 'V2-', 'vip3': 'V3-'}.get(k_type, 'V2-')
        for _ in range(int(request.json.get('count', 1))): db.session.add(CDKey(key_str=prefix + str(uuid.uuid4()).split('-')[0].upper(), key_type=k_type, value=val, is_event=is_ev))
        db.session.commit()
        return jsonify({"code": 200, "msg": "生成成功"})
    return jsonify({"code": 200, "data": [{"id": k.id, "key_str": k.key_str, "type": k.key_type, "value": k.value, "is_event": k.is_event, "used_count": k.used_count, "is_used": k.is_used, "used_by": k.used_by} for k in CDKey.query.order_by(CDKey.id.desc()).all()]})

@app.route('/api/admin/logs', methods=['GET'])
def admin_logs():
    if not check_admin(): return jsonify({"code": 401})
    uid_filter = request.args.get('uid')
    query = ExecutionLog.query.order_by(ExecutionLog.id.desc())
    if uid_filter: query = query.join(TaskConfig).join(DouyinAccount).filter(DouyinAccount.user_id == uid_filter)
    res = []
    for l in query.limit(100).all():
        t = l.task; a = t.account if t else None; u = a.user if a else None
        res.append({"id": l.id, "time": l.created_at.strftime('%Y-%m-%d %H:%M:%S'), "status": l.status, "content": l.content, "username": u.username if u else "未知", "douyin_id": a.nickname or a.douyin_id if a else "未知", "friend_id": t.remark or t.friend_id if t else "未知"})
    return jsonify({"code": 200, "data": res})

@app.route('/api/admin/run', methods=['POST'])
def trigger_run():
    if not check_admin(): return jsonify({"code": 401})
    with app.app_context():
        for user in User.query.all():
            for acc in user.accounts:
                if not acc.tasks: continue
                ok, billing_msg, cost, free_count = reserve_task_quota(user, len(acc.tasks))
                if not ok: continue
                msg_groups = {}
                for t in acc.tasks:
                    t.last_status = "排队中(管理员全量触发)..."
                    msgs = [m.strip() for m in t.message.split('\n') if m.strip()]
                    msg_groups.setdefault(random.choice(msgs) if msgs else "[火花]", []).append(t)
                db.session.commit()
                remaining_cost = cost
                remaining_free = free_count
                for msg, t_list in msg_groups.items():
                    group_size = len(t_list)
                    group_free = min(remaining_free, group_size)
                    group_cost = group_size - group_free
                    remaining_free -= group_free
                    remaining_cost -= group_cost
                    execute_playwright_job.delay(user.id, acc.id, msg, [t.friend_id for t in t_list], [t.id for t in t_list], group_cost, group_free)
    return jsonify({"code": 200, "msg": "已强制全部执行！"})

@app.route('/api/admin/smtp_test', methods=['POST'])
def admin_smtp_test():
    if not check_admin(): return jsonify({"code": 401})
    email = request.json.get('email')
    if not email: return jsonify({"code": 400, "msg": "未提供接收测试的邮箱地址"})
    html_content = f"""<div style="max-width:600px; margin:0 auto; padding:25px; background:#ffffff; border-radius:12px; box-shadow: 0 4px 15px rgba(0,0,0,0.05); border:1px solid #e2e8f0; font-family: sans-serif;"><h2 style="color:#10b981; margin-top:0;">系统SMTP诊断测试成功</h2><p style="color:#334155; font-size:15px; margin-top:20px;">尊敬的管理员：</p><p style="color:#334155; font-size:15px;">如果您看到了这封带有防垃圾特征追踪码的邮件，说明您配置的发信服务器 <b>已完美连通</b> 且有效绕过了拦截！</p><p style="color:#64748b; font-size:13px; margin-top:30px;">追踪探测号: {uuid.uuid4().hex}</p></div>"""
    success, msg = send_email(email, "【系统测试】发信链路诊断报告", html_content)
    return jsonify({"code": 200 if success else 500, "msg": "发送成功" if success else msg})

@app.route('/debug/screenshot', methods=['GET'])
def debug_screenshot():
    import os
    from flask import send_file
    img_type = request.args.get('type', 'error')
    path = '/app/extract_failed.png' if img_type == 'extract' else '/app/error_screenshot.png'
    if os.path.exists(path): return send_file(path, mimetype='image/png')
    return f"暂无截图 ({path})。"

if __name__ == '__main__':
    socketio.run(app, host='0.0.0.0', port=5009, allow_unsafe_werkzeug=True)
