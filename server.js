const express = require('express');
const app = express();
const http = require('http');
const server = http.createServer(app);
const { Server } = require("socket.io");
// 修改点 1：允许最大 10MB 的数据包（用于发图片）
const io = new Server(server, {
  maxHttpBufferSize: 1e7 
});
const sqlite3 = require('sqlite3').verbose();

// --- 数据库初始化 ---
const db = new sqlite3.Database('chat.db');
db.serialize(() => {
  // 我们增加了一个 type 字段来区分是 'text' 还是 'image'
  // 为了兼容老数据，如果列不存在可能会报错，所以这里用简单的容错写法
  db.run("CREATE TABLE IF NOT EXISTS messages (id INTEGER PRIMARY KEY AUTOINCREMENT, user TEXT, content TEXT, time TEXT, type TEXT)");
  
  // 尝试给旧表添加 type 列（如果已经存在会忽略错误）
  db.run("ALTER TABLE messages ADD COLUMN type TEXT", (err) => {});
});

app.get('/', (req, res) => {
  res.sendFile(__dirname + '/index.html');
});

const users = {};

io.on('connection', (socket) => {
  
  socket.on('join', (name) => {
    users[socket.id] = name;
    io.emit('system', `${name} 加入了聊天室`);
    io.emit('update user list', Object.values(users));

    // 加载历史消息
    db.all("SELECT user, content, time, type FROM messages ORDER BY id ASC LIMIT 50", (err, rows) => {
      if (err) return;
      rows.forEach((row) => {
        socket.emit('chat message', { 
            user: row.user, 
            text: row.content, 
            type: row.type || 'text', // 兼容老数据
            time: row.time,
            id: 'history' 
        });
      });
      socket.emit('system', '--- 以上是历史消息 ---');
    });
  });

  // 接收消息 (支持文本和图片)
  socket.on('chat message', (data) => {
    // data 结构: { msg: '...', type: 'text'/'image' }
    const name = users[socket.id] || '匿名';
    const time = new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
    const msgContent = typeof data === 'string' ? data : data.msg; // 兼容旧代码
    const msgType = data.type || 'text';

    const stmt = db.prepare("INSERT INTO messages (user, content, time, type) VALUES (?, ?, ?, ?)");
    stmt.run(name, msgContent, time, msgType);
    stmt.finalize();

    io.emit('chat message', { 
      user: name, 
      text: msgContent, 
      type: msgType,
      id: socket.id,
      time: time 
    });
  });

  socket.on('typing', () => {
    const name = users[socket.id];
    socket.broadcast.emit('typing', name);
  });

  socket.on('stop typing', () => {
    socket.broadcast.emit('stop typing');
  });

  socket.on('disconnect', () => {
    const name = users[socket.id];
    if (name) {
      delete users[socket.id];
      io.emit('system', `${name} 离开了聊天室`);
      io.emit('update user list', Object.values(users));
    }
  });
});

const PORT = process.env.PORT || 3000;
server.listen(PORT, () => {
  console.log(`服务器运行在端口 ${PORT}`);
});

/* --- 24小时防休眠 (请替换为你自己的 Render 网址) --- */
const https = require('https');
setInterval(() => {
    // const myUrl = 'https://你的项目名.onrender.com'; 
    // https.get(myUrl, (res) => console.log('Keep-alive:', res.statusCode)).on('error', (e) => {});
}, 14 * 60 * 1000);