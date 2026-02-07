import os
import subprocess
import sys

# ================= 1. 修复后的 server.js (后端) =================
server_js_content = r"""const express = require('express');
const app = express();
const http = require('http');
const server = http.createServer(app);
const { Server } = require("socket.io");
const io = new Server(server, { maxHttpBufferSize: 5e7 });
const sqlite3 = require('sqlite3').verbose();
const bcrypt = require('bcryptjs');

// 初始化数据库
const db = new sqlite3.Database('chat.db');

db.serialize(() => {
    // 强制 username 为主键 (PRIMARY KEY)，确保唯一性
    db.run("CREATE TABLE IF NOT EXISTS users (username TEXT PRIMARY KEY, password TEXT)");
    db.run("CREATE TABLE IF NOT EXISTS messages (id INTEGER PRIMARY KEY AUTOINCREMENT, user TEXT, content TEXT, time TEXT, type TEXT)");
});

app.get('/', (req, res) => { res.sendFile(__dirname + '/index.html'); });

const onlineUsers = {};

io.on('connection', (socket) => {
    
    // --- 注册逻辑 (修复版) ---
    socket.on('register', (data) => {
        const { username, password } = data;
        
        // 1. 先检查是否为空
        if (!username || !password) {
            return socket.emit('register_response', { success: false, msg: '账号密码不能为空' });
        }

        // 2. 尝试插入数据库
        const hash = bcrypt.hashSync(password, 10);
        const stmt = db.prepare("INSERT INTO users (username, password) VALUES (?, ?)");
        
        stmt.run(username, hash, function(err) {
            if (err) {
                // 如果报错包含 UNIQUE constraint，说明用户名已存在
                if (err.message.includes('UNIQUE')) {
                    socket.emit('register_response', { success: false, msg: '该用户名已被占用，请换一个' });
                } else {
                    socket.emit('register_response', { success: false, msg: '注册失败，服务器内部错误' });
                }
            } else {
                socket.emit('register_response', { success: true, msg: '注册成功！请登录' });
            }
        });
        stmt.finalize();
    });

    // --- 登录逻辑 (修复版) ---
    socket.on('login', (data) => {
        const { username, password } = data;
        
        db.get("SELECT * FROM users WHERE username = ?", [username], (err, row) => {
            if (err) {
                return socket.emit('login_response', { success: false, msg: '数据库查询错误' });
            }
            
            // 🌟 关键修复：区分账号不存在和密码错误
            if (!row) {
                // 找不到用户 -> 说明可能是 Render 重启导致数据丢失，或者是新用户
                return socket.emit('login_response', { success: false, msg: '账号不存在 (可能已被重置)，请重新注册' });
            }
            
            if (!bcrypt.compareSync(password, row.password)) {
                return socket.emit('login_response', { success: false, msg: '密码错误' });
            }

            // 登录成功
            onlineUsers[socket.id] = username;
            socket.emit('login_response', { success: true, username: username });
            
            io.emit('system', `${username} 上线了`);
            io.emit('update user list', Object.values(onlineUsers));

            // 加载历史消息
            db.all("SELECT user, content, time, type FROM messages ORDER BY id ASC LIMIT 50", (err, rows) => {
                if (rows) rows.forEach(r => socket.emit('chat message', { user: r.user, text: r.content, type: r.type || 'text', time: r.time }));
            });
        });
    });

    // --- 消息处理 ---
    socket.on('chat message', (data) => {
        const name = onlineUsers[socket.id];
        if (!name) return;

        const time = new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
        const msgContent = typeof data === 'string' ? data : data.msg;
        const msgType = data.type || 'text';

        // 指令处理
        if (msgType === 'text' && msgContent.startsWith('/')) {
            handleCommand(socket, name, msgContent);
            return;
        }

        const stmt = db.prepare("INSERT INTO messages (user, content, time, type) VALUES (?, ?, ?, ?)");
        stmt.run(name, msgContent, time, msgType);
        stmt.finalize();

        io.emit('chat message', { user: name, text: msgContent, type: msgType, id: socket.id, time: time });
    });

    function handleCommand(socket, user, cmd) {
        let resultMsg = "";
        if (cmd === '/roll') resultMsg = `🎲 ${user} 掷出了：${Math.floor(Math.random()*100)+1} 点`;
        else if (cmd === '/coin') resultMsg = `🪙 ${user} 抛出了：${Math.random()>0.5?"正面":"反面"}`;
        else if (cmd === '/help') { socket.emit('system', '指令: /roll, /coin'); return; }
        else { socket.emit('system', '❌ 未知指令'); return; }
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
server.listen(PORT, () => { console.log(`Server running on port ${PORT}`); });
"""

