const express = require('express');
const app = express();
const http = require('http');
const server = http.createServer(app);
const { Server } = require("socket.io");
const io = new Server(server, { maxHttpBufferSize: 1e7 });
const sqlite3 = require('sqlite3').verbose();
const bcrypt = require('bcryptjs'); // 引入加密库

// --- 数据库初始化 ---
const db = new sqlite3.Database('chat.db');

db.serialize(() => {
  // 1. 消息表
  db.run("CREATE TABLE IF NOT EXISTS messages (id INTEGER PRIMARY KEY AUTOINCREMENT, user TEXT, content TEXT, time TEXT, type TEXT)");
  
  // 2. 用户表 (新增：存账号和加密后的密码)
  db.run("CREATE TABLE IF NOT EXISTS users (username TEXT PRIMARY KEY, password TEXT)");
});

app.get('/', (req, res) => {
  res.sendFile(__dirname + '/index.html');
});

const onlineUsers = {}; // 记录 socketID -> 用户名

io.on('connection', (socket) => {
  
  // --- A. 用户注册 ---
  socket.on('register', (data) => {
    const { username, password } = data;
    // 先查用户是否存在
    db.get("SELECT * FROM users WHERE username = ?", [username], (err, row) => {
      if (row) {
        socket.emit('register_response', { success: false, msg: '用户名已存在' });
      } else {
        // 加密密码
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

  // --- B. 用户登录 ---
  socket.on('login', (data) => {
    const { username, password } = data;
    db.get("SELECT * FROM users WHERE username = ?", [username], (err, row) => {
      if (!row) {
        socket.emit('login_response', { success: false, msg: '用户不存在' });
      } else {
        // 验证密码
        if (bcrypt.compareSync(password, row.password)) {
          // 登录成功！
          onlineUsers[socket.id] = username;
          socket.emit('login_response', { success: true, username: username });
          
          // 广播进入消息
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
            }
          });
        } else {
          socket.emit('login_response', { success: false, msg: '密码错误' });
        }
      }
    });
  });

  // --- C. 聊天消息 ---
  socket.on('chat message', (data) => {
    const name = onlineUsers[socket.id];
    if (!name) return; // 未登录不能发言

    const time = new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
    const msgContent = typeof data === 'string' ? data : data.msg;
    const msgType = data.type || 'text';

    const stmt = db.prepare("INSERT INTO messages (user, content, time, type) VALUES (?, ?, ?, ?)");
    stmt.run(name, msgContent, time, msgType);
    stmt.finalize();

    io.emit('chat message', { user: name, text: msgContent, type: msgType, id: socket.id, time: time });
  });

  // --- D. 其他事件 ---
  socket.on('typing', () => {
    const name = onlineUsers[socket.id];
    if(name) socket.broadcast.emit('typing', name);
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

// 防休眠 (替换你的网址)
const https = require('https');
setInterval(() => {
    // const myUrl = 'https://你的项目.onrender.com';
    // https.get(myUrl).on('error', ()=>{});
}, 14 * 60 * 1000);