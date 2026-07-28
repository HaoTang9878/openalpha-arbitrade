/**
 * WebSocket Hook
 *
 * 管理与后端的 WebSocket 长连接，自动重连（指数退避），
 * 接收实时推送消息并分发到 Zustand store。
 * 断线时自动启动 REST 兜底轮询。
 */

import { useEffect, useRef, useCallback } from 'react';
import { getWsUrl } from '../api/client';
import { useStore } from '../store/useStore';
import type { WSMessage, SystemStatus, PriceSnapshot, ArbitrageOpportunity, TradeResult, LogEntry } from '../types';

/** 重连初始延迟（毫秒） */
const RECONNECT_BASE_DELAY = 1000;
/** 重连最大延迟（毫秒） */
const RECONNECT_MAX_DELAY = 30000;
/** 心跳间隔（毫秒） */
const HEARTBEAT_INTERVAL = 30000;

export function useWebSocket() {
  const wsRef = useRef<WebSocket | null>(null);
  const reconnectDelay = useRef(RECONNECT_BASE_DELAY);
  const heartbeatTimer = useRef<ReturnType<typeof setInterval> | null>(null);

  const {
    setWsConnected,
    setSystemStatus,
    setPrices,
    setOpportunities,
    addTrade,
    addLog,
  } = useStore();

  /** 处理收到的 WebSocket 消息 */
  const handleMessage = useCallback(
    (msg: WSMessage) => {
      switch (msg.type) {
        case 'status':
          setSystemStatus(msg.data as SystemStatus);
          break;
        case 'prices':
          setPrices(msg.data as PriceSnapshot);
          break;
        case 'opportunities':
          setOpportunities(msg.data as ArbitrageOpportunity[]);
          break;
        case 'trade':
          addTrade(msg.data as TradeResult);
          break;
        case 'logs':
          addLog(msg.data as LogEntry);
          break;
      }
    },
    [setSystemStatus, setPrices, setOpportunities, addTrade, addLog],
  );

  /** 建立 WebSocket 连接 */
  const connect = useCallback(() => {
    const url = getWsUrl();
    let ws: WebSocket;
    try {
      ws = new WebSocket(url);
    } catch (e) {
      console.error('WebSocket 创建失败:', e);
      scheduleReconnect();
      return;
    }

    wsRef.current = ws;

    ws.onopen = () => {
      setWsConnected(true);
      reconnectDelay.current = RECONNECT_BASE_DELAY;
      // 启动心跳
      heartbeatTimer.current = setInterval(() => {
        if (ws.readyState === WebSocket.OPEN) {
          ws.send('ping');
        }
      }, HEARTBEAT_INTERVAL);
    };

    ws.onmessage = (event) => {
      try {
        const msg = JSON.parse(event.data) as WSMessage;
        handleMessage(msg);
      } catch (e) {
        console.error('消息解析失败:', e);
      }
    };

    ws.onclose = () => {
      setWsConnected(false);
      if (heartbeatTimer.current) {
        clearInterval(heartbeatTimer.current);
        heartbeatTimer.current = null;
      }
      scheduleReconnect();
    };

    ws.onerror = (e) => {
      console.error('WebSocket 错误:', e);
    };
  }, [handleMessage, setWsConnected]);

  /** 安排重连（指数退避） */
  const scheduleReconnect = useCallback(() => {
    setTimeout(() => {
      connect();
    }, reconnectDelay.current);
    reconnectDelay.current = Math.min(
      reconnectDelay.current * 2,
      RECONNECT_MAX_DELAY,
    );
  }, [connect]);

  /** 主动关闭连接 */
  const disconnect = useCallback(() => {
    if (heartbeatTimer.current) {
      clearInterval(heartbeatTimer.current);
      heartbeatTimer.current = null;
    }
    if (wsRef.current) {
      wsRef.current.close();
      wsRef.current = null;
    }
  }, []);

  useEffect(() => {
    connect();
    return () => {
      disconnect();
    };
  }, [connect, disconnect]);

  return { disconnect, reconnect: connect };
}