# ================= 2. 修复后的 index.html (前端) =================
index_html_content = r"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <title>WebChat Pro</title>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no, viewport-fit=cover">
    <style>
        :root { --primary:#007AFF; --bg:#f2f2f2; --text:#333; --bubble:#fff; --self:#95ec69; --sidebar:#2e3b4e; --input-bg:#fff; --header:#fff; }
        [data-theme="dark"] { --primary:#0A84FF; --bg:#1a1a1a; --text:#e0e0e0; --bubble:#2c2c2c; --self:#206736; --sidebar:#121212; --input-bg:#2c2c2c; --header:#242424; }
        
        * { box-sizing: border-box; -webkit-tap-highlight-color: transparent; }
        body { margin: 0; font-family: sans-serif; height: 100dvh; display: flex; background: var(--bg); color: var(--text); overflow: hidden; }

        /* 登录弹窗 */
        #auth-overlay { position: fixed; inset: 0; background: rgba(0,0,0,0.6); z-index: 999; display: flex; align-items: center; justify-content: center; backdrop-filter: blur(5px); }
        #auth-box { background: var(--header); padding: 30px; border-radius: 16px; width: 320px; text-align: center; box-shadow: 0 10px 40px rgba(0,0,0,0.3); }
        .auth-input { width: 100%; padding: 12px; margin: 10px 0; border: 1px solid #ddd; border-radius: 8px; font-size: 16px; background: var(--input-bg); color: var(--text); }
        .auth-btn { width: 100%; padding: 12px; border: none; border-radius: 8px; font-size: 16px; font-weight: bold; cursor: pointer; margin-top: 5px; }
        .btn-primary { background: var(--primary); color: white; }
        .btn-link { background: none; color: var(--primary); margin-top: 15px; font-size: 14px; text-decoration: underline; }
        
        /* 布局 */
        #main-app { display: none; width: 100%; height: 100%; }
        #sidebar { width: 260px; background: var(--sidebar); color: #ccc; display: flex; flex-direction: column; }
        #main { flex: 1; display: flex; flex-direction: column; position: relative; }
        
        .header { height: 50px; background: var(--header); border-bottom: 1px solid #ddd; display: flex; align-items: center; justify-content: space-between; padding: 0 15px; }
        #messages { flex: 1; overflow-y: auto; padding: 15px; display: flex; flex-direction: column; gap: 15px; list-style: none; margin: 0; }
        
        .msg-row { display: flex; align-items: flex-end; max-width: 85%; }
        .msg-row.right { align-self: flex-end; flex-direction: row-reverse; }
        .avatar { width: 36px; height: 36px; border-radius: 6px; display: flex; align-items: center; justify-content: center; background: #ccc; color: #fff; flex-shrink: 0; font-weight: bold; }
        .bubble { margin: 0 10px; padding: 10px 14px; border-radius: 8px; background: var(--bubble); box-shadow: 0 1px 2px rgba(0,0,0,0.1); word-break: break-all; }
        .msg-row.right .bubble { background: var(--self); color: #fff; }
        .bubble img { max-width: 100%; border-radius: 4px; }
        .meta { font-size: 12px; color: #888; margin-bottom: 2px; }
        .msg-row.right .meta { text-align: right; }
        
        #input-area { background: var(--header); padding: 10px; display: flex; gap: 10px; align-items: center; border-top: 1px solid #ddd; }
        #input { flex: 1; padding: 10px; border: 1px solid #ddd; border-radius: 4px; background: var(--input-bg); color: var(--text); }
        .icon-btn { background: none; border: none; font-size: 1.4rem; cursor: pointer; padding: 0 5px; }

        @media(max-width: 700px) { #sidebar { display: none; } }
    </style>
</head>
<body>
    <div id="auth-overlay">
        <div id="auth-box">
            <h2 id="auth-title">欢迎回来</h2>
            <div id="auth-error" style="color: #ff4d4f; font-size: 14px; margin-bottom: 10px; min-height: 20px;"></div>
            <input id="auth-user" class="auth-input" placeholder="用户名" autocomplete="off">
            <input id="auth-pass" class="auth-input" type="password" placeholder="密码">
            
            <button id="btn-action" class="auth-btn btn-primary" onclick="submitAuth()">登 录</button>
            
            <button id="btn-switch" class="auth-btn btn-link" onclick="toggleMode()">没有账号？去注册</button>
        </div>
    </div>

    <div id="main-app">
        <div id="sidebar">
            <div style="padding:20px; font-weight:bold;">在线用户</div>
            <ul id="user-list" style="list-style:none; padding:10px; margin:0;"></ul>
        </div>
        <div id="main">
            <div class="header">
                <span id="chat-title">聊天室</span>
                <div>
                    <button onclick="toggleTheme()" style="background:none; border:none; font-size:1.2rem; cursor:pointer;">🌗</button>
                    <button onclick="logout()" style="background:#ff4d4f; color:fff; border:none; padding:5px 10px; border-radius:4px; color:white; margin-left:10px;">退出</button>
                </div>
            </div>
            <ul id="messages"></ul>
            <form id="input-area">
                <input type="file" id="file-input" hidden accept="image/*">
                <button type="button" class="icon-btn" onclick="document.getElementById('file-input').click()">🖼️</button>
                <input id="input" autocomplete="off" placeholder="说点什么... (输入 /roll 掷骰子)">
                <button class="auth-btn btn-primary" style="width:auto; padding:0 20px;">发送</button>
            </form>
        </div>
    </div>

    <script src="/socket.io/socket.io.js"></script>
    <script>
        const socket = io();
        let isRegisterMode = false; // 默认是登录模式
        let myName = "";

        // --- 初始化：检查本地缓存 ---
        window.onload = () => {
            const savedTheme = localStorage.getItem('theme');
            if (savedTheme === 'dark') document.body.setAttribute('data-theme', 'dark');

            const savedUser = localStorage.getItem('chatUser');
            if (savedUser) {
                // 如果有缓存，自动填入用户名，并保持在登录模式
                document.getElementById('auth-user').value = savedUser;
                document.getElementById('auth-title').textContent = "欢迎回来 " + savedUser;
            } else {
                // 没有缓存，可能是新用户，但不自动切换，等待用户选择
                document.getElementById('auth-title').textContent = "WebChat 登录";
            }
        };

        function toggleMode() {
            isRegisterMode = !isRegisterMode;
            const title = document.getElementById('auth-title');
            const btn = document.getElementById('btn-action');
            const switchBtn = document.getElementById('btn-switch');
            const err = document.getElementById('auth-error');
            
            err.textContent = ""; // 清空报错

            if (isRegisterMode) {
                title.textContent = "创建新账号";
                btn.textContent = "注 册";
                switchBtn.textContent = "已有账号？去登录";
            } else {
                title.textContent = "WebChat 登录";
                btn.textContent = "登 录";
                switchBtn.textContent = "没有账号？去注册";
            }
        }

        function submitAuth() {
            const u = document.getElementById('auth-user').value.trim();
            const p = document.getElementById('auth-pass').value.trim();
            if (!u || !p) return showErr("账号和密码不能为空");

            const event = isRegisterMode ? 'register' : 'login';
            socket.emit(event, { username: u, password: p });
        }

        function showErr(msg) {
            const err = document.getElementById('auth-error');
            err.textContent = msg;
            // 简单的抖动动画
            err.style.transform = "translateX(5px)";
            setTimeout(() => err.style.transform = "translateX(0)", 100);
        }

        socket.on('register_response', res => {
            if (res.success) {
                alert("✅ 注册成功！现在请直接登录。");
                toggleMode(); // 切换回登录界面
                // 自动填入刚才注册的密码，方便登录
                document.getElementById('auth-pass').value = ""; 
            } else {
                showErr(res.msg);
            }
        });

        socket.on('login_response', res => {
            if (res.success) {
                myName = res.username;
                localStorage.setItem('chatUser', myName); // 记住用户名
                document.getElementById('auth-overlay').style.display = 'none';
                document.getElementById('main-app').style.display = 'flex';
                document.getElementById('chat-title').textContent = `聊天室 (${myName})`;
            } else {
                showErr(res.msg); // 显示详细错误（如账号不存在）
            }
        });

        function logout() {
            localStorage.removeItem('chatUser');
            location.reload();
        }

        function toggleTheme() {
            const isDark = document.body.getAttribute('data-theme') === 'dark';
            const newTheme = isDark ? 'light' : 'dark';
            document.body.setAttribute('data-theme', newTheme);
            localStorage.setItem('theme', newTheme);
        }

        // --- 聊天核心 ---
        const form = document.getElementById('input-area');
        const input = document.getElementById('input');
        const msgs = document.getElementById('messages');

        form.addEventListener('submit', (e) => {
            e.preventDefault();
            if (input.value) {
                socket.emit('chat message', { msg: input.value, type: 'text' });
                input.value = '';
            }
        });

        document.getElementById('file-input').addEventListener('change', function() {
            if (this.files[0]) {
                const reader = new FileReader();
                reader.onload = e => socket.emit('chat message', { msg: e.target.result, type: 'image' });
                reader.readAsDataURL(this.files[0]);
                this.value = '';
            }
        });

        socket.on('chat message', data => {
            const li = document.createElement('li');
            const isMe = data.user === myName;
            li.className = `msg-row ${isMe ? 'right' : 'left'}`;
            li.innerHTML = `
                <div class="avatar">${data.user[0].toUpperCase()}</div>
                <div>
                    <div class="meta">${!isMe ? data.user : ''} ${data.time}</div>
                    <div class="bubble">
                        ${data.type==='image' ? `<img src="${data.text}">` : data.text}
                    </div>
                </div>`;
            msgs.appendChild(li);
            msgs.scrollTop = msgs.scrollHeight;
        });

        socket.on('system', msg => {
            const li = document.createElement('li');
            li.style.textAlign='center'; li.style.fontSize='12px'; li.style.color='#888';
            li.textContent = msg;
            msgs.appendChild(li);
        });
        
        socket.on('update user list', list => {
            document.getElementById('user-list').innerHTML = list.map(u => `<li>👤 ${u}</li>`).join('');
        });
    </script>
</body>
</html>
"""

def write_file(filename, content):
    with open(filename, 'w', encoding='utf-8') as f:
        f.write(content)
    print(f"✅ 更新文件: {filename}")

if __name__ == "__main__":
    write_file("server.js", server_js_content)
    write_file("index.html", index_html_content)
    
    print("\n📦 执行 Git 提交...")
    os.system('git add .')
    os.system('git commit -m "fix login logic and unique account check"')
    os.system('git push')
    print("\n🚀 部署完成！请等待 Render 更新（约1分钟）。")