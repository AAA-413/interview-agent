import { request } from './request';

export interface LoginRequest {
  username: string;
  password: string;
}

export interface RegisterRequest {
  username: string;
  email: string;
  password: string;
  full_name?: string;
}

export interface UserInfo {
  id: number;
  username: string;
  email: string;
  full_name?: string;
  is_active: boolean;
  is_superuser: boolean;
  created_at: string;
  last_login?: string;
}

export interface LoginResponse {
  access_token: string;
  token_type: string;
  expires_in: number;
}

export const authApi = {
  // 登录
  login: (data: LoginRequest) => {
    return request.post<LoginResponse>('/api/auth/login', data);
  },

  // 注册
  register: (data: RegisterRequest) => {
    return request.post<UserInfo>('/api/auth/register', data);
  },

  // 获取当前用户信息
  getCurrentUser: () => {
    return request.get<UserInfo>('/api/auth/me');
  },

  // 登出
  logout: () => {
    return request.post('/api/auth/logout');
  },
};
