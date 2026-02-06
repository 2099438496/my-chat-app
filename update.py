import os
import subprocess
import sys

# ================= 1. 新版 server.js 代码 =================
server_js_content = r"""const express = require('express');
const app = express();
const http = require('http');
const server = http.createServer(app);
const { Server } = require("socket.io");
const io = new Server(server, { maxHttpBufferSize: 5e7 }); // 50MB 限制
const sqlite3 = require('sqlite3').verbose();
const bcrypt = require('bcryptjs');

const db = new sqlite3.Database('chat.db');

db.serialize(() => {
    db.run("CREATE TABLE IF NOT EXISTS users (username TEXT PRIMARY KEY, password TEXT)");
    db.run("CREATE TABLE IF NOT EXISTS messages (id INTEGER PRIMARY KEY AUTOINCREMENT, user TEXT, content TEXT, time TEXT, type TEXT)");
});

app.get('/', (req, res) => { res.sendFile(__dirname + '/index.html'); });

const onlineUsers = {};

io.on('connection', (socket) => {
    
    // --- 注册 ---
    socket.on('register', (data) => {
        const { username, password } = data;
        db.get("SELECT * FROM users WHERE username = ?", [username], (err, row) => {
            if (row) {
                socket.emit('register_response', { success: false, msg: '用户名已存在' });
            } else {
                const hash = bcrypt.hashSync(password, 10);
                const stmt = db.prepare("INSERT INTO users VALUES (?, ?)");
                stmt.run(username, hash, (err) => {
                    if (err) socket.emit('register_response', { success: false, msg: '注册失败' });
                    else socket.emit('register_response', { success: true, msg: '注册成功' });
                });
                stmt.finalize();
            }
        });
    });

    // --- 登录 ---
    socket.on('login', (data) => {
        const { username, password } = data;
        db.get("SELECT * FROM users WHERE username = ?", [username], (err, row) => {
            if (!row || !bcrypt.compareSync(password, row.password)) {
                socket.emit('login_response', { success: false, msg: '账号或密码错误' });
            } else {
                onlineUsers[socket.id] = username;
                socket.emit('login_response', { success: true, username: username });
                
                io.emit('system', `${username} 上线了`);
                io.emit('update user list', Object.values(onlineUsers));

                // 加载历史消息
                db.all("SELECT user, content, time, type FROM messages ORDER BY id ASC LIMIT 50", (err, rows) => {
                    if (rows) rows.forEach(r => socket.emit('chat message', { user: r.user, text: r.content, type: r.type || 'text', time: r.time }));
                });
            }
        });
    });

    // --- 核心：消息处理 (含指令逻辑) ---
    socket.on('chat message', (data) => {
        const name = onlineUsers[socket.id];
        if (!name) return;

        const time = new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
        const msgContent = typeof data === 'string' ? data : data.msg;
        const msgType = data.type || 'text';

        // 🌟 新增：检查是否是指令 (只处理文本类型)
        if (msgType === 'text' && msgContent.startsWith('/')) {
            handleCommand(socket, name, msgContent);
            return; // 是指令就不入库，也不作为普通消息转发
        }

        // 普通消息：存库并广播
        const stmt = db.prepare("INSERT INTO messages (user, content, time, type) VALUES (?, ?, ?, ?)");
        stmt.run(name, msgContent, time, msgType);
        stmt.finalize();

        io.emit('chat message', { user: name, text: msgContent, type: msgType, id: socket.id, time: time });
    });

    // --- 🌟 魔法指令处理函数 ---
    function handleCommand(socket, user, cmd) {
        let resultMsg = "";
        
        if (cmd === '/roll') {
            const num = Math.floor(Math.random() * 100) + 1;
            resultMsg = `🎲 ${user} 掷出了骰子：【 ${num} 点 】`;
        } 
        else if (cmd === '/coin') {
            const side = Math.random() > 0.5 ? "正面" : "反面";
            resultMsg = `🪙 ${user} 抛出了硬币：【 ${side} 】`;
        }
        else if (cmd === '/help') {
            // 只有自己能看到帮助
            socket.emit('system', '可用指令: /roll (掷骰子), /coin (抛硬币)');
            return;
        } 
        else {
            socket.emit('system', '❌ 未知指令，输入 /help 查看帮助');
            return;
        }

        // 广播游戏结果 (不存数据库，属于临时互动)
        io.emit('system', resultMsg);
    }

    socket.on('disconnect', () => {
        const name = onlineUsers[socket.id];
        if (name) {
            delete onlineUsers[socket.id];
            io.emit('system', `${name} 下线了`);
            io.emit('update user list', Object.values(onlineUsers));
        }
    });
});

const PORT = process.env.PORT || 3000;
server.listen(PORT, () => { console.log(`服务器运行在端口 ${PORT}`); });

// 防休眠监控 (30秒一次)
const https = require('https');
setInterval(() => {
    const memoryUsage = process.memoryUsage();
    // 只有在有人在线时才打印日志，避免日志太乱
    if(Object.keys(onlineUsers).length > 0) {
        console.log(`[监控] RAM: ${Math.round(memoryUsage.rss / 1024 / 1024)}MB | 在线: ${Object.keys(onlineUsers).length}`);
    }
}, 30000);
"""

