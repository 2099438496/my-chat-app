const express = require('express');
const app = express();
const http = require('http');
const server = http.createServer(app);
const { Server } = require("socket.io");
const io = new Server(server, { maxHttpBufferSize: 1e7 });
const bcrypt = require('bcryptjs');

// --- 数据库切换逻辑 ---
// 如果有 DATABASE_URL 环境变量，就用 PostgreSQL，否则用本地内存(仅测试用)
const { Pool } = require('pg');
const isProduction = process.env.NODE_ENV === 'production' || process.env.DATABASE_URL;

// 配置 PG 连接池
const pool = isProduction ? new Pool({
  connectionString: process.env.DATABASE_URL,
  ssl: { rejectUnauthorized: false } // Render 要求 SSL
}) : null;

// 本地开发时的临时数据库 (如果没配 PG)
const localDB = { users: {}, messages: [] };

// --- 初始化表结构 (PostgreSQL) ---
if (isProduction) {
  const initSQL = `
    CREATE TABLE IF NOT EXISTS users (
      username VARCHAR(50) PRIMARY KEY,
      password VARCHAR(100)
    );
    CREATE TABLE IF NOT EXISTS messages (
      id SERIAL PRIMARY KEY,
      username VARCHAR(50),
      content TEXT,
      time VARCHAR(20),
      type VARCHAR(10)
    );
  `;
  pool.query(initSQL).catch(err => console.error("DB Init Error:", err));
}

app.get('/', (req, res) => {
  res.sendFile(__dirname + '/index.html');
});

const onlineUsers = {};

io.on('connection', (socket) => {

  // --- 辅助函数：执行 SQL ---
  async function query(text, params) {
    if (isProduction) return await pool.query(text, params);
    return null; // 本地模式暂略
  }

  // --- A. 注册 ---
  socket.on('register', async (data) => {
    const { username, password } = data;
    try {
      // 查重
      const check = await query("SELECT * FROM users WHERE username = $1", [username]);
      if (check && check.rows.length > 0) {
        socket.emit('register_response', { success: false, msg: '用户名已存在' });
      } else {
        const hash = bcrypt.hashSync(password, 10);
        await query("INSERT INTO users (username, password) VALUES ($1, $2)", [username, hash]);
        socket.emit('register_response', { success: true, msg: '注册成功' });
      }
    } catch (e) {
      console.error(e);
      socket.emit('register_response', { success: false, msg: '注册出错' });
    }
  });

  // --- B. 登录 ---
  socket.on('login', async (data) => {
    const { username, password } = data;
    try {
      const res = await query("SELECT * FROM users WHERE username = $1", [username]);
      if (res && res.rows.length > 0) {
        const user = res.rows[0];
        if (bcrypt.compareSync(password, user.password)) {
          onlineUsers[socket.id] = username;
          socket.emit('login_response', { success: true, username: username });
          
          io.emit('system', `${username} 上线了`);
          io.emit('update user list', Object.values(onlineUsers));

          // 加载历史消息
          const history = await query("SELECT * FROM messages ORDER BY id ASC LIMIT 50");
          history.rows.forEach(row => {
            socket.emit('chat message', {
              user: row.username, text: row.content, type: row.type || 'text', time: row.time, id: 'history'
            });
          });
        } else {
          socket.emit('login_response', { success: false, msg: '密码错误' });
        }
      } else {
        socket.emit('login_response', { success: false, msg: '用户不存在' });
      }
    } catch (e) {
      console.error(e);
      socket.emit('login_response', { success: false, msg: '登录出错' });
    }
  });

  // --- C. 发消息 ---
  socket.on('chat message', async (data) => {
    const name = onlineUsers[socket.id];
    if (!name) return;

    const time = new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
    const msgContent = typeof data === 'string' ? data : data.msg;
    const msgType = data.type || 'text';

    // 存入云数据库
    try {
      await query("INSERT INTO messages (username, content, time, type) VALUES ($1, $2, $3, $4)", 
        [name, msgContent, time, msgType]);
    } catch(e) { console.error(e); }

    io.emit('chat message', { user: name, text: msgContent, type: msgType, id: socket.id, time: time });
  });

  // --- D. 其他 ---
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

// 防休眠
const https = require('https');
setInterval(() => {
    // const myUrl = 'https://你的项目.onrender.com';
    // https.get(myUrl).on('error', ()=>{});
}, 14 * 60 * 1000);