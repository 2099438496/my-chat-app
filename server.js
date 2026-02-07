const express = require('express');
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