# ================= 2. 新版 index.html 代码 =================
index_html_content = r"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <title>WebChat Fun Edition</title>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no, viewport-fit=cover">
    <style>
        /* --- 核心配色变量 --- */
        :root {
            --primary-color: #007AFF;
            --self-bg: #95ec69;
            --bg-color: #f2f2f2;
            --sidebar-bg: #2e3b4e;
            --text-color: #333;
            --bubble-bg: #ffffff;
            --input-bg: #ffffff;
            --border-color: #ddd;
            --header-bg: #ffffff;
        }

        /* 🌙 夜间模式变量覆盖 */
        [data-theme="dark"] {
            --primary-color: #0A84FF;
            --self-bg: #206736;
            --bg-color: #1a1a1a;
            --sidebar-bg: #121212;
            --text-color: #e0e0e0;
            --bubble-bg: #2c2c2c;
            --input-bg: #2c2c2c;
            --border-color: #444;
            --header-bg: #242424;
        }

        * { box-sizing: border-box; outline: none; -webkit-tap-highlight-color: transparent; }
        body { margin: 0; font-family: -apple-system, sans-serif; height: 100dvh; display: flex; background-color: var(--bg-color); color: var(--text-color); overflow: hidden; transition: background 0.3s; }

        /* 登录框 */
        #auth-overlay { position: fixed; top: 0; left: 0; right: 0; bottom: 0; background: rgba(0,0,0,0.6); z-index: 999; display: flex; align-items: center; justify-content: center; backdrop-filter: blur(5px); }
        #auth-box { background: var(--header-bg); padding: 30px; border-radius: 16px; width: 320px; box-shadow: 0 10px 30px rgba(0,0,0,0.3); text-align: center; color: var(--text-color); }
        .auth-input { width: 100%; padding: 12px; margin: 10px 0; border: 1px solid var(--border-color); border-radius: 8px; font-size: 16px; background: var(--input-bg); color: var(--text-color); }
        .auth-btn { width: 100%; padding: 12px; border: none; border-radius: 8px; font-size: 16px; font-weight: bold; cursor: pointer; margin-top: 5px; }
        .btn-primary { background: var(--primary-color); color: white; }
        .btn-secondary { background: transparent; color: var(--primary-color); margin-top: 10px; }

        /* 主布局 */
        #main-app { display: none; width: 100%; height: 100%; display: flex; }
        #sidebar { width: 260px; background-color: var(--sidebar-bg); color: #ecf0f1; display: flex; flex-direction: column; z-index: 2; transition: transform 0.3s; }
        #main { flex: 1; display: flex; flex-direction: column; background: var(--bg-color); width: 100%; position: relative; }

        .sidebar-header { padding: 20px; font-weight: bold; background: rgba(255,255,255,0.05); }
        #user-list { list-style: none; padding: 10px; margin: 0; overflow-y: auto; flex: 1; }
        .user-item { padding: 8px; display: flex; align-items: center; font-size: 0.9rem; color: #bbb; }
        .user-avatar-sm { width: 28px; height: 28px; border-radius: 50%; margin-right: 10px; display: flex; align-items: center; justify-content: center; color: white; font-size: 12px; font-weight: bold; }

        /* 头部 */
        .chat-header { height: 50px; background: var(--header-bg); border-bottom: 1px solid var(--border-color); display: flex; align-items: center; padding: 0 15px; justify-content: space-between; flex-shrink: 0; color: var(--text-color); transition: background 0.3s; }
        .menu-btn { display: none; font-size: 1.5rem; margin-right: 15px; cursor: pointer; }

        /* 消息区 */
        #messages { flex: 1; list-style: none; margin: 0; padding: 15px; overflow-y: auto; display: flex; flex-direction: column; gap: 15px; }
        .message-row { display: flex; align-items: flex-end; max-width: 85%; }
        .right { align-self: flex-end; flex-direction: row-reverse; }
        .left { align-self: flex-start; }
        
        .avatar { width: 36px; height: 36px; border-radius: 6px; display: flex; align-items: center; justify-content: center; color: white; font-weight: bold; flex-shrink: 0; font-size: 14px; box-shadow: 0 2px 4px rgba(0,0,0,0.1); }
        .bubble-container { margin: 0 10px; display: flex; flex-direction: column; }
        .bubble-meta { font-size: 12px; color: #888; margin-bottom: 3px; }
        .right .bubble-meta { text-align: right; }

        .bubble { padding: 10px 14px; border-radius: 8px; font-size: 15px; line-height: 1.4; word-break: break-all; position: relative; box-shadow: 0 1px 2px rgba(0,0,0,0.05); background: var(--bubble-bg); color: var(--text-color); }
        .right .bubble { background: var(--self-bg); color: white; } /* 自己发的消息文字变白 */
        .bubble img { max-width: 100%; max-height: 200px; border-radius: 4px; display: block; }
        
        .system-message { align-self: center; background: rgba(0,0,0,0.1); padding: 4px 12px; border-radius: 20px; font-size: 12px; color: #888; text-align: center; }
        [data-theme="dark"] .system-message { background: rgba(255,255,255,0.15); color: #ccc; }

        /* 底部工具 */
        #input-area { background: var(--header-bg); padding: 8px 10px; padding-bottom: calc(8px + env(safe-area-inset-bottom)); border-top: 1px solid var(--border-color); display: flex; gap: 8px; align-items: center; flex-shrink: 0; transition: background 0.3s; }
        .tool-btn { font-size: 1.4rem; cursor: pointer; background: none; border: none; padding: 0 5px; color: #666; }
        [data-theme="dark"] .tool-btn { color: #aaa; }
        #input { flex: 1; border: 1px solid var(--border-color); padding: 9px 12px; border-radius: 4px; font-size: 16px; background: var(--input-bg); color: var(--text-color); }
        .send-btn { background: var(--primary-color); color: white; border: none; padding: 0 15px; height: 38px; border-radius: 4px; font-weight: bold; cursor: pointer; }

        /* 表情框 */
        #emoji-picker { position: absolute; bottom: 65px; left: 10px; background: var(--header-bg); border: 1px solid var(--border-color); border-radius: 8px; padding: 10px; display: grid; grid-template-columns: repeat(6, 1fr); gap: 5px; box-shadow: 0 5px 15px rgba(0,0,0,0.2); display: none; z-index: 10; max-width: 300px; }
        #emoji-picker.show { display: grid; }
        .emoji-item { font-size: 1.4rem; cursor: pointer; text-align: center; padding: 5px; }

        @media (max-width: 700px) {
            #sidebar { position: absolute; height: 100%; transform: translateX(-100%); width: 75%; box-shadow: 2px 0 10px rgba(0,0,0,0.3); }
            #sidebar.open { transform: translateX(0); }
            .menu-btn { display: block; color: var(--text-color); }
        }
    </style>
</head>
<body>
    <div id="auth-overlay">
        <div id="auth-box">
            <h2 id="auth-title">WebChat</h2>
            <input id="auth-user" class="auth-input" placeholder="账号" autocomplete="off">
            <input id="auth-pass" class="auth-input" type="password" placeholder="密码">
            <div id="auth-error" style="color: #ff4d4f; font-size: 14px; margin-top: 5px;"></div>
            <button class="auth-btn btn-primary" onclick="doLogin()">登 录</button>
            <button class="auth-btn btn-secondary" onclick="switchMode()">注册账号</button>
        </div>
    </div>

    <div id="main-app">
        <div id="sidebar">
            <div class="sidebar-header">
                WebChat V3.0
                <div style="font-size:12px; color:#888; margin-top:5px; font-weight:normal;">输入 /roll 掷骰子</div>
            </div>
            <ul id="user-list"></ul>
        </div>

        <div id="main">
            <div class="chat-header">
                <div style="display:flex; align-items:center;">
                    <div class="menu-btn" onclick="toggleSidebar()">☰</div>
                    <span id="header-title">聊天室</span>
                </div>
                <div style="display: flex; gap: 10px;">
                    <button onclick="toggleTheme()" id="theme-btn" style="background:none; border:none; font-size:1.2rem; cursor:pointer;">🌙</button>
                    <button onclick="doLogout()" style="background:#ff4d4f; color:white; border:none; padding:5px 10px; border-radius:4px; font-size:12px; cursor:pointer;">退出</button>
                </div>
            </div>

            <ul id="messages"></ul>
            
            <div id="emoji-picker"></div>

            <form id="input-area">
                <input type="file" id="file-input" accept="image/*" style="display: none;" />
                <button type="button" class="tool-btn" onclick="document.getElementById('file-input').click()">🖼️</button>
                <button type="button" class="tool-btn" onclick="toggleEmoji()">😀</button>
                <input id="input" autocomplete="off" placeholder="发消息 或输入 /help..." />
                <button class="send-btn">发送</button>
            </form>
        </div>
    </div>

    <script src="/socket.io/socket.io.js"></script>
    <script>
        var socket = io();
        var myName = "";
        var isRegister = false;

        // --- 🌟 夜间模式逻辑 ---
        function toggleTheme() {
            const body = document.body;
            const isDark = body.getAttribute('data-theme') === 'dark';
            const newTheme = isDark ? 'light' : 'dark';
            body.setAttribute('data-theme', newTheme);
            document.getElementById('theme-btn').textContent = isDark ? '🌙' : '☀️';
            localStorage.setItem('theme', newTheme);
        }

        // 初始化：读取本地存储的主题
        window.onload = () => {
            const savedTheme = localStorage.getItem('theme');
            if(savedTheme === 'dark') {
                document.body.setAttribute('data-theme', 'dark');
                document.getElementById('theme-btn').textContent = '☀️';
            }
            const savedUser = localStorage.getItem('chatUser');
            if(savedUser) document.getElementById('auth-user').value = savedUser;
        };

        // --- 登录/注册 ---
        function switchMode() {
            isRegister = !isRegister;
            document.getElementById('auth-title').textContent = isRegister ? "注册" : "登录";
            document.querySelector('.btn-primary').textContent = isRegister ? "注 册" : "登 录";
            document.querySelector('.btn-secondary').textContent = isRegister ? "去登录" : "注册账号";
            document.getElementById('auth-error').textContent = "";
        }

        function doLogin() {
            const u = document.getElementById('auth-user').value.trim();
            const p = document.getElementById('auth-pass').value.trim();
            if(!u || !p) return showErr("请输入账号密码");
            socket.emit(isRegister ? 'register' : 'login', { username: u, password: p });
        }
        function doLogout() { localStorage.removeItem('chatUser'); location.reload(); }
        function showErr(msg) { document.getElementById('auth-error').textContent = msg; }

        socket.on('register_response', res => {
            if(res.success) { alert("注册成功，请登录"); switchMode(); } else showErr(res.msg);
        });

        socket.on('login_response', res => {
            if(res.success) {
                myName = res.username;
                localStorage.setItem('chatUser', myName);
                document.getElementById('auth-overlay').style.display = 'none';
                document.getElementById('main-app').style.display = 'flex';
                document.getElementById('header-title').textContent = `聊天室 (${myName})`;
            } else showErr(res.msg);
        });

        // --- 聊天逻辑 ---
        const messages = document.getElementById('messages');
        const input = document.getElementById('input');

        document.getElementById('input-area').addEventListener('submit', (e) => {
            e.preventDefault();
            if(input.value.trim()) {
                socket.emit('chat message', { msg: input.value, type: 'text' });
                input.value = '';
                input.focus();
            }
        });

        // 图片处理
        document.getElementById('file-input').addEventListener('change', function() {
            if(this.files[0]) sendImg(this.files[0]);
            this.value = '';
        });
        input.addEventListener('paste', (e) => {
            const items = (e.clipboardData || e.originalEvent.clipboardData).items;
            for(let item of items) if(item.kind === 'file') sendImg(item.getAsFile());
        });
        function sendImg(file) {
            if(file.size > 5*1024*1024) return alert("图片太大了");
            const reader = new FileReader();
            reader.onload = (e) => socket.emit('chat message', { msg: e.target.result, type: 'image' });
            reader.readAsDataURL(file);
        }

        // --- 消息渲染 ---
        socket.on('chat message', (data) => {
            const li = document.createElement('li');
            const isMe = data.user === myName;
            li.className = `message-row ${isMe ? 'right' : 'left'}`;
            const color = stringToColor(data.user);
            
            const content = data.type === 'image' 
                ? `<img src="${data.text}" onclick="window.open(this.src)">` 
                : data.text;

            li.innerHTML = `
                <div class="avatar" style="background:${color}">${data.user[0].toUpperCase()}</div>
                <div class="bubble-container">
                    <div class="bubble-meta">${!isMe ? data.user : ''} ${data.time}</div>
                    <div class="bubble">${content}</div>
                </div>
            `;
            messages.appendChild(li);
            requestAnimationFrame(() => messages.scrollTop = messages.scrollHeight);
        });

        socket.on('system', (msg) => {
            const li = document.createElement('li');
            li.className = 'system-message';
            li.textContent = msg;
            messages.appendChild(li);
            messages.scrollTop = messages.scrollHeight;
        });

        // --- 杂项 ---
        function stringToColor(str) {
            let hash = 0;
            for (let i = 0; i < str.length; i++) hash = str.charCodeAt(i) + ((hash << 5) - hash);
            let c = (hash & 0x00FFFFFF).toString(16).toUpperCase();
            return '#' + "00000".substring(0, 6 - c.length) + c;
        }

        socket.on('update user list', users => {
            document.getElementById('user-list').innerHTML = users.map(u => 
                `<li class="user-item"><div class="user-avatar-sm" style="background:${stringToColor(u)}">${u[0].toUpperCase()}</div>${u}</li>`
            ).join('');
        });

        // 表情
        const emojis = ["😀","😂","🤣","😍","👍","👎","🎉","🔥","❤️","💩","🎲","🪙"];
        const picker = document.getElementById('emoji-picker');
        emojis.forEach(e => {
            const s = document.createElement('span'); s.className='emoji-item'; s.textContent=e;
            s.onclick = () => { input.value += e; input.focus(); picker.classList.remove('show'); };
            picker.appendChild(s);
        });
        function toggleEmoji() { picker.classList.toggle('show'); }
        function toggleSidebar() { document.getElementById('sidebar').classList.toggle('open'); }
        document.addEventListener('click', e => {
            if(!e.target.closest('#emoji-picker') && !e.target.closest('.tool-btn')) picker.classList.remove('show');
        });
    </script>
</body>
</html>
"""

def write_file(filename, content):
    try:
        with open(filename, 'w', encoding='utf-8') as f:
            f.write(content)
        print(f"✅ 成功更新文件: {filename}")
    except Exception as e:
        print(f"❌ 写入 {filename} 失败: {e}")
        sys.exit(1)

def run_git():
    print("\n📦 正在执行 Git 推送...")
    try:
        subprocess.run(["git", "add", "."], check=True)
        subprocess.run(["git", "commit", "-m", "auto update: dark mode and commands"], check=True)
        subprocess.run(["git", "push"], check=True)
        print("\n🚀 推送成功！Render 正在部署中...")
    except subprocess.CalledProcessError as e:
        print(f"\n❌ Git 操作失败: {e}")

if __name__ == "__main__":
    print("=== 开始自动更新聊天室 ===")
    
    # 1. 写入 server.js
    write_file("server.js", server_js_content)
    
    # 2. 写入 index.html
    write_file("index.html", index_html_content)
    
    # 3. 推送到 GitHub
    run_git()