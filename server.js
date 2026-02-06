const express = require('express');
const app = express();
const http = require('http');
const server = http.createServer(app);
const { Server } = require("socket.io");
const io = new Server(server);
const sqlite3 = require('sqlite3').verbose();

// --- 数据库初始化 ---
// 创建或打开一个名为 chat.db 的本地文件数据库
const db = new sqlite3.Database('chat.db');

// 只有当表不存在时才创建表（防止重复创建）
db.serialize(() => {
  db.run("CREATE TABLE IF NOT EXISTS messages (id INTEGER PRIMARY KEY AUTOINCREMENT, user TEXT, content TEXT, time TEXT)");
});

app.get('/', (req, res) => {
  res.sendFile(__dirname + '/index.html');
});

const users = {};

io.on('connection', (socket) => {
  
  // 1. 用户加入
  socket.on('join', (name) => {
    users[socket.id] = name;
    io.emit('system', `${name} 加入了聊天室`);
    io.emit('update user list', Object.values(users));

    // --- 关键代码：加载历史消息 ---
    // 从数据库查询最近的 50 条消息
    db.all("SELECT user, content, time FROM messages ORDER BY id ASC LIMIT 50", (err, rows) => {
      if (err) return;
      
      // 循环每一条历史记录，只发给当前连进来的这个用户 (socket.emit)
      // 我们伪造成 'chat message' 事件，这样前端代码完全不用改就能显示历史记录！
      rows.forEach((row) => {
        socket.emit('chat message', { 
            user: row.user, 
            text: row.content, 
            time: row.time,
            id: 'history' // 标记为历史消息，避免前端判断气泡左右时出错
        });
      });
      
      // 发一条系统提示，告诉用户这是历史记录
      socket.emit('system', '--- 以上是历史消息 ---');
    });
  });

  // 2. 收到消息
  socket.on('chat message', (msg) => {
    const name = users[socket.id] || '匿名';
    const time = new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });

    // --- 关键代码：存入数据库 ---
    // 使用占位符 (?) 防止 SQL 注入攻击
    const stmt = db.prepare("INSERT INTO messages (user, content, time) VALUES (?, ?, ?)");
    stmt.run(name, msg, time);
    stmt.finalize();

    // 广播给所有人
    io.emit('chat message', { 
      user: name, 
      text: msg, 
      id: socket.id,
      time: time 
    });
  });

  // 3. 正在输入
  socket.on('typing', () => {
    const name = users[socket.id];
    socket.broadcast.emit('typing', name);
  });

  socket.on('stop typing', () => {
    socket.broadcast.emit('stop typing');
  });

  // 4. 断开连接
  socket.on('disconnect', () => {
    const name = users[socket.id];
    if (name) {
      delete users[socket.id];
      io.emit('system', `${name} 离开了聊天室`);
      io.emit('update user list', Object.values(users));
    }
  });
});

const PORT = process.env.PORT || 3000; // 如果云端有分配端口就用云端的，没有就用3000
server.listen(PORT, () => {
  console.log(`服务器运行在端口 ${PORT}`);
});