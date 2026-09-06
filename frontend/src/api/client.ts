import axios from 'axios';

const client = axios.create({
  baseURL: '/api/admin',
  withCredentials: true,
  headers: { 'Content-Type': 'application/json' },
});

// 请求拦截：自动附加 CSRF Token
client.interceptors.request.use((config) => {
  const token = localStorage.getItem('csrf_token');
  if (token && config.method !== 'get') {
    config.headers['X-CSRF-Token'] = token;
  }
  return config;
});

// 响应拦截：未认证时跳转登录
client.interceptors.response.use(
  (res) => res,
  (err) => {
    if (err.response?.status === 401) {
      localStorage.removeItem('csrf_token');
      const path = window.location.pathname;
      // 登录页路由挂在 /admin basename 下，避免跳到不带前缀的根路径
      if (path !== '/admin/login') {
        window.location.href = '/admin/login';
      }
    }
    return Promise.reject(err);
  },
);

export default client;
