const express = require('express');
const app = express();
const http = require('http');
const server = http.createServer(app);
const { Server } = require("socket.io");
// 允许最大 50MB 的图片传输
const io = new Server(server, { maxHttpBufferSize: 5e7 });
const sqlite3 = require('sqlite3').verbose();
const bcrypt = require('bcryptjs');

// --- 数据库初始化 ---
const db = new sqlite3.Database('chat.db');

db.serialize(() => {
    // 1. 用户表
    db.run("CREATE TABLE IF NOT EXISTS users (username TEXT PRIMARY KEY, password TEXT)");
    // 2. 消息表 (包含 type 字段用于区分图片)
    db.run("CREATE TABLE IF NOT EXISTS messages (id INTEGER PRIMARY KEY AUTOINCREMENT, user TEXT, content TEXT, time TEXT, type TEXT)");
    // 尝试修补旧表 (防止旧数据库没有 type 字段报错)
    db.run("ALTER TABLE messages ADD COLUMN type TEXT", (err) => {});
});

app.get('/', (req, res) => {
    res.sendFile(__dirname + '/index.html');
});

const onlineUsers = {}; // 记录 socket.id -> 用户名

io.on('connection', (socket) => {
    
    // --- 1. 注册 ---
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
                    else socket.emit('register_response', { success: true, msg: '注册成功，请登录' });
                });
                stmt.finalize();
            }
        });
    });

    // --- 2. 登录 ---
    socket.on('login', (data) => {
        const { username, password } = data;
        db.get("SELECT * FROM users WHERE username = ?", [username], (err, row) => {
            if (!row) {
                socket.emit('login_response', { success: false, msg: '用户不存在' });
            } else {
                if (bcrypt.compareSync(password, row.password)) {
                    // 登录成功
                    onlineUsers[socket.id] = username;
                    socket.emit('login_response', { success: true, username: username });
                    
                    // 广播上线
                    io.emit('system', `${username} 上线了`);
                    io.emit('update user list', Object.values(onlineUsers));

                    // 加载历史消息
                    db.all("SELECT user, content, time, type FROM messages ORDER BY id ASC LIMIT 50", (err, rows) => {
                        if (rows) {
                            rows.forEach((r) => {
                                socket.emit('chat message', { 
                                    user: r.user, text: r.content, type: r.type || 'text', time: r.time, id: 'history' 
                                });
                            });
                            socket.emit('system', '--- 以上是历史消息 ---');
                        }
                    });
                } else {
                    socket.emit('login_response', { success: false, msg: '密码错误' });
                }
            }
        });
    });

    // --- 3. 处理消息 (文本+图片) ---
    socket.on('chat message', (data) => {
        const name = onlineUsers[socket.id];
        if (!name) return;

        const time = new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
        // 兼容处理：data 可能是字符串(旧版)也可能是对象(新版)
        const msgContent = typeof data === 'string' ? data : data.msg;
        const msgType = data.type || 'text';

        const stmt = db.prepare("INSERT INTO messages (user, content, time, type) VALUES (?, ?, ?, ?)");
        stmt.run(name, msgContent, time, msgType);
        stmt.finalize();

        io.emit('chat message', { 
            user: name, text: msgContent, type: msgType, id: socket.id, time: time 
        });
    });

    // --- 4. 其他杂项 ---
    socket.on('typing', () => {
        const name = onlineUsers[socket.id];
        if (name) socket.broadcast.emit('typing', name);
    });
    
    socket.on('stop typing', () => socket.broadcast.emit('stop typing'));

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

// 防休眠
const https = require('https');
setInterval(() => {
    // 替换你的 render 网址
    // const myUrl = 'https://xxxx.onrender.com';
    // https.get(myUrl).on('error', ()=>{});
}, 14 * 60 * 1000);
/* --- 服务器性能监控 --- */
setInterval(() => {
    const memoryUsage = process.memoryUsage();
    const ramUsed = Math.round(memoryUsage.rss / 1024 / 1024); 
    const connections = Object.keys(onlineUsers).length; 

    // 只在控制台输出，不再刷屏
    // 改为 60000 (30秒) 甚至 60000 (1分钟)
    console.log(`[系统监控] 内存: ${ramUsed} MB | 在线: ${connections}`);
}, 30000);