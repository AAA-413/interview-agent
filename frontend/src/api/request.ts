import axios, { AxiosInstance, AxiosRequestConfig } from 'axios';

interface Result<T = unknown> {
  code: number;
  message: string;
  data: T;
}

const rawApiBaseUrl = import.meta.env.VITE_API_BASE_URL?.trim();
const apiBaseUrl = rawApiBaseUrl ? rawApiBaseUrl.replace(/\/+$/, '') : undefined;

const instance: AxiosInstance = axios.create({
  baseURL: apiBaseUrl,
  timeout: 60000,
});

export function apiUrl(path: string): string {
  if (!apiBaseUrl) return path;
  const normalizedPath = path.startsWith('/') ? path : `/${path}`;
  return `${apiBaseUrl}${normalizedPath}`;
}

// 请求拦截器：添加 token
instance.interceptors.request.use(
  (config) => {
    const token = localStorage.getItem('access_token');
    if (token) {
      config.headers.Authorization = `Bearer ${token}`;
    }
    return config;
  },
  (error) => {
    return Promise.reject(error);
  }
);

// 响应拦截器：处理 401 未授权
instance.interceptors.response.use(
  (response) => {
    const result = response.data as Result;

    if (result && typeof result === 'object' && 'code' in result) {
      if (result.code === 0) {
        response.data = result.data;
        return response;
      }
      return Promise.reject(new Error(result.message || '请求失败'));
    }

    return response;
  },
  (error) => {
    if (error.response) {
      const { data, status } = error.response;
      if (data && typeof data === 'object' && 'code' in data && 'message' in data) {
        const result = data as Result;
        return Promise.reject(new Error(result.message || '请求失败'));
      }

      // HTTP 状态码友好提示
      if (status === 401) {
        localStorage.removeItem('access_token');
        localStorage.removeItem('token_type');
        window.location.href = '/login';
        return Promise.reject(new Error('登录已过期，请重新登录'));
      }
      if (status === 404) {
        return Promise.reject(new Error('请求的资源不存在'));
      }
      if (status === 500) {
        return Promise.reject(new Error('服务器错误，请稍后重试'));
      }
      if (status === 503) {
        return Promise.reject(new Error('服务暂时不可用，请稍后重试'));
      }

      return Promise.reject(new Error('请求失败，请重试'));
    }

    const config = error.config;
    const isUpload = config && (
      config.url?.includes('/upload') ||
      config.headers?.['Content-Type']?.toString().includes('multipart')
    );

    // 超时错误
    if (error.code === 'ECONNABORTED' || error.message?.includes('timeout')) {
      if (isUpload) {
        return Promise.reject(new Error('上传超时（5分钟），文件可能过大或网络较慢，请重试'));
      }
      return Promise.reject(new Error('请求超时（60秒），请检查网络或稍后重试'));
    }

    // 上传错误
    if (isUpload) {
      return Promise.reject(new Error('上传失败，可能是网络中断或文件过大，请重试'));
    }

    // 网络错误
    return Promise.reject(new Error('网络连接失败，请检查网络'));
  }
);

export const request = {
  get<T>(url: string, config?: AxiosRequestConfig): Promise<T> {
    return instance.get(url, config).then(res => res.data);
  },

  post<T>(url: string, data?: unknown, config?: AxiosRequestConfig): Promise<T> {
    return instance.post(url, data, config).then(res => res.data);
  },

  put<T>(url: string, data?: unknown, config?: AxiosRequestConfig): Promise<T> {
    return instance.put(url, data, config).then(res => res.data);
  },

  delete<T>(url: string, config?: AxiosRequestConfig): Promise<T> {
    return instance.delete(url, config).then(res => res.data);
  },

  upload<T>(url: string, formData: FormData, config?: AxiosRequestConfig): Promise<T> {
    return instance.post(url, formData, {
      timeout: 300000,
      headers: { 'Content-Type': 'multipart/form-data' },
      ...config,
    }).then(res => res.data);
  },

  getInstance(): AxiosInstance {
    return instance;
  },
};

export function getErrorMessage(error: unknown): string {
  if (error instanceof Error) {
    return error.message;
  }
  return '未知错误';
}
