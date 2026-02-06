const express = require('express');
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
